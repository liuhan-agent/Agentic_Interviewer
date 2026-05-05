"""Unit tests for :class:`app.engine.context.ContextFrame`.

Covers the three contracts the rest of the stack relies on:

1. ``system_text`` concatenates static + dynamic layers with a double
   newline when both are set, and collapses to the static layer alone
   when the dynamic tail is empty. This is the exact join the legacy
   generator used, so any drift here breaks byte-equivalence.
2. ``payload`` stays free-form so renderers can feed arbitrary keys
   into their prompt templates without needing a frame schema bump.
3. ``cache_key`` is stable across runs and role-sensitive - the
   Phase 0 value is consumed by tests only, but PR-2 will bind it to
   Anthropic prompt-cache keys so we lock the stability guarantee
   here.
"""
from __future__ import annotations

from app.engine.context import ContextFrame


def test_system_text_joins_static_and_dynamic() -> None:
    frame = ContextFrame(
        agent_role="generator",
        turn_idx=0,
        static_system="STATIC",
        dynamic_system="DYNAMIC",
    )
    assert frame.system_text == "STATIC\n\nDYNAMIC"


def test_system_text_collapses_when_dynamic_empty() -> None:
    frame = ContextFrame(
        agent_role="generator",
        turn_idx=0,
        static_system="STATIC",
        dynamic_system="",
    )
    assert frame.system_text == "STATIC"


def test_payload_is_freeform_dict() -> None:
    frame = ContextFrame(
        agent_role="generator",
        turn_idx=3,
        payload={"dimension": "system_design", "target_difficulty": "hard"},
    )
    assert frame.payload["dimension"] == "system_design"
    assert frame.payload["target_difficulty"] == "hard"


def test_cache_key_is_stable_and_role_sensitive() -> None:
    a = ContextFrame(
        agent_role="generator",
        turn_idx=0,
        static_system="sys",
        dynamic_system="dyn",
    )
    b = ContextFrame(
        agent_role="generator",
        turn_idx=99,  # turn_idx must NOT affect the cache key
        static_system="sys",
        dynamic_system="dyn",
    )
    c = ContextFrame(
        agent_role="evaluator",  # different role => different key
        turn_idx=0,
        static_system="sys",
        dynamic_system="dyn",
    )
    assert a.cache_key() == b.cache_key()
    assert a.cache_key() != c.cache_key()
    assert len(a.cache_key()) == 12
