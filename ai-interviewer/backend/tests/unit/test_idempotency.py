"""Unit tests for app/core/idempotency.

The store backs ``POST /api/v1/interview/sessions/{id}/answer``; the
guarantees we care about are:
- A second identical request with the same key returns the cached
  first-call response verbatim (replay safety).
- A second request with the same key but a different body raises
  ``IdempotencyConflict`` (replay-with-mutation guard).
- TTL expires entries so a long-lived process cannot accumulate state.
- Key validation rejects shapes that would let the cache absorb noise
  (single-character keys, oversized keys, non-printable garbage).
"""
from __future__ import annotations

import time
from typing import Any

import pytest

from app.core.idempotency import (
    IDEMPOTENCY_KEY_MAX_LENGTH,
    IDEMPOTENCY_KEY_MIN_LENGTH,
    IdempotencyConflict,
    IdempotencyStore,
    hash_request_body,
    is_valid_idempotency_key,
)


def test_hash_request_body_is_dict_order_independent() -> None:
    a = hash_request_body({"answer": "x", "turn_idx": 1})
    b = hash_request_body({"turn_idx": 1, "answer": "x"})
    assert a == b


def test_hash_request_body_changes_with_payload() -> None:
    a = hash_request_body({"answer": "x", "turn_idx": 1})
    b = hash_request_body({"answer": "x", "turn_idx": 2})
    assert a != b


def test_hash_request_body_handles_nested_structures() -> None:
    a = hash_request_body(
        {"video_signals": {"engagement": 0.5, "confidence": 0.8}, "answer": "y"}
    )
    b = hash_request_body(
        {"answer": "y", "video_signals": {"confidence": 0.8, "engagement": 0.5}}
    )
    assert a == b


def test_is_valid_idempotency_key_accepts_uuid_like() -> None:
    assert is_valid_idempotency_key("550e8400-e29b-41d4-a716-446655440000")


def test_is_valid_idempotency_key_rejects_too_short() -> None:
    assert not is_valid_idempotency_key("a" * (IDEMPOTENCY_KEY_MIN_LENGTH - 1))


def test_is_valid_idempotency_key_rejects_too_long() -> None:
    assert not is_valid_idempotency_key("a" * (IDEMPOTENCY_KEY_MAX_LENGTH + 1))


def test_is_valid_idempotency_key_rejects_disallowed_chars() -> None:
    assert not is_valid_idempotency_key("abc def 123!")


def test_is_valid_idempotency_key_rejects_none_and_blank() -> None:
    assert not is_valid_idempotency_key(None)
    assert not is_valid_idempotency_key("")


def test_store_lookup_returns_none_when_unknown() -> None:
    store = IdempotencyStore()
    assert store.lookup("scope-a", "k" * 12, "hash-x") is None


def test_store_returns_cached_response_for_replay() -> None:
    store = IdempotencyStore()
    payload: dict[str, Any] = {"session_id": "sess-1", "accepted": True}
    store.record("scope-a", "k" * 12, "hash-x", payload)

    hit = store.lookup("scope-a", "k" * 12, "hash-x")

    assert hit is not None
    assert hit.response == payload


def test_store_raises_conflict_when_same_key_with_different_hash() -> None:
    store = IdempotencyStore()
    store.record("scope-a", "k" * 12, "hash-x", {"accepted": True})

    with pytest.raises(IdempotencyConflict):
        store.lookup("scope-a", "k" * 12, "hash-y")


def test_store_isolates_scopes() -> None:
    store = IdempotencyStore()
    store.record("scope-a", "k" * 12, "hash-x", {"a": 1})

    assert store.lookup("scope-b", "k" * 12, "hash-x") is None


def test_store_ttl_expires_entries() -> None:
    store = IdempotencyStore(ttl_seconds=0.01)
    store.record("scope-a", "k" * 12, "hash-x", {"accepted": True})
    time.sleep(0.05)

    assert store.lookup("scope-a", "k" * 12, "hash-x") is None


def test_store_evicts_oldest_when_cap_exceeded() -> None:
    store = IdempotencyStore(max_keys=2)
    store.record("scope", "key-aaaaaaaa", "h1", {"id": 1})
    time.sleep(0.001)
    store.record("scope", "key-bbbbbbbb", "h2", {"id": 2})
    time.sleep(0.001)
    store.record("scope", "key-cccccccc", "h3", {"id": 3})

    # Oldest "key-aaaaaaaa" should be gone
    assert store.lookup("scope", "key-aaaaaaaa", "h1") is None
    # The newer two stay
    assert store.lookup("scope", "key-bbbbbbbb", "h2") is not None
    assert store.lookup("scope", "key-cccccccc", "h3") is not None


def test_store_clear_drops_all_entries() -> None:
    store = IdempotencyStore()
    store.record("scope", "k" * 12, "h", {"x": 1})
    store.clear()

    assert store.lookup("scope", "k" * 12, "h") is None


def test_record_returns_immutable_copy_of_response() -> None:
    """Subsequent mutation of the original dict must not affect the cached
    payload. Otherwise a downstream caller could accidentally rewrite the
    cached entry by mutating their local response dict."""
    store = IdempotencyStore()
    payload: dict[str, Any] = {"accepted": True, "session_id": "sess-1"}
    store.record("scope", "k" * 12, "h", payload)

    payload["accepted"] = False

    cached = store.lookup("scope", "k" * 12, "h")
    assert cached is not None
    assert cached.response == {"accepted": True, "session_id": "sess-1"}
