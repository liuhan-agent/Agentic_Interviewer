"""TTL-based eviction for the raw answer side-channel.

Defends against the leak path identified in the 2026-05-04 audit:
when ``evaluator`` or ``verification`` raises and ``compress_context``
(the normal owner of ``clear_raw_answer_for_state``) does not get to
run, the raw text would otherwise stay in ``_RAW_ANSWER_STORE`` for
the lifetime of the process. With TTL the entry self-evicts within
``_RAW_ANSWER_TTL_SECONDS`` even on the unhappy path.
"""
from __future__ import annotations

import pytest

from app.engine.workflow.nodes import wait_answer


@pytest.fixture(autouse=True)
def _clear_store() -> None:
    wait_answer._RAW_ANSWER_STORE.clear()
    yield
    wait_answer._RAW_ANSWER_STORE.clear()


def test_get_returns_stored_answer_within_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(wait_answer, "_now_monotonic", lambda: 1000.0)
    ref = wait_answer._store_raw_answer("hello")
    state = {"current_answer_raw_ref": ref}

    monkeypatch.setattr(wait_answer, "_now_monotonic", lambda: 1100.0)
    assert wait_answer.get_raw_answer_for_state(state) == "hello"
    assert ref in wait_answer._RAW_ANSWER_STORE


def test_get_returns_empty_after_ttl_and_evicts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(wait_answer, "_now_monotonic", lambda: 2000.0)
    ref = wait_answer._store_raw_answer("secret")
    state = {"current_answer_raw_ref": ref}

    # Push the clock past the 300s TTL.
    monkeypatch.setattr(wait_answer, "_now_monotonic", lambda: 2400.0)
    assert wait_answer.get_raw_answer_for_state(state) == ""
    # Lazy eviction on read should have dropped the entry.
    assert ref not in wait_answer._RAW_ANSWER_STORE


def test_evict_expired_drops_only_stale_entries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(wait_answer, "_now_monotonic", lambda: 5000.0)
    fresh = wait_answer._store_raw_answer("fresh")

    # Manually plant an already-expired entry so we can verify selective eviction.
    wait_answer._RAW_ANSWER_STORE["stale-ref"] = ("stale", 4999.0)

    monkeypatch.setattr(wait_answer, "_now_monotonic", lambda: 5100.0)
    evicted = wait_answer._evict_expired()
    assert evicted == 1
    assert fresh in wait_answer._RAW_ANSWER_STORE
    assert "stale-ref" not in wait_answer._RAW_ANSWER_STORE


def test_clear_is_safe_after_ttl_eviction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(wait_answer, "_now_monotonic", lambda: 100.0)
    ref = wait_answer._store_raw_answer("x")
    state = {"current_answer_raw_ref": ref}

    monkeypatch.setattr(wait_answer, "_now_monotonic", lambda: 1000.0)
    wait_answer.get_raw_answer_for_state(state)  # triggers TTL evict
    assert ref not in wait_answer._RAW_ANSWER_STORE
    # ``clear_raw_answer_for_state`` should not crash even when the
    # ref is already gone — important for ``cancel`` finally blocks.
    # It still returns True because the state-level ref string was
    # present, signalling to callers that a clear-attempt happened.
    assert wait_answer.clear_raw_answer_for_state(state) is True


def test_legacy_raw_field_is_returned_when_ref_missing() -> None:
    state = {"current_answer_raw_ref": "", "current_answer_raw": "legacy"}
    assert wait_answer.get_raw_answer_for_state(state) == "legacy"


def test_ttl_reads_from_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Setting RAW_ANSWER_TTL_SECONDS env should affect new entries."""
    from app.core import settings as settings_mod

    monkeypatch.setenv("RAW_ANSWER_TTL_SECONDS", "30")
    settings_mod.get_settings.cache_clear()
    try:
        # Default returns 30 from env override.
        assert wait_answer._raw_answer_ttl_seconds() == 30.0

        # An entry stored with this TTL expires after 30s, not 300s.
        monkeypatch.setattr(wait_answer, "_now_monotonic", lambda: 0.0)
        ref = wait_answer._store_raw_answer("scoped")
        state = {"current_answer_raw_ref": ref}

        monkeypatch.setattr(wait_answer, "_now_monotonic", lambda: 25.0)
        assert wait_answer.get_raw_answer_for_state(state) == "scoped"

        monkeypatch.setattr(wait_answer, "_now_monotonic", lambda: 35.0)
        assert wait_answer.get_raw_answer_for_state(state) == ""
    finally:
        settings_mod.get_settings.cache_clear()


def test_ttl_falls_back_when_settings_broken(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def explode() -> None:
        raise RuntimeError("settings unreachable")

    monkeypatch.setattr(wait_answer, "get_settings", explode)
    # The fallback path keeps the historical 300s default so behaviour
    # is unchanged when settings throws (e.g. during tests that bypass
    # the cache).
    assert wait_answer._raw_answer_ttl_seconds() == 300.0
