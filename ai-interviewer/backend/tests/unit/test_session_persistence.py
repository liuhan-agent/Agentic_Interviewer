from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any

from app.models.interview_session import InterviewSession
from app.services.session_persistence import SessionPersistence


class _FakeDb:
    def __init__(self) -> None:
        self.rows: dict[str, Any] = {}
        self.added: list[Any] = []

    def get(self, _model: Any, session_id: str) -> Any | None:
        return self.rows.get(session_id)

    def add(self, row: Any) -> None:
        self.rows[row.session_id] = row
        self.added.append(row)


def _session_factory(db: _FakeDb):
    @contextmanager
    def _get_session():
        yield db

    return _get_session


def _handle(**overrides: Any) -> SimpleNamespace:
    values = {
        "session_id": "sess-1",
        "trace_id": "trace-1",
        "session_token_hash": "token-hash",
        "llm_config_meta": {"provider": "stub"},
        "error": None,
        "error_kind": None,
        "asked_turn": 0,
        "enable_video_analysis": True,
        "setup_snapshot": {
            "candidate": {
                "name": "Ada",
                "resume_parsed": {"summary": "Built payment systems."},
            },
            "job_spec": {"title": "Backend Engineer", "level": "senior"},
        },
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_persist_interrupt_creates_or_updates_waiting_row() -> None:
    db = _FakeDb()
    persistence = SessionPersistence(get_db_session_fn=_session_factory(db))
    question = {"question": "Tell me about a system.", "dimension": "system_design"}

    persistence.persist_interrupt(_handle(), question, turn_idx=1)

    row = db.rows["sess-1"]
    assert isinstance(row, InterviewSession)
    assert row.trace_id == "trace-1"
    assert row.status == "interrupted"
    assert row.session_token_hash == "token-hash"
    assert row.llm_config_meta == {"provider": "stub"}
    assert row.current_question == question
    assert row.turn_idx == 1
    assert row.asked_turn == 0
    assert row.enable_video_analysis is True
    assert row.setup_snapshot == {
        "candidate": {
            "name": "Ada",
            "resume_parsed": {"summary": "Built payment systems."},
        },
        "job_spec": {"title": "Backend Engineer", "level": "senior"},
    }


def test_persist_completed_maps_error_state_and_clears_question() -> None:
    db = _FakeDb()
    db.rows["sess-1"] = InterviewSession(
        session_id="sess-1",
        trace_id="trace-1",
        current_question={"question": "old"},
    )
    persistence = SessionPersistence(get_db_session_fn=_session_factory(db))

    persistence.persist_completed(
        _handle(error="provider timed out", error_kind="timeout"),
        {
            "status": "errored",
            "error": "graph failed",
            "error_kind": "question_generation_failed",
            "retryable": True,
        },
    )

    row = db.rows["sess-1"]
    assert row.status == "errored"
    assert row.final_report is None
    assert row.error == "graph failed"
    assert row.error_kind == "question_generation_failed"
    assert row.retryable is True
    assert row.current_question is None
    assert row.setup_snapshot == {
        "candidate": {
            "name": "Ada",
            "resume_parsed": {"summary": "Built payment systems."},
        },
        "job_spec": {"title": "Backend Engineer", "level": "senior"},
    }


def test_load_session_for_retry_returns_minimal_metadata() -> None:
    db = _FakeDb()
    db.rows["sess-1"] = InterviewSession(
        session_id="sess-1",
        trace_id="trace-1",
        candidate_name="Alex",
        job_title="Backend Engineer",
        job_level="senior",
        mode="mixed",
        enable_video_analysis=True,
        session_token_hash="token-hash",
        llm_config_meta={"provider": "stub"},
        turn_idx=3,
        asked_turn=2,
    )
    persistence = SessionPersistence(get_db_session_fn=_session_factory(db))

    assert persistence.load_session_for_retry("sess-1") == {
        "trace_id": "trace-1",
        "candidate_name": "Alex",
        "job_title": "Backend Engineer",
        "job_level": "senior",
        "mode": "mixed",
        "enable_video_analysis": True,
        "session_token_hash": "token-hash",
        "session_token_expires_at": None,
        "llm_config_meta": {"provider": "stub"},
        "turn_idx": 3,
        "asked_turn": 2,
    }


def test_mark_retry_running_clears_terminal_fields() -> None:
    db = _FakeDb()
    db.rows["sess-1"] = InterviewSession(
        session_id="sess-1",
        trace_id="trace-1",
        status="error",
        current_question={"question": "old"},
        final_report={"score": 0},
        error="old error",
        error_kind="timeout",
        retryable=True,
    )
    persistence = SessionPersistence(get_db_session_fn=_session_factory(db))

    persistence.mark_retry_running("sess-1")

    row = db.rows["sess-1"]
    assert row.status == "running"
    assert row.current_question is None
    assert row.final_report is None
    assert row.error is None
    assert row.error_kind is None
    assert row.retryable is False
