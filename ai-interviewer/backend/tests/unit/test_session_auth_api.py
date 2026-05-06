from __future__ import annotations

import threading
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1 import interview as interview_api
from app.core.session_auth import hash_session_token


class _Handle:
    trace_id = "trace-auth"
    done_event: threading.Event
    final_state: dict[str, Any] | None
    cancelled = False
    error = None
    error_kind = None
    current_question = {"question": "Q", "dimension": "technical_depth"}
    turn_idx = 2
    max_turns = 8

    def __init__(self) -> None:
        self.done_event = threading.Event()
        self.final_state = None
        self.session_token_hash = hash_session_token("session-secret")


class _Manager:
    def __init__(self) -> None:
        self.handle = _Handle()
        self.submitted: list[dict[str, Any]] = []
        self.skipped: list[dict[str, Any]] = []
        self.hints: list[dict[str, Any]] = []
        self.reauth_required = False

    def get(self, session_id: str) -> _Handle | None:
        return self.handle if session_id == "sess-auth" else None

    def wait_for_next_question(
        self,
        session_id: str,
        timeout: float = 30.0,
    ) -> dict[str, Any] | None:
        return self.handle.current_question

    def submit_answer(
        self,
        session_id: str,
        answer: str,
        *,
        turn_idx: int,
        video_signals: dict[str, Any] | None = None,
        llm_config: dict[str, Any] | None = None,
    ) -> None:
        if self.reauth_required:
            raise ValueError("llm_config reauth_required")
        if turn_idx != self.handle.turn_idx:
            raise ValueError("turn_idx mismatch")
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
        if turn_idx != self.handle.turn_idx:
            raise ValueError("turn_idx mismatch")
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
        if session_id != "sess-auth":
            raise KeyError(session_id)
        if turn_idx != self.handle.turn_idx:
            raise ValueError("turn_idx mismatch")
        if self.reauth_required:
            raise ValueError("llm_config reauth_required")
        self.hints.append(
            {"session_id": session_id, "turn_idx": turn_idx, "llm_config": llm_config}
        )
        return {
            "session_id": session_id,
            "turn_idx": turn_idx,
            "hint": "可以先从目标、约束和验证方式三个角度组织回答。",
            "source": "contract",
        }


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, _Manager]:
    manager = _Manager()
    monkeypatch.setattr(interview_api, "get_session_manager", lambda: manager)
    app = FastAPI()
    app.include_router(interview_api.router)
    return TestClient(app), manager


def test_session_endpoint_rejects_missing_token(
    client: tuple[TestClient, _Manager],
) -> None:
    http, _manager = client

    resp = http.get("/api/v1/interview/sessions/sess-auth/question")

    assert resp.status_code == 401


@pytest.mark.parametrize(
    ("method", "suffix", "json_body"),
    [
        ("get", "question", None),
        ("post", "answer", {"answer": "A", "turn_idx": 2}),
        ("get", "resume", None),
    ],
)
def test_session_endpoints_reject_invalid_path_session_id(
    client: tuple[TestClient, _Manager],
    method: str,
    suffix: str,
    json_body: dict[str, Any] | None,
) -> None:
    http, _manager = client
    url = f"/api/v1/interview/sessions/{'x' * 65}/{suffix}"
    kwargs: dict[str, Any] = {"headers": {"X-Session-Token": "session-secret"}}
    if json_body is not None:
        kwargs["json"] = json_body

    resp = getattr(http, method)(url, **kwargs)

    assert resp.status_code == 422


def test_session_endpoint_rejects_illegal_path_session_id(
    client: tuple[TestClient, _Manager],
) -> None:
    http, _manager = client

    resp = http.get(
        "/api/v1/interview/sessions/bad%20id/question",
        headers={"X-Session-Token": "session-secret"},
    )

    assert resp.status_code == 422


def test_session_endpoint_rejects_wrong_token(
    client: tuple[TestClient, _Manager],
) -> None:
    http, _manager = client

    resp = http.get(
        "/api/v1/interview/sessions/sess-auth/question",
        headers={"X-Session-Token": "wrong"},
    )

    assert resp.status_code == 403


def test_session_endpoint_accepts_correct_token(
    client: tuple[TestClient, _Manager],
) -> None:
    http, _manager = client

    resp = http.get(
        "/api/v1/interview/sessions/sess-auth/question",
        headers={"X-Session-Token": "session-secret"},
    )

    assert resp.status_code == 200
    assert resp.json()["question"] == {"question": "Q", "dimension": "technical_depth"}
    assert resp.json()["max_turns"] == 8


def test_resume_endpoint_includes_max_turns(
    client: tuple[TestClient, _Manager],
) -> None:
    http, _manager = client

    resp = http.get(
        "/api/v1/interview/sessions/sess-auth/resume",
        headers={"X-Session-Token": "session-secret"},
    )

    assert resp.status_code == 200
    assert resp.json()["max_turns"] == 8


def test_voice_ticket_endpoint_requires_session_token(
    client: tuple[TestClient, _Manager],
) -> None:
    http, _manager = client

    resp = http.post("/api/v1/interview/sessions/sess-auth/voice-ticket")

    assert resp.status_code == 401


def test_voice_ticket_endpoint_issues_short_lived_ticket(
    client: tuple[TestClient, _Manager],
) -> None:
    http, _manager = client

    resp = http.post(
        "/api/v1/interview/sessions/sess-auth/voice-ticket",
        headers={"X-Session-Token": "session-secret"},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body["ticket"], str)
    assert body["expires_in_seconds"] > 0


def test_submit_answer_requires_turn_idx(
    client: tuple[TestClient, _Manager],
) -> None:
    http, _manager = client

    resp = http.post(
        "/api/v1/interview/sessions/sess-auth/answer",
        headers={"X-Session-Token": "session-secret"},
        json={"answer": "A"},
    )

    assert resp.status_code == 422


def test_submit_answer_returns_conflict_for_stale_turn_idx(
    client: tuple[TestClient, _Manager],
) -> None:
    http, _manager = client

    resp = http.post(
        "/api/v1/interview/sessions/sess-auth/answer",
        headers={"X-Session-Token": "session-secret"},
        json={"answer": "A", "turn_idx": 1},
    )

    assert resp.status_code == 409
    assert "turn_idx" in resp.text


def test_submit_answer_forwards_turn_idx_and_llm_config(
    client: tuple[TestClient, _Manager],
) -> None:
    http, manager = client

    resp = http.post(
        "/api/v1/interview/sessions/sess-auth/answer",
        headers={"X-Session-Token": "session-secret"},
        json={
            "answer": "A",
            "turn_idx": 2,
            "llm_config": {
                "provider": "qwen",
                "api_key": "secret",
                "model": "qwen3.6-flash",
            },
        },
    )

    assert resp.status_code == 200
    assert manager.submitted == [
        {
            "session_id": "sess-auth",
            "answer": "A",
            "turn_idx": 2,
            "video_signals": None,
            "llm_config": {
                "provider": "qwen",
                "api_key": "secret",
                "model": "qwen3.6-flash",
            },
        }
    ]


def test_submit_answer_returns_structured_reauth_required(
    client: tuple[TestClient, _Manager],
) -> None:
    http, manager = client
    manager.reauth_required = True

    resp = http.post(
        "/api/v1/interview/sessions/sess-auth/answer",
        headers={"X-Session-Token": "session-secret"},
        json={"answer": "A", "turn_idx": 2},
    )

    assert resp.status_code == 409
    assert resp.json()["detail"] == {
        "error": "reauth_required",
        "message": "This interview needs your personal LLM configuration again.",
    }


def test_skip_question_requires_session_token(
    client: tuple[TestClient, _Manager],
) -> None:
    http, _manager = client

    resp = http.post(
        "/api/v1/interview/sessions/sess-auth/skip-question",
        json={"turn_idx": 2},
    )

    assert resp.status_code == 401


def test_skip_question_forwards_turn_idx_and_reason(
    client: tuple[TestClient, _Manager],
) -> None:
    http, manager = client

    resp = http.post(
        "/api/v1/interview/sessions/sess-auth/skip-question",
        headers={"X-Session-Token": "session-secret"},
        json={"turn_idx": 2, "reason": "想先练下一题"},
    )

    assert resp.status_code == 200
    assert resp.json() == {
        "session_id": "sess-auth",
        "accepted": True,
        "status": "skipped",
    }
    assert manager.skipped == [
        {"session_id": "sess-auth", "turn_idx": 2, "reason": "想先练下一题"}
    ]


def test_skip_question_returns_conflict_for_stale_turn_idx(
    client: tuple[TestClient, _Manager],
) -> None:
    http, _manager = client

    resp = http.post(
        "/api/v1/interview/sessions/sess-auth/skip-question",
        headers={"X-Session-Token": "session-secret"},
        json={"turn_idx": 1},
    )

    assert resp.status_code == 409
    assert "turn_idx" in resp.text


def test_hint_requires_session_token(
    client: tuple[TestClient, _Manager],
) -> None:
    http, _manager = client

    resp = http.post(
        "/api/v1/interview/sessions/sess-auth/hint",
        json={"turn_idx": 2},
    )

    assert resp.status_code == 401


def test_hint_returns_404_for_missing_session(
    client: tuple[TestClient, _Manager],
) -> None:
    http, _manager = client

    resp = http.post(
        "/api/v1/interview/sessions/sess-missing/hint",
        headers={"X-Session-Token": "session-secret"},
        json={"turn_idx": 2},
    )

    assert resp.status_code == 404


def test_hint_forwards_turn_idx_and_llm_config(
    client: tuple[TestClient, _Manager],
) -> None:
    http, manager = client

    resp = http.post(
        "/api/v1/interview/sessions/sess-auth/hint",
        headers={"X-Session-Token": "session-secret"},
        json={
            "turn_idx": 2,
            "llm_config": {
                "provider": "openai",
                "model": "gpt-4o-mini",
            },
        },
    )

    assert resp.status_code == 200
    assert resp.json() == {
        "session_id": "sess-auth",
        "turn_idx": 2,
        "hint": "可以先从目标、约束和验证方式三个角度组织回答。",
        "source": "contract",
    }
    assert manager.hints == [
        {
            "session_id": "sess-auth",
            "turn_idx": 2,
            "llm_config": {
                "provider": "openai",
                "model": "gpt-4o-mini",
            },
        }
    ]


def test_hint_rejects_stale_turn_idx(
    client: tuple[TestClient, _Manager],
) -> None:
    http, _manager = client

    resp = http.post(
        "/api/v1/interview/sessions/sess-auth/hint",
        headers={"X-Session-Token": "session-secret"},
        json={"turn_idx": 1},
    )

    assert resp.status_code == 409
    assert "turn_idx" in resp.text


def test_hint_returns_reauth_required(
    client: tuple[TestClient, _Manager],
) -> None:
    http, manager = client
    manager.reauth_required = True

    resp = http.post(
        "/api/v1/interview/sessions/sess-auth/hint",
        headers={"X-Session-Token": "session-secret"},
        json={"turn_idx": 2},
    )

    assert resp.status_code == 409
    assert resp.json()["detail"] == {
        "error": "reauth_required",
        "message": "This interview needs your personal LLM configuration again.",
    }


def test_submit_answer_rejects_text_above_max_length(
    client: tuple[TestClient, _Manager],
) -> None:
    http, manager = client

    resp = http.post(
        "/api/v1/interview/sessions/sess-auth/answer",
        headers={"X-Session-Token": "session-secret"},
        json={
            "answer": "x" * (interview_api.ANSWER_TEXT_MAX_LENGTH + 1),
            "turn_idx": 2,
        },
    )

    assert resp.status_code == 422
    assert manager.submitted == []


def test_submit_answer_accepts_answer_at_max_length(
    client: tuple[TestClient, _Manager],
) -> None:
    http, manager = client

    resp = http.post(
        "/api/v1/interview/sessions/sess-auth/answer",
        headers={"X-Session-Token": "session-secret"},
        json={
            "answer": "x" * interview_api.ANSWER_TEXT_MAX_LENGTH,
            "turn_idx": 2,
        },
    )

    assert resp.status_code == 200
    assert len(manager.submitted) == 1
    assert manager.submitted[0]["video_signals"] is None


def test_submit_answer_accepts_valid_video_signals(
    client: tuple[TestClient, _Manager],
) -> None:
    http, manager = client

    resp = http.post(
        "/api/v1/interview/sessions/sess-auth/answer",
        headers={"X-Session-Token": "session-secret"},
        json={
            "answer": "ok",
            "turn_idx": 2,
            "video_signals": {
                "confidence": 0.7,
                "engagement": 0.5,
                "dominant_emotion": "positive",
                "sample_count": 12,
            },
        },
    )

    assert resp.status_code == 200
    assert manager.submitted[-1]["video_signals"] == {
        "confidence": 0.7,
        "engagement": 0.5,
        "dominant_emotion": "positive",
        "sample_count": 12,
    }


@pytest.mark.parametrize(
    "video_signals",
    [
        # missing required field
        {
            "confidence": 0.5,
            "engagement": 0.5,
            "dominant_emotion": "neutral",
        },
        # confidence out of range
        {
            "confidence": 1.5,
            "engagement": 0.5,
            "dominant_emotion": "neutral",
            "sample_count": 5,
        },
        # invalid emotion enum
        {
            "confidence": 0.5,
            "engagement": 0.5,
            "dominant_emotion": "angry",
            "sample_count": 5,
        },
        # extra field forbidden
        {
            "confidence": 0.5,
            "engagement": 0.5,
            "dominant_emotion": "neutral",
            "sample_count": 5,
            "attention_score": 0.9,
        },
        # sample_count zero
        {
            "confidence": 0.5,
            "engagement": 0.5,
            "dominant_emotion": "neutral",
            "sample_count": 0,
        },
    ],
)
def test_submit_answer_rejects_invalid_video_signals(
    client: tuple[TestClient, _Manager],
    video_signals: dict[str, Any],
) -> None:
    http, manager = client

    resp = http.post(
        "/api/v1/interview/sessions/sess-auth/answer",
        headers={"X-Session-Token": "session-secret"},
        json={
            "answer": "ok",
            "turn_idx": 2,
            "video_signals": video_signals,
        },
    )

    assert resp.status_code == 422
    assert manager.submitted == []
