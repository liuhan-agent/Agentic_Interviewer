"""SessionManager cancellation / raw-answer cleanup hardening.

Locks in the audit follow-up items:
- raw answer side-channel is cleared even when a graph segment errors
  before ``compress_context`` can run;
- cancel reports failure when the cancel-resume segment cannot be
  started, instead of pretending the graceful graph cancel succeeded.
"""
from __future__ import annotations

import threading
from typing import Any

import pytest

from app.engine.workflow.nodes import wait_answer
from app.services.session_manager import SessionHandle, SessionManager


@pytest.fixture(autouse=True)
def _clear_raw_answer_store() -> None:
    wait_answer._RAW_ANSWER_STORE.clear()
    yield
    wait_answer._RAW_ANSWER_STORE.clear()


def _manager_with_handle(handle: SessionHandle) -> SessionManager:
    manager = SessionManager.__new__(SessionManager)
    manager._sessions = {handle.session_id: handle}
    manager._lock = threading.Lock()
    return manager


def test_run_segment_clears_raw_answer_ref_when_graph_errors() -> None:
    ref = wait_answer._store_raw_answer("unredacted answer")

    class ExplodingWorkflow:
        def stream(self, stream_input: Any, *, config: dict, stream_mode: str):
            yield {
                "session_id": "s-raw-cleanup",
                "current_answer_raw_ref": ref,
                "status": "running",
            }
            raise RuntimeError("evaluator exploded")

    handle = SessionHandle(session_id="s-raw-cleanup", trace_id="trace-raw-cleanup")
    manager = _manager_with_handle(handle)
    manager._workflow = ExplodingWorkflow()
    manager._persist_completed = lambda _handle, _final_state: None

    manager._run_segment(handle, {"resume": "value"})

    assert ref not in wait_answer._RAW_ANSWER_STORE
    assert handle.done_event.is_set()
    assert handle.error


def test_cancel_returns_false_when_resume_segment_cannot_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handle = SessionHandle(session_id="s-cancel-fail", trace_id="trace-cancel-fail")
    manager = _manager_with_handle(handle)

    def fail_start_segment(_handle: SessionHandle, _stream_input: Any) -> bool:
        raise RuntimeError("thread pool unavailable")

    monkeypatch.setattr(manager, "_start_segment", fail_start_segment)

    assert manager.cancel("s-cancel-fail", join_timeout=0) is False
    assert handle.cancelled is True
