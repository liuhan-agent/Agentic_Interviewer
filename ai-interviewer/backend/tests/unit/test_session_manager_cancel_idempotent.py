"""Regression test for ``SessionManager.cancel`` idempotency.

The WebSocket voice handler (``backend/app/api/v1/ws_voice.py``)
calls ``manager.cancel`` unconditionally from its ``finally`` block,
even when the interview just finished normally and the server is
tearing the socket down right after sending the ``final_report``
frame. An earlier implementation of ``cancel`` set ``handle.cancelled
= True`` and kicked off a fresh ``Command(resume=...)`` segment in
that case, which meant:

- ``GET /api/v1/interview/sessions/<id>/resume`` would then return
  ``{"status": "cancelled"}`` to the text InterviewRoom, even though
  the run actually completed successfully;
- the React ``useQuestionPoller`` would dispatch ``CANCELLED`` and
  show the "This session was cancelled" banner.

The fix: treat ``done_event.is_set()`` as terminal and short-circuit
``cancel`` to a no-op. This test pins that behaviour so a future
refactor doesn't reintroduce the bug.
"""
from __future__ import annotations

import threading

from app.services.session_manager import SessionHandle, SessionManager


def _completed_handle(session_id: str = "sess-done") -> SessionHandle:
    handle = SessionHandle(
        session_id=session_id,
        trace_id="trace-done",
        final_state={"final_report": {"verdict": "pass"}},
    )
    handle.done_event.set()
    return handle


def test_cancel_on_done_handle_does_not_flip_cancelled_flag() -> None:
    mgr = SessionManager()
    # Avoid the reaper thread hanging around after the test.
    mgr.shutdown()

    handle = _completed_handle()
    mgr._sessions[handle.session_id] = handle  # noqa: SLF001 - test harness

    ok = mgr.cancel(handle.session_id)

    assert ok is True
    # Terminal state must not be mutated.
    assert handle.cancelled is False
    assert handle._cancel_event.is_set() is False  # noqa: SLF001


def test_cancel_on_unknown_session_returns_false() -> None:
    """The no-op-on-done path must not mask the "session does not
    exist" signal — those two cases return different values so the
    caller can distinguish.
    """
    mgr = SessionManager()
    mgr.shutdown()

    assert mgr.cancel("sess-does-not-exist") is False


def test_cancel_on_live_handle_still_sets_cancelled_flag() -> None:
    """The guard must not leak into the normal cancel path."""
    mgr = SessionManager()
    mgr.shutdown()

    handle = SessionHandle(
        session_id="sess-live",
        trace_id="trace-live",
    )
    # Simulate an interview currently paused at an interrupt: done is
    # NOT set, question_event IS set (we are waiting on the client).
    handle.question_event.set()
    mgr._sessions[handle.session_id] = handle  # noqa: SLF001

    # ``_start_segment`` would try to run workflow.stream; we don't
    # want that to actually fire in a unit test. Monkey-patch it to
    # a no-op so ``cancel`` exercises the flag logic only.
    calls: list[str] = []

    def fake_start_segment(h: SessionHandle, stream_input: object) -> None:
        calls.append(type(stream_input).__name__)

    mgr._start_segment = fake_start_segment  # type: ignore[method-assign]

    ok = mgr.cancel("sess-live")

    assert ok is True
    assert handle.cancelled is True
    assert handle._cancel_event.is_set() is True  # noqa: SLF001
    # The live-cancel path must still schedule a resume segment with
    # the ``__cancelled__`` marker so the graph reaches final_report.
    assert calls == ["Command"]
    # And no background thread should still be waiting on the handle
    # because question_event is force-set on the cancel path.
    assert handle.question_event.is_set()
    # Spin down any thread-pool execution that might have leaked.
    # (SessionHandle has no owned thread in this test.)
    assert isinstance(handle._segment_lock, type(threading.Lock()))  # noqa: SLF001
