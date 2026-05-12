"""Interview endpoints surface structured LLM failure kinds."""
from __future__ import annotations

from threading import Event
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1 import interview as interview_api


class _Handle:
    def __init__(self) -> None:
        self.trace_id = "trace-error"
        self.done_event = Event()
        self.done_event.set()
        self.final_state: dict[str, Any] | None = {"final_report": None}
        self.current_question = None
        self.turn_idx = 0
        # Mirrors prod ``SessionHandle.max_turns`` which the interview
        # API reads when shaping poll/resume responses (`interview.py`
        # accesses ``handle.max_turns`` around line 1042). Default 8
        # matches ``state.build_initial_state``.
        self.max_turns = 8
        self.cancelled = False
        self.error = "invalid api key"
        self.error_kind = "auth"


class _Manager:
    def __init__(self) -> None:
        self.handle = _Handle()

    def get(self, session_id: str) -> _Handle | None:
        return self.handle if session_id == "sess-error" else None

    def wait_for_next_question(
        self,
        session_id: str,
        timeout: float = 30.0,
    ) -> dict[str, Any] | None:
        return None


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(interview_api, "get_session_manager", lambda: _Manager())
    app = FastAPI()
    app.include_router(interview_api.router)
    return TestClient(app)


def test_poll_question_returns_error_kind_for_failed_session(
    client: TestClient,
) -> None:
    resp = client.get("/api/v1/interview/sessions/sess-error/question?timeout=0.1")

    assert resp.status_code == 200
    # ``previous_turn_evaluation`` and ``server_latency_ms`` are part of
    # the poll contract on every branch (see
    # ``test_realtime_feedback_api.py`` and ``test_segment_latency_api.py``);
    # the legacy ``_Handle`` mock here doesn't define
    # ``last_turn_evaluation`` / ``last_segment_latency_ms`` so both
    # surface as ``None``. Matching the full payload keeps the contract
    # assertion tight.
    body = resp.json()
    assert body["session_id"] == "sess-error"
    assert body["status"] == "error"
    assert body["question"] is None
    assert body["error"] == "invalid api key"
    assert body["error_kind"] == "auth"


def test_poll_question_clamps_excessive_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handle = _Handle()
    handle.done_event.clear()
    handle.error = None
    handle.error_kind = None
    seen: list[float] = []

    class _SlowManager:
        def get(self, session_id: str) -> _Handle | None:
            return handle if session_id == "sess-slow" else None

        def wait_for_next_question(
            self,
            session_id: str,
            timeout: float = 30.0,
        ) -> dict[str, Any] | None:
            seen.append(timeout)
            return None

    monkeypatch.setattr(interview_api, "get_session_manager", lambda: _SlowManager())
    app = FastAPI()
    app.include_router(interview_api.router)
    local_client = TestClient(app)

    resp = local_client.get(
        "/api/v1/interview/sessions/sess-slow/question?timeout=999999"
    )

    assert resp.status_code == 200
    assert seen == [60.0]


def test_resume_session_returns_error_kind_for_failed_session(
    client: TestClient,
) -> None:
    resp = client.get("/api/v1/interview/sessions/sess-error/resume")

    assert resp.status_code == 200
    assert resp.json() == {
        "session_id": "sess-error",
        "status": "error",
        "question": None,
        "error": "invalid api key",
        "error_kind": "auth",
        "enable_video_analysis": False,
    }


def test_resume_session_returns_persisted_error_when_handle_missing(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        interview_api,
        "_terminal_payload_from_persisted_session",
        lambda session_id: {
            "session_id": session_id,
            "status": "error",
            "question": None,
            "error": "这场面试已结束，无法继续，请重新开始一场。",
            "error_kind": None,
        },
    )

    resp = client.get("/api/v1/interview/sessions/sess-persisted-error/resume")

    assert resp.status_code == 200
    assert resp.json() == {
        "session_id": "sess-persisted-error",
        "status": "error",
        "question": None,
        "error": "这场面试已结束，无法继续，请重新开始一场。",
        "error_kind": None,
    }


def test_terminal_payload_uses_persisted_error_details(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Row:
        status = "errored"
        final_report = None
        error = "invalid api key"
        error_kind = "auth"
        retryable = True

    class _Db:
        def __enter__(self) -> _Db:
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        def get(self, model, session_id: str) -> _Row:
            return _Row()

    import app.models.base as base_mod

    monkeypatch.setattr(base_mod, "get_session", lambda: _Db())

    assert interview_api._terminal_payload_from_persisted_session(
        "sess-persisted",
        retryable=False,
    ) == {
        "session_id": "sess-persisted",
        "status": "error",
        "question": None,
        "error": "invalid api key",
        "error_kind": "auth",
        "retryable": True,
        "enable_video_analysis": False,
    }


def test_get_report_returns_error_kind_for_failed_session(
    client: TestClient,
) -> None:
    resp = client.get("/api/v1/interview/sessions/sess-error/report")

    assert resp.status_code == 200
    body = resp.json()
    # ``trace_health`` is enriched on every report payload (PR-A); strip
    # it so the legacy assertion can still focus on the error fields.
    body.pop("trace_health", None)
    assert body == {
        "session_id": "sess-error",
        "final_report": None,
        "error": "invalid api key",
        "error_kind": "auth",
    }


def test_report_payload_uses_persisted_error_details(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Row:
        status = "errored"
        final_report = None
        error = "invalid api key"
        error_kind = "auth"

    class _Db:
        def __enter__(self) -> _Db:
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        def get(self, model, session_id: str) -> _Row:
            return _Row()

    import app.models.base as base_mod

    monkeypatch.setattr(base_mod, "get_session", lambda: _Db())

    payload = interview_api._report_payload_from_persisted_session("sess-persisted")
    assert payload is not None
    payload.pop("trace_health", None)
    assert payload == {
        "session_id": "sess-persisted",
        "final_report": None,
        "error": "invalid api key",
        "error_kind": "auth",
    }


def test_get_report_returns_persisted_report_when_handle_missing(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        interview_api,
        "_report_payload_from_persisted_session",
        lambda session_id: {
            "session_id": session_id,
            "final_report": {"overall_score": 8.2},
            "error": None,
        },
    )

    resp = client.get("/api/v1/interview/sessions/sess-persisted-done/report")

    assert resp.status_code == 200
    assert resp.json() == {
        "session_id": "sess-persisted-done",
        "final_report": {"overall_score": 8.2},
        "error": None,
    }


def test_done_cancelled_session_resumes_as_cancelled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handle = _Handle()
    handle.cancelled = True
    handle.final_state = {"status": "cancelled", "final_report": None}
    handle.error = None
    handle.error_kind = None

    class _CancelledManager:
        def get(self, session_id: str) -> _Handle | None:
            return handle if session_id == "sess-cancelled" else None

    monkeypatch.setattr(
        interview_api,
        "get_session_manager",
        lambda: _CancelledManager(),
    )
    app = FastAPI()
    app.include_router(interview_api.router)
    local_client = TestClient(app)

    resp = local_client.get("/api/v1/interview/sessions/sess-cancelled/resume")

    assert resp.status_code == 200
    assert resp.json() == {
        "session_id": "sess-cancelled",
        "status": "cancelled",
        "question": None,
        "max_turns": 8,
        "enable_video_analysis": False,
        "history": [],
    }


def test_done_cancelled_session_report_returns_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handle = _Handle()
    handle.cancelled = True
    handle.final_state = {"status": "cancelled", "final_report": None}
    handle.error = None
    handle.error_kind = None

    class _CancelledManager:
        def get(self, session_id: str) -> _Handle | None:
            return handle if session_id == "sess-cancelled" else None

    monkeypatch.setattr(
        interview_api,
        "get_session_manager",
        lambda: _CancelledManager(),
    )
    app = FastAPI()
    app.include_router(interview_api.router)
    local_client = TestClient(app)

    resp = local_client.get("/api/v1/interview/sessions/sess-cancelled/report")

    assert resp.status_code == 200
    body = resp.json()
    body.pop("trace_health", None)
    assert body == {
        "session_id": "sess-cancelled",
        "final_report": None,
        "error": "session cancelled",
        "error_kind": None,
    }


def test_resume_session_recovers_waiting_checkpoint_when_handle_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handle = _Handle()
    handle.done_event.clear()
    handle.error = None
    handle.error_kind = None
    handle.current_question = {"question": "Tell me about a system."}
    handle.turn_idx = 2

    class _RecoverManager:
        def get(self, session_id: str) -> None:
            return None

        def recover_waiting_session(self, session_id: str) -> _Handle | None:
            return handle if session_id == "sess-recover" else None

        def can_retry_failed_question(self, session_id: str) -> bool:
            return False

    monkeypatch.setattr(
        interview_api,
        "get_session_manager",
        lambda: _RecoverManager(),
    )
    app = FastAPI()
    app.include_router(interview_api.router)
    local_client = TestClient(app)

    resp = local_client.get("/api/v1/interview/sessions/sess-recover/resume")

    assert resp.status_code == 200
    assert resp.json() == {
        "session_id": "sess-recover",
        "status": "waiting_for_answer",
        "turn_idx": 2,
        "max_turns": 8,
        "question": {"question": "Tell me about a system."},
        "enable_video_analysis": False,
        "previous_turn_evaluation": None,
        "history": [],
    }


def test_retry_failed_question_endpoint_starts_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, dict[str, Any] | None]] = []

    class _RetryManager:
        def get(self, session_id: str) -> None:
            return None

        def retry_failed_question(
            self,
            session_id: str,
            *,
            llm_config: dict[str, Any] | None = None,
        ) -> object | None:
            calls.append((session_id, llm_config))
            return object()

    monkeypatch.setattr(interview_api, "get_session_manager", lambda: _RetryManager())
    app = FastAPI()
    app.include_router(interview_api.router)
    local_client = TestClient(app)

    llm_config = {
        "provider": "qwen",
        "api_key": "fresh-key",
        "model": "qwen3.6-flash",
    }
    resp = local_client.post(
        "/api/v1/interview/sessions/sess-retry/retry-question",
        json={"llm_config": llm_config},
    )

    assert resp.status_code == 200
    assert resp.json() == {"session_id": "sess-retry", "status": "retrying"}
    assert calls == [("sess-retry", llm_config)]


def test_retry_failed_question_endpoint_rejects_non_retryable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _RetryManager:
        def get(self, session_id: str) -> None:
            return None

        def retry_failed_question(
            self,
            session_id: str,
            *,
            llm_config: dict[str, Any] | None = None,
        ) -> object | None:
            return None

    monkeypatch.setattr(interview_api, "get_session_manager", lambda: _RetryManager())
    app = FastAPI()
    app.include_router(interview_api.router)
    local_client = TestClient(app)

    resp = local_client.post("/api/v1/interview/sessions/sess-nope/retry-question")

    assert resp.status_code == 409
    assert resp.json()["detail"]["error"] == "question retry is not available"


def test_redact_llm_secrets_handles_nested_role_keys() -> None:
    from app.engine.agents.llm_client import redact_llm_secrets

    config = {
        "api_key": "default-key",
        "role_overrides": {
            "verifier": {"api_key": "verifier-key"},
        },
    }

    assert redact_llm_secrets(
        "default-key failed; verifier-key also failed",
        config,
    ) == "[redacted-api-key] failed; [redacted-api-key] also failed"
