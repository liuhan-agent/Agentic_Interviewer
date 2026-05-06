"""HTTP idempotency-key helper for write endpoints.

The interview answer endpoint is the canonical use case: the LangGraph
turn already enforces ``turn_idx`` match, but the wire-level retry
window is wider than the in-memory turn state, e.g.

  1. Browser submits ``POST /answer`` and the response is lost mid-flight
     (network blip, mobile tab switch).
  2. The browser retries the same submission. The graph has already
     advanced to the next ``turn_idx``, so the retry would now hit a 409
     even though the *original* submission succeeded.

Idempotency-Key fixes this end-to-end retry story by tagging each logical
request with a client-generated UUID. The first time the server sees the
key, it executes the operation and caches the response. Subsequent
requests with the same key + identical body get the cached response back
verbatim; same key + different body gets ``409 idempotency_conflict``.

This module is intentionally small:
- in-memory only (the project already runs without Redis where possible);
- TTL-bounded so a long-running process cannot accumulate state forever;
- thread-safe, since multiple uvicorn worker threads may hit it.

Wire it into a route handler with :func:`get_idempotency_store` and the
two ``IdempotencyStore`` methods (``lookup`` / ``record``). See
``ai-interviewer/backend/app/api/v1/interview.py`` for the canonical
example.
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
from dataclasses import dataclass
from typing import Any


IDEMPOTENCY_KEY_MAX_LENGTH = 128
IDEMPOTENCY_KEY_MIN_LENGTH = 8
DEFAULT_IDEMPOTENCY_TTL_SECONDS = 300
_MAX_TRACKED_KEYS = 4096


class IdempotencyConflict(Exception):
    """Raised when a key is reused with a *different* request body.

    Mapped to HTTP 409 by callers; carries the original key in
    ``args[0]`` so logs can distinguish replay-with-mutation from
    plain conflicts.
    """


@dataclass(frozen=True)
class IdempotencyHit:
    """Cached first-call response served to a duplicate request."""

    response: dict[str, Any]
    request_hash: str
    recorded_at: float


def hash_request_body(payload: Any) -> str:
    """Stable SHA-256 of a JSON-serialisable payload.

    The body is serialised with ``sort_keys=True`` so dict ordering does
    not produce a false conflict. Non-serialisable values raise
    ``TypeError`` — callers should pre-normalise to the same primitives
    they pass to the underlying service.
    """
    serialised = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(serialised.encode("utf-8")).hexdigest()


def is_valid_idempotency_key(key: str | None) -> bool:
    """Cheap shape check for client-supplied keys.

    The header is *opaque* on the wire, but we still cap length so a
    malicious client cannot pin huge strings into the in-memory store,
    and require a minimum length so a stray ``Idempotency-Key: x`` does
    not silently activate the cache layer.
    """
    if not isinstance(key, str):
        return False
    if not (IDEMPOTENCY_KEY_MIN_LENGTH <= len(key) <= IDEMPOTENCY_KEY_MAX_LENGTH):
        return False
    return all(ch.isascii() and (ch.isalnum() or ch in "-_.~") for ch in key)


class IdempotencyStore:
    """Thread-safe TTL cache keyed by ``(scope, idempotency_key)``."""

    def __init__(
        self,
        *,
        ttl_seconds: float = DEFAULT_IDEMPOTENCY_TTL_SECONDS,
        max_keys: int = _MAX_TRACKED_KEYS,
    ) -> None:
        self._ttl = float(ttl_seconds)
        self._max_keys = int(max_keys)
        self._lock = threading.Lock()
        self._entries: dict[tuple[str, str], IdempotencyHit] = {}

    def _now(self) -> float:
        return time.monotonic()

    def _is_expired(self, hit: IdempotencyHit, *, now: float) -> bool:
        return now - hit.recorded_at > self._ttl

    def _prune_expired(self, *, now: float) -> None:
        # Cheap O(n) sweep; n is bounded by ``_max_keys`` so this stays
        # well under a millisecond on the hot path.
        expired = [
            key for key, hit in self._entries.items() if self._is_expired(hit, now=now)
        ]
        for key in expired:
            self._entries.pop(key, None)

    def lookup(
        self,
        scope: str,
        key: str,
        request_hash: str,
    ) -> IdempotencyHit | None:
        """Return a cached response when ``(scope, key)`` is a known hit.

        Raises :class:`IdempotencyConflict` when the same key was already
        used with a *different* body (replay-with-mutation).
        """
        with self._lock:
            now = self._now()
            hit = self._entries.get((scope, key))
            if hit is None:
                return None
            if self._is_expired(hit, now=now):
                self._entries.pop((scope, key), None)
                return None
            if hit.request_hash != request_hash:
                raise IdempotencyConflict(key)
            return hit

    def record(
        self,
        scope: str,
        key: str,
        request_hash: str,
        response: dict[str, Any],
    ) -> IdempotencyHit:
        """Cache the response after the operation succeeds."""
        with self._lock:
            now = self._now()
            self._prune_expired(now=now)
            if len(self._entries) >= self._max_keys:
                # Evict the oldest entry; the bound is a safety net, not
                # a precise LRU.
                oldest_key = min(
                    self._entries,
                    key=lambda k: self._entries[k].recorded_at,
                )
                self._entries.pop(oldest_key, None)
            hit = IdempotencyHit(
                response=dict(response),
                request_hash=request_hash,
                recorded_at=now,
            )
            self._entries[(scope, key)] = hit
            return hit

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


_default_store: IdempotencyStore | None = None
_default_store_lock = threading.Lock()


def get_idempotency_store() -> IdempotencyStore:
    """Process-local singleton store. Tests can ``reset_idempotency_store``
    to keep state isolated across cases."""
    global _default_store
    if _default_store is None:
        with _default_store_lock:
            if _default_store is None:
                _default_store = IdempotencyStore()
    return _default_store


def reset_idempotency_store() -> None:
    """Drop the singleton (test-only seam)."""
    global _default_store
    with _default_store_lock:
        _default_store = None
