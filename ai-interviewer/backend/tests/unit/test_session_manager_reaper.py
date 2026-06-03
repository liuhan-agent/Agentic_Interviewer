from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.services import session_manager as session_manager_module
from app.services.session_manager import SessionHandle, SessionManager


def _manager_with_handles(*handles: SessionHandle) -> SessionManager:
    manager = SessionManager.__new__(SessionManager)
    manager._sessions = {handle.session_id: handle for handle in handles}
    manager._lock = threading.Lock()
    return manager


def _expired_handle(session_id: str, *, terminal: str | None = None) -> SessionHandle:
    now = datetime.now(UTC)
    handle = SessionHandle(session_id=session_id, trace_id=f"trace-{session_id}")
    handle.last_activity_at = now - timedelta(minutes=61)
    if terminal == "done":
        handle.done_event.set()
    elif terminal == "error":
        handle.error = "boom"
        handle.error_kind = "llm_error"
        handle.done_event.set()
    elif terminal == "cancelled":
        handle.cancelled = True
    return handle


@pytest.fixture
def ttl_60(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        session_manager_module,
        "get_settings",
        lambda: SimpleNamespace(session_idle_ttl_minutes=60),
    )


def test_reaper_directly_removes_expired_terminal_handles_without_cancel(
    ttl_60: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    completed = _expired_handle("sess-completed", terminal="done")
    errored = _expired_handle("sess-errored", terminal="error")
    cancelled = _expired_handle("sess-cancelled", terminal="cancelled")
    manager = _manager_with_handles(completed, errored, cancelled)

    def fail_cancel(session_id: str, *, join_timeout: float = 5.0) -> bool:
        raise AssertionError(f"terminal handle should not be cancelled: {session_id}")

    monkeypatch.setattr(manager, "cancel", fail_cancel)

    assert manager._reap_once() == 3
    assert manager._sessions == {}
    assert completed.cancelled is False
    assert errored.error == "boom"
    assert cancelled.cancelled is True


def test_reaper_cancels_then_removes_expired_live_handle(
    ttl_60: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    live = _expired_handle("sess-live")
    manager = _manager_with_handles(live)
    cancelled: list[str] = []

    def fake_cancel(session_id: str, *, join_timeout: float = 5.0) -> bool:
        cancelled.append(session_id)
        return True

    monkeypatch.setattr(manager, "cancel", fake_cancel)

    assert manager._reap_once() == 1
    assert cancelled == ["sess-live"]
    assert manager._sessions == {}


def test_reaper_evicts_expired_waiting_handle_without_cancelling(
    ttl_60: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    waiting = _expired_handle("sess-waiting")
    question = {"question": "Continue?", "dimension": "technical_depth"}
    waiting.current_question = question
    waiting.turn_idx = 2
    waiting.question_event.set()
    manager = _manager_with_handles(waiting)
    persisted: list[tuple[str, dict, int]] = []

    def fail_cancel(session_id: str, *, join_timeout: float = 5.0) -> bool:
        raise AssertionError(f"waiting handle should stay resumable: {session_id}")

    def persist_interrupt(
        handle: SessionHandle,
        current_question: dict,
        turn_idx: int,
    ) -> None:
        persisted.append((handle.session_id, current_question, turn_idx))

    monkeypatch.setattr(manager, "cancel", fail_cancel)
    monkeypatch.setattr(manager, "_persist_interrupt", persist_interrupt)

    assert manager._reap_once() == 1
    assert manager._sessions == {}
    assert waiting.cancelled is False
    assert persisted == [("sess-waiting", question, 2)]


def test_reaper_keeps_recent_completed_and_running_handles(
    ttl_60: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(UTC)
    completed = SessionHandle(session_id="sess-completed", trace_id="trace-completed")
    completed.done_event.set()
    completed.last_activity_at = now - timedelta(minutes=30)
    running = SessionHandle(session_id="sess-running", trace_id="trace-running")
    running.last_activity_at = now - timedelta(minutes=30)
    manager = _manager_with_handles(completed, running)

    def fail_cancel(session_id: str, *, join_timeout: float = 5.0) -> bool:
        raise AssertionError(f"recent handle should not be cancelled: {session_id}")

    monkeypatch.setattr(manager, "cancel", fail_cancel)

    assert manager._reap_once() == 0
    assert set(manager._sessions) == {"sess-completed", "sess-running"}


def test_snapshot_does_not_refresh_last_activity_at() -> None:
    now = datetime.now(UTC)
    handle = SessionHandle(session_id="sess-snapshot", trace_id="trace-snapshot")
    handle.last_activity_at = now - timedelta(minutes=30)
    manager = _manager_with_handles(handle)

    before = handle.last_activity_at
    snapshot = manager.snapshot()

    assert snapshot[0]["session_id"] == "sess-snapshot"
    assert handle.last_activity_at == before
