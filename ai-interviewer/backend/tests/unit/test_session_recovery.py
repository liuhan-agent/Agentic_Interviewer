"""Regression tests for HITL session recovery and turn transitions."""
from __future__ import annotations

import threading
from types import SimpleNamespace
from typing import Any

import pytest

from app.services.session_manager import SessionHandle, SessionManager


def _bare_manager() -> SessionManager:
    manager = SessionManager.__new__(SessionManager)
    manager._sessions = {}
    manager._lock = threading.Lock()
    return manager


def _waiting_manager(values: dict[str, Any]) -> SessionManager:
    manager = _bare_manager()

    class _Workflow:
        def get_state(self, _config: dict[str, Any]) -> SimpleNamespace:
            return SimpleNamespace(values=values, next=("wait_answer",))

    manager._workflow = _Workflow()
    manager._load_persisted_session_for_retry = lambda _session_id: None
    manager._persist_interrupt = lambda *_args, **_kwargs: None
    return manager


def _live_handle(turn_idx: int = 2, asked_turn: int = 1) -> SessionHandle:
    handle = SessionHandle(session_id="sess-live", trace_id="trace-live")
    handle.current_question = {
        "question": "Explain one production incident you resolved.",
        "dimension": "ownership",
    }
    handle.turn_idx = turn_idx
    handle.asked_turn = asked_turn
    handle.question_event.set()
    return handle


def test_recovered_session_can_poll_current_question_and_submit_once() -> None:
    question = {"question": "Q?", "dimension": "system_design"}
    manager = _waiting_manager(
        {
            "session_id": "sess-recover",
            "trace_id": "trace-recover",
            "current_question": question,
            "turn_idx": 3,
            "max_turns": 8,
        }
    )
    started: list[object] = []
    manager._wait_until_idle = lambda _handle, **_kwargs: True
    manager._start_segment = lambda _handle, command: started.append(command) or True

    handle = manager.recover_waiting_session("sess-recover")

    assert handle is not None
    assert manager.wait_for_next_question("sess-recover", timeout=0.01) == question

    manager.submit_answer("sess-recover", "candidate answer", turn_idx=3)

    assert handle.asked_turn == 3
    assert handle.question_event.is_set() is False
    assert len(started) == 1
    with pytest.raises(ValueError, match="waiting"):
        manager.submit_answer("sess-recover", "duplicate answer", turn_idx=3)


def test_skip_then_old_answer_is_rejected() -> None:
    manager = _bare_manager()
    handle = _live_handle(turn_idx=4, asked_turn=3)
    manager._sessions[handle.session_id] = handle
    started: list[object] = []
    manager._wait_until_idle = lambda _handle, **_kwargs: True
    manager._start_segment = lambda _handle, command: started.append(command) or True

    manager.skip_question(handle.session_id, turn_idx=4, reason="candidate skipped")

    assert handle.asked_turn == 4
    assert handle.question_event.is_set() is False
    assert len(started) == 1
    with pytest.raises(ValueError, match="waiting"):
        manager.submit_answer(handle.session_id, "late answer", turn_idx=4)


def test_cancel_completed_session_preserves_terminal_state() -> None:
    manager = _bare_manager()
    handle = SessionHandle(
        session_id="sess-done",
        trace_id="trace-done",
        final_state={"final_report": {"verdict": "pass"}},
    )
    handle.done_event.set()
    manager._sessions[handle.session_id] = handle

    assert manager.cancel(handle.session_id) is True
    assert handle.cancelled is False
    assert handle.final_state == {"final_report": {"verdict": "pass"}}
    assert handle._cancel_event.is_set() is False
