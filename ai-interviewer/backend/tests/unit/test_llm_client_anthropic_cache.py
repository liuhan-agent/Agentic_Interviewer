"""Unit tests for :func:`_anthropic_system_arg`.

The helper bakes two policies into one pure function:

1. *Legacy mode* - no ChatMessage carries ``cache_control``. Behaviour
   is bit-identical to the pre-PR-2b ``_call_anthropic`` branch: one
   joined text block with or without ``cache_control`` depending on
   the global ``anthropic_prompt_cache`` flag, or a plain-string
   ``system`` when the flag is off.
2. *Per-message mode* - at least one ChatMessage carries a
   ``cache_control`` hint. Every system message becomes its own text
   block; only the ones flagged ``"ephemeral"`` receive
   ``cache_control`` in the outgoing payload (and only if the global
   flag is on).

Keeping this pure helper separate from the Anthropic SDK call means
we can exercise the full routing without mocking the client.
"""
from __future__ import annotations

from app.engine.agents.llm_client import ChatMessage, _anthropic_system_arg


def test_no_system_messages_returns_none() -> None:
    assert _anthropic_system_arg([], prompt_cache_enabled=True) is None
    assert _anthropic_system_arg([], prompt_cache_enabled=False) is None


def test_legacy_single_system_cache_on_wraps_in_cached_block() -> None:
    """One plain system message, global cache flag ON -> one text
    block with ``cache_control: ephemeral`` (pre-PR-2b behaviour)."""
    msgs = [ChatMessage("system", "HELLO")]
    out = _anthropic_system_arg(msgs, prompt_cache_enabled=True)
    assert out == [
        {
            "type": "text",
            "text": "HELLO",
            "cache_control": {"type": "ephemeral"},
        }
    ]


def test_legacy_single_system_cache_off_returns_string() -> None:
    """Flag OFF + no per-message hint -> plain string ``system``
    (shortest path; matches the old SDK call style)."""
    msgs = [ChatMessage("system", "HELLO")]
    out = _anthropic_system_arg(msgs, prompt_cache_enabled=False)
    assert out == "HELLO"


def test_legacy_multi_system_joined_with_newline() -> None:
    """Multiple systems, all plain -> joined with ``\\n`` in one
    block. Matches the pre-PR-2b ``"\\n".join(system_parts)`` semantic
    exactly (single newline, NOT double)."""
    msgs = [
        ChatMessage("system", "A"),
        ChatMessage("system", "B"),
    ]
    out = _anthropic_system_arg(msgs, prompt_cache_enabled=True)
    assert out == [
        {
            "type": "text",
            "text": "A\nB",
            "cache_control": {"type": "ephemeral"},
        }
    ]


def test_per_message_hint_yields_split_blocks_with_selective_cache() -> None:
    """Static system marked ephemeral, dynamic plain -> two blocks,
    only the first cached."""
    msgs = [
        ChatMessage("system", "STATIC", cache_control="ephemeral"),
        ChatMessage("system", "DYNAMIC"),  # no hint
    ]
    out = _anthropic_system_arg(msgs, prompt_cache_enabled=True)
    assert out == [
        {
            "type": "text",
            "text": "STATIC",
            "cache_control": {"type": "ephemeral"},
        },
        {"type": "text", "text": "DYNAMIC"},
    ]


def test_per_message_hint_respects_global_off_switch() -> None:
    """Global flag OFF must strip all cache markers even when
    messages asked for them. Operators rely on this to kill-switch
    caching for debugging."""
    msgs = [
        ChatMessage("system", "STATIC", cache_control="ephemeral"),
        ChatMessage("system", "DYNAMIC"),
    ]
    out = _anthropic_system_arg(msgs, prompt_cache_enabled=False)
    assert out == [
        {"type": "text", "text": "STATIC"},
        {"type": "text", "text": "DYNAMIC"},
    ]


def test_per_message_hint_single_block() -> None:
    """A single cacheable system message still routes through the
    per-message path and produces one text block (not a plain string)."""
    msgs = [ChatMessage("system", "STATIC", cache_control="ephemeral")]
    out = _anthropic_system_arg(msgs, prompt_cache_enabled=True)
    assert out == [
        {
            "type": "text",
            "text": "STATIC",
            "cache_control": {"type": "ephemeral"},
        }
    ]


def test_chatmessage_to_dict_excludes_cache_control() -> None:
    """``cache_control`` is an Anthropic-only hint; it MUST NOT leak
    into the OpenAI / DeepSeek JSON payload."""
    msg = ChatMessage("system", "HELLO", cache_control="ephemeral")
    payload = msg.to_dict()
    assert payload == {"role": "system", "content": "HELLO"}
    assert "cache_control" not in payload
