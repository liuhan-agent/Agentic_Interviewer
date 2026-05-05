from __future__ import annotations

import threading
from types import SimpleNamespace
from typing import Any

from app.services.session_manager import SessionHandle, SessionManager


def _manager_with_workflow(values: dict[str, Any], next_nodes: tuple[str, ...]):
    manager = SessionManager.__new__(SessionManager)
    manager._sessions = {}
    manager._lock = threading.Lock()

    class _Workflow:
        def get_state(self, _config: dict[str, Any]) -> SimpleNamespace:
            return SimpleNamespace(values=values, next=next_nodes)

    manager._workflow = _Workflow()
    return manager


def test_recover_waiting_session_rebuilds_handle_invariants() -> None:
    question = {"question": "Q?", "dimension": "system_design"}
    values = {
        "session_id": "sess-recover",
        "trace_id": "trace-recover",
        "candidate": {"name": "Alex"},
        "job_spec": {"title": "Backend Engineer", "level": "senior"},
        "current_question": question,
        "turn_idx": 2,
        "max_turns": 8,
        "mode": "mixed",
    }
    manager = _manager_with_workflow(values, ("wait_answer",))
    persisted: list[tuple[SessionHandle, dict[str, Any], int]] = []

    manager._load_persisted_session_for_retry = lambda _session_id: None  # type: ignore[method-assign]
    manager._persist_interrupt = lambda handle, q, turn: persisted.append(  # type: ignore[method-assign]
        (handle, q, turn)
    )

    handle = manager.recover_waiting_session("sess-recover")

    assert handle is not None
    assert handle.current_question == question
    assert handle.turn_idx == 2
    assert handle.asked_turn == 1
    assert handle.max_turns == 8
    assert handle.question_event.is_set()
    assert handle.done_event.is_set() is False
    assert handle.candidate_name == "Alex"
    assert handle.job_title == "Backend Engineer"
    assert handle.job_level == "senior"
    assert handle.mode == "mixed"
    assert manager._sessions["sess-recover"] is handle
    assert persisted == [(handle, question, 2)]


def test_recover_waiting_session_returns_none_when_checkpoint_not_waiting() -> None:
    manager = _manager_with_workflow(
        {
            "current_question": {"question": "Q?"},
            "turn_idx": 2,
        },
        ("evaluator",),
    )
    manager._load_persisted_session_for_retry = lambda _session_id: None  # type: ignore[method-assign]

    assert manager.recover_waiting_session("sess-not-waiting") is None
    assert manager._sessions == {}


def test_recover_waiting_session_returns_none_without_checkpoint_question() -> None:
    manager = _manager_with_workflow(
        {
            "current_question": {},
            "turn_idx": 2,
        },
        ("wait_answer",),
    )
    manager._load_persisted_session_for_retry = lambda _session_id: None  # type: ignore[method-assign]

    assert manager.recover_waiting_session("sess-no-question") is None
    assert manager._sessions == {}
