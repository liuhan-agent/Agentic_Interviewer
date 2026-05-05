"""Real-time feedback (#9): poll_question must surface the candidate's
last-turn evaluation summary so the InterviewRoom can display it next to
the freshly arrived question.

The intent is *not* to re-run scoring on the API path; the evaluation has
already happened during the previous graph segment. The session manager
caches a compact projection of ``state.qa_history[-1].evaluation`` on the
handle, and this endpoint just pipes it through.
"""
from __future__ import annotations

import threading
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1 import interview as interview_api
from app.core.session_auth import hash_session_token


class _FeedbackHandle:
    trace_id = "trace-feedback"
    cancelled = False
    error = None
    error_kind = None
    current_question = {"question": "Q?", "dimension": "system_design"}
    turn_idx = 3
    max_turns = 8

    def __init__(self) -> None:
        self.done_event = threading.Event()
        self.final_state: dict[str, Any] | None = None
        self.session_token_hash = hash_session_token("session-secret")
        self.last_turn_evaluation: dict[str, Any] | None = None


class _FeedbackManager:
    def __init__(self) -> None:
        self.handle = _FeedbackHandle()

    def get(self, session_id: str) -> _FeedbackHandle | None:
        return self.handle if session_id == "sess-feedback" else None

    def wait_for_next_question(
        self,
        session_id: str,
        timeout: float = 30.0,
    ) -> dict[str, Any] | None:
        if self.handle.done_event.is_set():
            return None
        return self.handle.current_question


@pytest.fixture()
def client(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[TestClient, _FeedbackManager]:
    manager = _FeedbackManager()
    monkeypatch.setattr(interview_api, "get_session_manager", lambda: manager)
    app = FastAPI()
    app.include_router(interview_api.router)
    return TestClient(app), manager


def test_poll_question_omits_previous_evaluation_when_handle_has_none(
    client: tuple[TestClient, _FeedbackManager],
) -> None:
    """First-turn poll: handle has no last_turn_evaluation, key is None."""
    http, manager = client
    manager.handle.last_turn_evaluation = None

    resp = http.get(
        "/api/v1/interview/sessions/sess-feedback/question",
        headers={"X-Session-Token": "session-secret"},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "waiting_for_answer"
    assert body["turn_idx"] == 3
    assert body["previous_turn_evaluation"] is None


def test_poll_question_surfaces_previous_evaluation_when_handle_has_one(
    client: tuple[TestClient, _FeedbackManager],
) -> None:
    """Mid-interview poll: handle.last_turn_evaluation projection is echoed."""
    http, manager = client
    manager.handle.last_turn_evaluation = {
        "turn_idx": 2,
        "dimension": "system_design",
        "score": 7.5,
        "passed": True,
        "strengths": ["架构层次清晰", "对取舍解释具体"],
        "weaknesses": ["容量估算不够量化"],
        "rubric_coverage": {
            "system_design": "covered",
            "trade_off_reasoning": "partial",
        },
    }

    resp = http.get(
        "/api/v1/interview/sessions/sess-feedback/question",
        headers={"X-Session-Token": "session-secret"},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "waiting_for_answer"
    assert body["previous_turn_evaluation"] == {
        "turn_idx": 2,
        "dimension": "system_design",
        "score": 7.5,
        "passed": True,
        "strengths": ["架构层次清晰", "对取舍解释具体"],
        "weaknesses": ["容量估算不够量化"],
        "rubric_coverage": {
            "system_design": "covered",
            "trade_off_reasoning": "partial",
        },
    }


def test_poll_question_includes_previous_evaluation_field_for_completed_session(
    client: tuple[TestClient, _FeedbackManager],
) -> None:
    """Even on a completed session payload, the field key is present
    (as None) so the frontend doesn't have to special-case its absence."""
    http, manager = client
    manager.handle.done_event.set()
    manager.handle.final_state = {"final_report": {"verdict": "pass"}}

    resp = http.get(
        "/api/v1/interview/sessions/sess-feedback/question",
        headers={"X-Session-Token": "session-secret"},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "completed"
    assert "previous_turn_evaluation" in body
    assert body["previous_turn_evaluation"] is None
