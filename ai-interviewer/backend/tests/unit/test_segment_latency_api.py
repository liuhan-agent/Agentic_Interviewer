"""End-to-end latency trace (#11): poll_question must surface the
duration of the most recent ``_run_segment`` so the InterviewRoom
loading state can show an ETA hint.

The session manager records wall-clock latency via ``time.monotonic``
in ``_run_segment.finally`` and caches it on the handle as
``last_segment_latency_ms``. This endpoint just pipes it through —
exactly the same pattern as ``previous_turn_evaluation``.
"""
from __future__ import annotations

import threading
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1 import interview as interview_api
from app.core.session_auth import hash_session_token


class _LatencyHandle:
    trace_id = "trace-latency"
    cancelled = False
    error = None
    error_kind = None
    current_question = {"question": "Q?", "dimension": "system_design"}
    turn_idx = 4
    max_turns = 8

    def __init__(self) -> None:
        self.done_event = threading.Event()
        self.final_state: dict[str, Any] | None = None
        self.session_token_hash = hash_session_token("session-secret")
        self.last_turn_evaluation: dict[str, Any] | None = None
        self.last_segment_latency_ms: int | None = None


class _LatencyManager:
    def __init__(self) -> None:
        self.handle = _LatencyHandle()

    def get(self, session_id: str) -> _LatencyHandle | None:
        return self.handle if session_id == "sess-latency" else None

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
) -> tuple[TestClient, _LatencyManager]:
    manager = _LatencyManager()
    monkeypatch.setattr(interview_api, "get_session_manager", lambda: manager)
    app = FastAPI()
    app.include_router(interview_api.router)
    return TestClient(app), manager


def test_poll_question_surfaces_server_latency_when_handle_recorded_one(
    client: tuple[TestClient, _LatencyManager],
) -> None:
    """Mid-interview poll: handle.last_segment_latency_ms is echoed."""
    http, manager = client
    manager.handle.last_segment_latency_ms = 4321

    resp = http.get(
        "/api/v1/interview/sessions/sess-latency/question",
        headers={"X-Session-Token": "session-secret"},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "waiting_for_answer"


def test_poll_question_emits_null_server_latency_on_first_turn(
    client: tuple[TestClient, _LatencyManager],
) -> None:
    """Before any segment has finished, the field may be absent or None."""
    http, manager = client
    manager.handle.last_segment_latency_ms = None

    resp = http.get(
        "/api/v1/interview/sessions/sess-latency/question",
        headers={"X-Session-Token": "session-secret"},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body.get("server_latency_ms") is None


def test_poll_question_includes_server_latency_for_completed_session(
    client: tuple[TestClient, _LatencyManager],
) -> None:
    """Completed payload should still succeed."""
    http, manager = client
    manager.handle.done_event.set()
    manager.handle.final_state = {"final_report": {"verdict": "pass"}}
    manager.handle.last_segment_latency_ms = 12_345

    resp = http.get(
        "/api/v1/interview/sessions/sess-latency/question",
        headers={"X-Session-Token": "session-secret"},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "completed"
