from __future__ import annotations

import threading
from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1 import interview as interview_api
from app.core.idempotency import reset_idempotency_store
from app.core.session_auth import hash_session_token


LIVE_CREATED_AT = datetime(2026, 5, 1, 9, 0, tzinfo=UTC)
LIVE_UPDATED_AT = datetime(2026, 5, 1, 9, 15, tzinfo=UTC)


class _RuntimeHandle:
    session_id = "sess-contract"
    trace_id = "trace-contract"
    current_question: dict[str, Any] | None = {
        "question": "请介绍一个你主导的系统设计。",
        "dimension": "system_design",
    }
    turn_idx = 3
    max_turns = 8
    cancelled = False
    error: str | None = None
    error_kind: str | None = None
    final_state: dict[str, Any] | None = None
    last_turn_evaluation: dict[str, Any] | None = None
    last_segment_latency_ms: int | None = None
    created_at = LIVE_CREATED_AT
    last_activity_at = LIVE_UPDATED_AT

    def __init__(self) -> None:
        self.done_event = threading.Event()
        self.question_event = threading.Event()
        self.question_event.set()
        self.session_token_hash = hash_session_token("session-secret")


class _RuntimeManager:
    def __init__(self) -> None:
        self.handle = _RuntimeHandle()
        self.recover_calls: list[str] = []
        self.submitted: list[dict[str, Any]] = []
        self.skipped: list[dict[str, Any]] = []
        self.hints: list[dict[str, Any]] = []
        self.retry_calls: list[str] = []

    def get(self, session_id: str) -> _RuntimeHandle | None:
        return self.handle if session_id == self.handle.session_id else None

    def recover_waiting_session(self, session_id: str) -> None:
        self.recover_calls.append(session_id)
        return None

    def wait_for_next_question(
        self,
        session_id: str,
        timeout: float = 30.0,
    ) -> dict[str, Any] | None:
        assert session_id == self.handle.session_id
        assert timeout >= 0
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
        if turn_idx != self.handle.turn_idx:
            raise ValueError("turn_idx mismatch")
        self.hints.append(
            {"session_id": session_id, "turn_idx": turn_idx, "llm_config": llm_config}
        )
        return {
            "session_id": session_id,
            "turn_idx": turn_idx,
            "hint": "先讲目标、约束和验证方式。",
            "source": "contract",
        }

    def retry_failed_question(
        self,
        session_id: str,
        *,
        llm_config: dict[str, Any] | None = None,
    ) -> _RuntimeHandle | None:
        self.retry_calls.append(session_id)
        return self.handle


def _client(monkeypatch) -> tuple[TestClient, _RuntimeManager]:
    manager = _RuntimeManager()
    monkeypatch.setattr(interview_api, "get_session_manager", lambda: manager)
    monkeypatch.setattr(
        interview_api,
        "_attach_trace_health",
        lambda payload, _session_id: {**payload, "trace_health": "ok"},
    )
    reset_idempotency_store()
    app = FastAPI()
    app.include_router(interview_api.router)
    return TestClient(app), manager


def test_poll_question_waiting_response_contract(monkeypatch) -> None:
    http, manager = _client(monkeypatch)
    manager.handle.last_turn_evaluation = {"score": 7, "passed": True}
    manager.handle.last_segment_latency_ms = 456

    resp = http.get(
        "/api/v1/interview/sessions/sess-contract/question",
        headers={"X-Session-Token": "session-secret"},
    )

    assert resp.status_code == 200
    assert resp.json() == {
        "session_id": "sess-contract",
        "status": "waiting_for_answer",
        "turn_idx": 3,
        "question": {
            "question": "请介绍一个你主导的系统设计。",
            "dimension": "system_design",
        },
        "max_turns": 8,
        "previous_turn_evaluation": {"score": 7, "passed": True},
        "server_latency_ms": 456,
    }


def test_poll_question_terminal_response_contracts(monkeypatch) -> None:
    http, manager = _client(monkeypatch)
    manager.handle.current_question = None
    manager.handle.done_event.set()
    manager.handle.final_state = {
        "status": "completed",
        "final_report": {"overall_score": 8.2},
    }

    completed = http.get(
        "/api/v1/interview/sessions/sess-contract/question",
        headers={"X-Session-Token": "session-secret"},
    )
    assert completed.status_code == 200
    assert completed.json() == {
        "session_id": "sess-contract",
        "status": "completed",
        "question": None,
        "final_report": {"overall_score": 8.2},
        "max_turns": 8,
        "previous_turn_evaluation": None,
        "server_latency_ms": None,
    }

    manager.handle.cancelled = True
    cancelled = http.get(
        "/api/v1/interview/sessions/sess-contract/question",
        headers={"X-Session-Token": "session-secret"},
    )
    assert cancelled.status_code == 200
    assert cancelled.json() == {
        "session_id": "sess-contract",
        "status": "cancelled",
        "question": None,
        "max_turns": 8,
        "previous_turn_evaluation": None,
        "server_latency_ms": None,
    }

    manager.handle.cancelled = False
    manager.handle.error = "question generation failed"
    manager.handle.error_kind = "question_generation_failed"
    errored = http.get(
        "/api/v1/interview/sessions/sess-contract/question",
        headers={"X-Session-Token": "session-secret"},
    )
    assert errored.status_code == 200
    assert errored.json() == {
        "session_id": "sess-contract",
        "status": "error",
        "question": None,
        "error": "question generation failed",
        "error_kind": "question_generation_failed",
        "previous_turn_evaluation": None,
        "server_latency_ms": None,
    }


def test_answer_skip_hint_and_retry_contracts(monkeypatch) -> None:
    http, manager = _client(monkeypatch)

    answer = http.post(
        "/api/v1/interview/sessions/sess-contract/answer",
        headers={
            "X-Session-Token": "session-secret",
            "Idempotency-Key": "contract-key-1",
        },
        json={
            "answer": "我会先确认 QPS 和一致性要求。",
            "turn_idx": 3,
            "video_signals": {
                "confidence": 0.8,
                "engagement": 0.7,
                "dominant_emotion": "neutral",
                "sample_count": 5,
            },
        },
    )
    assert answer.status_code == 200
    assert answer.json() == {"session_id": "sess-contract", "accepted": True}
    assert manager.submitted[-1]["video_signals"] == {
        "confidence": 0.8,
        "engagement": 0.7,
        "dominant_emotion": "neutral",
        "sample_count": 5,
    }

    replay = http.post(
        "/api/v1/interview/sessions/sess-contract/answer",
        headers={
            "X-Session-Token": "session-secret",
            "Idempotency-Key": "contract-key-1",
        },
        json={
            "answer": "我会先确认 QPS 和一致性要求。",
            "turn_idx": 3,
            "video_signals": {
                "confidence": 0.8,
                "engagement": 0.7,
                "dominant_emotion": "neutral",
                "sample_count": 5,
            },
        },
    )
    assert replay.status_code == 200
    assert replay.json() == answer.json()
    assert len(manager.submitted) == 1

    conflict = http.post(
        "/api/v1/interview/sessions/sess-contract/answer",
        headers={
            "X-Session-Token": "session-secret",
            "Idempotency-Key": "contract-key-1",
        },
        json={"answer": "另一版答案", "turn_idx": 3},
    )
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "idempotency_conflict"

    skipped = http.post(
        "/api/v1/interview/sessions/sess-contract/skip-question",
        headers={"X-Session-Token": "session-secret"},
        json={"turn_idx": 3, "reason": "candidate_skip"},
    )
    assert skipped.status_code == 200
    assert skipped.json() == {
        "session_id": "sess-contract",
        "accepted": True,
        "status": "skipped",
    }

    hint = http.post(
        "/api/v1/interview/sessions/sess-contract/hint",
        headers={"X-Session-Token": "session-secret"},
        json={"turn_idx": 3},
    )
    assert hint.status_code == 200
    assert hint.json() == {
        "session_id": "sess-contract",
        "turn_idx": 3,
        "hint": "先讲目标、约束和验证方式。",
        "source": "contract",
    }

    retry = http.post(
        "/api/v1/interview/sessions/sess-contract/retry-question",
        headers={"X-Session-Token": "session-secret"},
    )
    assert retry.status_code == 200
    assert retry.json() == {"session_id": "sess-contract", "status": "retrying"}
    assert manager.retry_calls == ["sess-contract"]


def test_report_resume_and_replay_status_contracts(monkeypatch) -> None:
    http, manager = _client(monkeypatch)

    running_report = http.get(
        "/api/v1/interview/sessions/sess-contract/report",
        headers={"X-Session-Token": "session-secret"},
    )
    assert running_report.status_code == 409
    assert running_report.json()["detail"] == "interview still running"

    resume = http.get(
        "/api/v1/interview/sessions/sess-contract/resume",
        headers={"X-Session-Token": "session-secret"},
    )
    assert resume.status_code == 200
    assert resume.json() == {
        "session_id": "sess-contract",
        "status": "waiting_for_answer",
        "created_at": LIVE_CREATED_AT.isoformat(),
        "updated_at": LIVE_UPDATED_AT.isoformat(),
        "turn_idx": 3,
        "question": {
            "question": "请介绍一个你主导的系统设计。",
            "dimension": "system_design",
        },
        "max_turns": 8,
        "previous_turn_evaluation": None,
        "history": [],
    }

    manager.handle.done_event.set()
    manager.handle.current_question = None
    manager.handle.final_state = {
        "status": "completed",
        "final_report": {"overall_score": 8.2},
    }
    report = http.get(
        "/api/v1/interview/sessions/sess-contract/report",
        headers={"X-Session-Token": "session-secret"},
    )
    assert report.status_code == 200
    assert report.json() == {
        "session_id": "sess-contract",
        "created_at": LIVE_CREATED_AT.isoformat(),
        "updated_at": LIVE_UPDATED_AT.isoformat(),
        "final_report": {"overall_score": 8.2},
        "error": None,
        "trace_health": "ok",
    }
