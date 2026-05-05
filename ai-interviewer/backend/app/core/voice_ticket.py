"""Short-lived one-time tickets for voice WebSocket authentication."""
from __future__ import annotations

import secrets
import threading
import time

from app.core.settings import get_settings

_lock = threading.Lock()
_tickets: dict[str, tuple[str, float]] = {}


def clear_voice_tickets() -> None:
    with _lock:
        _tickets.clear()


def issue_voice_ticket(session_id: str) -> str:
    ticket = secrets.token_urlsafe(32)
    expires_at = time.monotonic() + get_settings().voice_ticket_ttl_seconds
    with _lock:
        _tickets[ticket] = (session_id, expires_at)
    return ticket


def consume_voice_ticket(ticket: str | None, session_id: str) -> bool:
    if not ticket:
        return False
    now = time.monotonic()
    with _lock:
        record = _tickets.pop(ticket, None)
    if record is None:
        return False
    expected_session_id, expires_at = record
    return expected_session_id == session_id and expires_at >= now
