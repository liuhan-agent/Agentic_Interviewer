from __future__ import annotations

import threading
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1 import interview as interview_api
from app.core.session_auth import hash_session_token


class _RecoveredHandle:
    session_id = "sess-recover"
    trace_id = "trace-recover"
    current_question = {"question": "Q?", "dimension": "system_design"}
    turn_idx = 2
    max_turns = 8
    cancelled = False
    error = None
    error_kind = None
    final_state: dict[str, Any] | None = None
    llm_config: dict[str, Any] | None = None

    def __init__(self) -> None:
        self.done_event = threading.Event()
        self.question_event = threading.Event()
        self.question_event.set()
        self.session_token_hash = hash_session_token("session-secret")
        self.llm_config_meta: dict[str, Any] | None = None


class _RecoveringManager:
    def __init__(self) -> None:
        self.handle = _RecoveredHandle()
        self.recover_calls: list[str] = []
        self.submitted: list[dict[str, Any]] = []
        self.skipped: list[dict[str, Any]] = []
        self.hints: list[dict[str, Any]] = []

    def get(self, session_id: str) -> None:
        return None

    def recover_waiting_session(self, session_id: str) -> _RecoveredHandle | None:
        self.recover_calls.append(session_id)
        return self.handle if session_id == self.handle.session_id else None

    def submit_answer(
        self,
        session_id: str,
        answer: str,
        *,
        turn_idx: int,
        video_signals: dict[str, Any] | None = None,
        llm_config: dict[str, Any] | None = None,
    ) -> None:
        if self.handle.llm_config_meta and self.handle.llm_config_meta.get(
            "requires_reauth"
        ) and llm_config is None:
            raise ValueError("llm_config reauth_required")
        self.submitted.append(
            {
                "session_id": session_id,
                "answer": answer,
                "turn_idx": turn_idx,
                "video_signals": video_signals,
                "llm_config": llm_config,
            }
        )

    def skip_question(
        self,
        session_id: str,
        *,
        turn_idx: int,
        reason: str | None = None,
    ) -> None:
        self.skipped.append(
            {"session_id": session_id, "turn_idx": turn_idx, "reason": reason}
        )

    def request_hint(
        self,
        session_id: str,
        *,
        turn_idx: int,
        llm_config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.hints.append(
            {"session_id": session_id, "turn_idx": turn_idx, "llm_config": llm_config}
        )
        return {
            "session_id": session_id,
            "turn_idx": turn_idx,
            "hint": "先讲目标、约束和验证方式。",
            "source": "contract",
        }


def _client(manager: _RecoveringManager) -> TestClient:
    app = FastAPI()
    app.include_router(interview_api.router)
    return TestClient(app)


def test_submit_answer_recovers_waiting_session_before_forwarding(
    monkeypatch,
) -> None:
    manager = _RecoveringManager()
    monkeypatch.setattr(interview_api, "get_session_manager", lambda: manager)
    http = _client(manager)

    resp = http.post(
        "/api/v1/interview/sessions/sess-recover/answer",
        headers={"X-Session-Token": "session-secret"},
        json={"answer": "A", "turn_idx": 2},
    )

    assert resp.status_code == 200
    assert manager.recover_calls == ["sess-recover"]
    assert manager.submitted == [
        {
            "session_id": "sess-recover",
            "answer": "A",
            "turn_idx": 2,
            "video_signals": None,
            "llm_config": None,
        }
    ]


def test_skip_question_recovers_waiting_session_before_forwarding(
    monkeypatch,
) -> None:
    manager = _RecoveringManager()
    monkeypatch.setattr(interview_api, "get_session_manager", lambda: manager)
    http = _client(manager)

    resp = http.post(
        "/api/v1/interview/sessions/sess-recover/skip-question",
        headers={"X-Session-Token": "session-secret"},
        json={"turn_idx": 2, "reason": "candidate_skip"},
    )

    assert resp.status_code == 200
    assert manager.recover_calls == ["sess-recover"]
    assert manager.skipped == [
        {"session_id": "sess-recover", "turn_idx": 2, "reason": "candidate_skip"}
    ]


def test_hint_recovers_waiting_session_before_forwarding(monkeypatch) -> None:
    manager = _RecoveringManager()
    monkeypatch.setattr(interview_api, "get_session_manager", lambda: manager)
    http = _client(manager)

    resp = http.post(
        "/api/v1/interview/sessions/sess-recover/hint",
        headers={"X-Session-Token": "session-secret"},
        json={"turn_idx": 2},
    )

    assert resp.status_code == 200
    assert manager.recover_calls == ["sess-recover"]
    assert manager.hints == [
        {"session_id": "sess-recover", "turn_idx": 2, "llm_config": None}
    ]


def test_voice_ticket_recovers_waiting_session_before_issuing_ticket(
    monkeypatch,
) -> None:
    manager = _RecoveringManager()
    monkeypatch.setattr(interview_api, "get_session_manager", lambda: manager)
    http = _client(manager)

    resp = http.post(
        "/api/v1/interview/sessions/sess-recover/voice-ticket",
        headers={"X-Session-Token": "session-secret"},
    )

    assert resp.status_code == 200
    assert manager.recover_calls == ["sess-recover"]
    assert isinstance(resp.json()["ticket"], str)


def test_recovered_submit_answer_returns_reauth_required_without_llm_config(
    monkeypatch,
) -> None:
    manager = _RecoveringManager()
    manager.handle.llm_config_meta = {"requires_reauth": True}
    monkeypatch.setattr(interview_api, "get_session_manager", lambda: manager)
    http = _client(manager)

    resp = http.post(
        "/api/v1/interview/sessions/sess-recover/answer",
        headers={"X-Session-Token": "session-secret"},
        json={"answer": "A", "turn_idx": 2},
    )

    assert resp.status_code == 409
    assert resp.json()["detail"] == {
        "error": "reauth_required",
        "message": "This interview needs your personal LLM configuration again.",
    }
    assert manager.recover_calls == ["sess-recover"]
    assert manager.submitted == []


def test_recovered_submit_answer_accepts_fresh_llm_config(
    monkeypatch,
) -> None:
    manager = _RecoveringManager()
    manager.handle.llm_config_meta = {"requires_reauth": True}
    monkeypatch.setattr(interview_api, "get_session_manager", lambda: manager)
    http = _client(manager)
    llm_config = {
        "provider": "qwen",
        "api_key": "secret",
        "model": "qwen-plus",
    }

    resp = http.post(
        "/api/v1/interview/sessions/sess-recover/answer",
        headers={"X-Session-Token": "session-secret"},
        json={"answer": "A", "turn_idx": 2, "llm_config": llm_config},
    )

    assert resp.status_code == 200
    assert manager.recover_calls == ["sess-recover"]
    assert manager.submitted == [
        {
            "session_id": "sess-recover",
            "answer": "A",
            "turn_idx": 2,
            "video_signals": None,
            "llm_config": llm_config,
        }
    ]
