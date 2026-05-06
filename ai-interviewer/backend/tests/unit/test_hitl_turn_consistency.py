"""HITL turn consistency and state invariant tests.

P0 Launch Hardening: verify that turn_idx, asked_turn,
current_question, and done_event stay consistent across the
start -> poll -> answer -> next-poll lifecycle, recovery from
checkpoint, cancel, and duplicate submission scenarios.

These are service-level tests that exercise SessionManager and
SessionHandle without spinning up a real workflow graph.
"""
from __future__ import annotations

import threading
from typing import Any

import pytest

from app.services.session_manager import SessionHandle, SessionManager


def _bare_manager() -> SessionManager:
    """Create a SessionManager without the reaper thread."""
    mgr = SessionManager.__new__(SessionManager)
    mgr._sessions = {}
    mgr._lock = threading.Lock()
    return mgr


def _live_handle(
    session_id: str = "sess-1",
    turn_idx: int = 1,
    asked_turn: int = 0,
    question: dict[str, Any] | None = None,
) -> SessionHandle:
    """Create a handle simulating a live interview paused at an interrupt."""
    handle = SessionHandle(
        session_id=session_id,
        trace_id=f"trace-{session_id}",
    )
    handle.current_question = question or {"question": "What is X?", "dimension": "technical"}
    handle.turn_idx = turn_idx
    handle.asked_turn = asked_turn
    handle.question_event.set()
    return handle


# -------------------------------------------------------------------
# Turn invariant assertions
# -------------------------------------------------------------------

class TestTurnInvariants:
    """Verify invariants that must hold at interrupt boundaries."""

    def test_fresh_handle_has_consistent_defaults(self):
        h = SessionHandle(session_id="s", trace_id="t")
        assert h.turn_idx == 0
        assert h.asked_turn == -1
        assert h.current_question is None
        assert h.question_event.is_set() is False
        assert h.done_event.is_set() is False
        assert h.cancelled is False
        assert h.error is None

    def test_interrupt_state_question_present_when_event_set(self):
        h = _live_handle(turn_idx=3, asked_turn=2)
        assert h.question_event.is_set()
        assert h.current_question is not None
        assert h.turn_idx > h.asked_turn

    def test_done_and_question_events_mutually_exclusive_on_terminal(self):
        h = SessionHandle(session_id="s", trace_id="t")
        h.done_event.set()
        h.final_state = {"final_report": {"verdict": "pass"}}
        assert h.done_event.is_set()
        assert h.question_event.is_set() is False


# -------------------------------------------------------------------
# Duplicate submit protection
# -------------------------------------------------------------------

class TestDuplicateSubmit:
    """submit_answer with the same turn_idx twice must not double-advance."""

    def test_second_submit_same_turn_raises(self):
        mgr = _bare_manager()
        handle = _live_handle(turn_idx=2, asked_turn=1)
        mgr._sessions[handle.session_id] = handle

        started: list[object] = []
        mgr._wait_until_idle = lambda _h, **kw: True
        mgr._start_segment = lambda _h, cmd: started.append(cmd)

        mgr.submit_answer(handle.session_id, "first answer", turn_idx=2)

        assert handle.question_event.is_set() is False
        assert handle.asked_turn == 2

        with pytest.raises(ValueError, match="waiting"):
            mgr.submit_answer(handle.session_id, "duplicate", turn_idx=2)

    def test_stale_turn_idx_rejected(self):
        mgr = _bare_manager()
        handle = _live_handle(turn_idx=3, asked_turn=2)
        mgr._sessions[handle.session_id] = handle

        with pytest.raises(ValueError, match="turn_idx"):
            mgr.submit_answer(handle.session_id, "stale", turn_idx=2)

        assert handle.question_event.is_set()
        assert handle.asked_turn == 2


# -------------------------------------------------------------------
# Cancel on completed session
# -------------------------------------------------------------------

class TestCancelAfterComplete:
    """cancel() on a done session must not flip cancelled or re-score."""

    def test_cancel_after_done_preserves_state(self):
        mgr = SessionManager()
        mgr.shutdown()

        handle = SessionHandle(
            session_id="sess-done",
            trace_id="trace-done",
            final_state={"final_report": {"verdict": "pass"}},
        )
        handle.done_event.set()
        mgr._sessions[handle.session_id] = handle

        ok = mgr.cancel(handle.session_id)

        assert ok is True
        assert handle.cancelled is False
        assert handle.final_state["final_report"]["verdict"] == "pass"
        assert handle._cancel_event.is_set() is False

    def test_cancel_during_active_sets_cancelled(self):
        mgr = _bare_manager()
        handle = _live_handle()
        mgr._sessions[handle.session_id] = handle

        calls: list[str] = []
        mgr._start_segment = lambda _h, cmd: calls.append("started")
        mgr.cancel(handle.session_id)

        assert handle.cancelled is True
        assert handle._cancel_event.is_set()


# -------------------------------------------------------------------
# Recovery invariants
# -------------------------------------------------------------------

class TestRecoveryTurnConsistency:
    """Recovered handles must have the same invariants as live ones."""

    def test_recovered_handle_turn_fields_consistent(self):
        from types import SimpleNamespace

        mgr = _bare_manager()
        values = {
            "session_id": "sess-rec",
            "trace_id": "trace-rec",
            "candidate": {"name": "Test"},
            "job_spec": {"title": "Engineer", "level": "mid"},
            "current_question": {"question": "Q?", "dimension": "algo"},
            "turn_idx": 3,
            "max_turns": 8,
            "mode": "mixed",
        }

        class _Workflow:
            def get_state(self, _config):
                return SimpleNamespace(values=values, next=("wait_answer",))

        mgr._workflow = _Workflow()
        mgr._load_persisted_session_for_retry = lambda _sid: None
        persisted = []
        mgr._persist_interrupt = lambda h, q, t: persisted.append(t)

        handle = mgr.recover_waiting_session("sess-rec")

        assert handle is not None
        assert handle.turn_idx == 3
        assert handle.asked_turn == 2
        assert handle.current_question == {"question": "Q?", "dimension": "algo"}
        assert handle.question_event.is_set()
        assert handle.done_event.is_set() is False
        assert handle.cancelled is False

    def test_recovery_of_non_waiting_checkpoint_returns_none(self):
        from types import SimpleNamespace

        mgr = _bare_manager()

        class _Workflow:
            def get_state(self, _config):
                return SimpleNamespace(
                    values={"current_question": {"question": "Q?"}, "turn_idx": 2},
                    next=("evaluator",),
                )

        mgr._workflow = _Workflow()
        mgr._load_persisted_session_for_retry = lambda _sid: None

        assert mgr.recover_waiting_session("sess-not-waiting") is None
        assert "sess-not-waiting" not in mgr._sessions


# -------------------------------------------------------------------
# Checkpoint missing / stale detection
# -------------------------------------------------------------------

class TestCheckpointStaleDetection:
    """When checkpoint data is missing or incomplete, session should
    be identifiable as stale rather than silently corrupted."""

    def test_checkpoint_exists_treats_empty_state_as_missing(self):
        from types import SimpleNamespace

        mgr = _bare_manager()

        class _Workflow:
            def get_state(self, _config):
                return SimpleNamespace(values={}, next=())

        mgr._workflow = _Workflow()

        assert mgr._checkpoint_exists("sess-missing") is False

    def test_recovery_with_empty_question_returns_none(self):
        from types import SimpleNamespace

        mgr = _bare_manager()

        class _Workflow:
            def get_state(self, _config):
                return SimpleNamespace(
                    values={"current_question": {}, "turn_idx": 2},
                    next=("wait_answer",),
                )

        mgr._workflow = _Workflow()
        mgr._load_persisted_session_for_retry = lambda _sid: None

        assert mgr.recover_waiting_session("sess-empty-q") is None

    def test_recovery_with_none_question_returns_none(self):
        from types import SimpleNamespace

        mgr = _bare_manager()

        class _Workflow:
            def get_state(self, _config):
                return SimpleNamespace(
                    values={"current_question": None, "turn_idx": 2},
                    next=("wait_answer",),
                )

        mgr._workflow = _Workflow()
        mgr._load_persisted_session_for_retry = lambda _sid: None

        assert mgr.recover_waiting_session("sess-none-q") is None


# -------------------------------------------------------------------
# Submit on unknown / cancelled sessions
# -------------------------------------------------------------------

class TestSubmitEdgeCases:
    def test_submit_on_unknown_session_raises(self):
        mgr = _bare_manager()
        with pytest.raises(KeyError):
            mgr.submit_answer("nonexistent", "answer", turn_idx=1)

    def test_submit_on_done_session_not_waiting(self):
        """After done_event is set the handle is no longer waiting;
        submit_answer must reject because question_event is not set."""
        mgr = _bare_manager()
        handle = _live_handle()
        handle.done_event.set()
        handle.question_event.clear()
        mgr._sessions[handle.session_id] = handle

        with pytest.raises(ValueError, match="waiting"):
            mgr.submit_answer(handle.session_id, "too late", turn_idx=1)
