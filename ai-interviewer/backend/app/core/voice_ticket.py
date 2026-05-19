"""Short-lived one-time tickets for voice WebSocket authentication."""
from __future__ import annotations

import secrets
import threading
import time
from typing import Any, Protocol

from app.core.settings import get_settings


class VoiceTicketStore(Protocol):
    def issue(self, session_id: str) -> str:
        """Create a one-time ticket for *session_id*."""

    def consume(self, ticket: str | None, session_id: str) -> bool:
        """Consume *ticket* once and return whether it belongs to *session_id*."""

    def clear(self) -> None:
        """Clear issued tickets. Intended for tests and operator reset paths."""


class MemoryVoiceTicketStore:
    """Process-local one-time ticket store used for dev and tests."""

    def __init__(self, *, ttl_seconds: int) -> None:
        self._ttl_seconds = ttl_seconds
        self._lock = threading.Lock()
        self._tickets: dict[str, tuple[str, float]] = {}

    def clear(self) -> None:
        with self._lock:
            self._tickets.clear()

    def issue(self, session_id: str, *, now: float | None = None) -> str:
        ticket = secrets.token_urlsafe(32)
        current = time.monotonic() if now is None else now
        expires_at = current + self._ttl_seconds
        with self._lock:
            self._tickets[ticket] = (session_id, expires_at)
        return ticket

    def consume(
        self,
        ticket: str | None,
        session_id: str,
        *,
        now: float | None = None,
    ) -> bool:
        if not ticket:
            return False
        current = time.monotonic() if now is None else now
        with self._lock:
            record = self._tickets.pop(ticket, None)
        if record is None:
            return False
        expected_session_id, expires_at = record
        return expected_session_id == session_id and expires_at >= current


_CONSUME_TICKET_LUA = """
local value = redis.call("GET", KEYS[1])
if not value then
  return 0
end
redis.call("DEL", KEYS[1])
if value == ARGV[1] then
  return 1
end
return 0
"""


class RedisVoiceTicketStore:
    """Redis-backed one-time voice ticket store shared across workers."""

    def __init__(
        self,
        *,
        redis_client: Any | None = None,
        redis_url: str | None = None,
        ttl_seconds: int,
        redis_prefix: str = "agentic_interviewer:voice_ticket",
    ) -> None:
        self._redis_client = redis_client
        self._redis_url = redis_url
        self._ttl_seconds = ttl_seconds
        self._redis_prefix = redis_prefix.rstrip(":")

    def _redis(self) -> Any:
        if self._redis_client is not None:
            return self._redis_client
        from redis import Redis

        url = self._redis_url or get_settings().redis_url
        self._redis_client = Redis.from_url(url, decode_responses=True)
        return self._redis_client

    def _key(self, ticket: str) -> str:
        return f"{self._redis_prefix}:{ticket}"

    def issue(self, session_id: str) -> str:
        redis_client = self._redis()
        for _ in range(3):
            ticket = secrets.token_urlsafe(32)
            if redis_client.set(
                self._key(ticket),
                session_id,
                ex=self._ttl_seconds,
                nx=True,
            ):
                return ticket
        raise RuntimeError("failed to issue unique voice ticket")

    def consume(self, ticket: str | None, session_id: str) -> bool:
        if not ticket:
            return False
        return bool(
            self._redis().eval(
                _CONSUME_TICKET_LUA,
                1,
                self._key(ticket),
                session_id,
            )
        )

    def clear(self) -> None:
        redis_client = self._redis()
        keys = list(redis_client.scan_iter(match=f"{self._redis_prefix}:*"))
        if keys:
            redis_client.delete(*keys)


_store: VoiceTicketStore | None = None
_store_lock = threading.Lock()


def _build_store() -> VoiceTicketStore:
    settings = get_settings()
    if settings.voice_ticket_backend == "redis":
        return RedisVoiceTicketStore(
            redis_url=settings.redis_url,
            ttl_seconds=settings.voice_ticket_ttl_seconds,
            redis_prefix=settings.voice_ticket_redis_prefix,
        )
    return MemoryVoiceTicketStore(ttl_seconds=settings.voice_ticket_ttl_seconds)


def get_voice_ticket_store() -> VoiceTicketStore:
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                _store = _build_store()
    return _store


def clear_voice_tickets() -> None:
    global _store
    with _store_lock:
        store = _store
        _store = None
    if store is not None:
        store.clear()


def issue_voice_ticket(session_id: str) -> str:
    return get_voice_ticket_store().issue(session_id)


def consume_voice_ticket(ticket: str | None, session_id: str) -> bool:
    return get_voice_ticket_store().consume(ticket, session_id)
