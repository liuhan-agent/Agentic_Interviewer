from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.services.session_manager import SessionHandle
from app.services.session_registry import SessionRegistry


def test_expired_session_ids_includes_completed_handles() -> None:
    now = datetime(2026, 5, 23, 12, 0, tzinfo=UTC)
    handle = SessionHandle(session_id="sess-done", trace_id="trace-done")
    handle.last_activity_at = now - timedelta(minutes=61)
    handle.done_event.set()
    registry = SessionRegistry({handle.session_id: handle})

    assert registry.expired_session_ids(now=now, ttl=timedelta(minutes=60)) == [
        "sess-done",
    ]


def test_expired_session_ids_keeps_recent_completed_and_running_handles() -> None:
    now = datetime(2026, 5, 23, 12, 0, tzinfo=UTC)
    completed = SessionHandle(session_id="sess-done", trace_id="trace-done")
    completed.last_activity_at = now - timedelta(minutes=30)
    completed.done_event.set()
    running = SessionHandle(session_id="sess-running", trace_id="trace-running")
    running.last_activity_at = now - timedelta(minutes=30)
    registry = SessionRegistry(
        {
            completed.session_id: completed,
            running.session_id: running,
        },
    )

    assert registry.expired_session_ids(now=now, ttl=timedelta(minutes=60)) == []
