"""Lightweight per-segment timing breadcrumbs.

The interview graph runs in short background segments.  LLM calls happen deep
inside agents, while trace rows are written by workflow nodes after the work is
done.  A ContextVar gives those two layers a small shared buffer without
thread-global leakage or coupling LLM code to the database.
"""
from __future__ import annotations

from contextvars import ContextVar, Token
from typing import Any

_LLM_TIMING_EVENTS: ContextVar[list[dict[str, Any]] | None] = ContextVar(
    "llm_timing_events",
    default=None,
)


def start_timing_trace() -> Token[list[dict[str, Any]] | None]:
    """Start a fresh timing buffer for the current execution context."""
    return _LLM_TIMING_EVENTS.set([])


def reset_timing_trace(token: Token[list[dict[str, Any]] | None]) -> None:
    """Restore the previous timing buffer."""
    _LLM_TIMING_EVENTS.reset(token)


def record_llm_timing_event(
    *,
    role: str | None,
    provider: str,
    model: str,
    status: str,
    elapsed_ms: int,
    input_chars: int,
    output_chars: int | None,
    messages: int,
    json_mode: bool,
    max_tokens: int,
    request_timeout: float | None,
    attempts: int,
    base_host: str,
    error_kind: str | None = None,
) -> None:
    """Append one LLM timing event if a buffer is active."""
    events = _LLM_TIMING_EVENTS.get()
    if events is None:
        return
    event: dict[str, Any] = {
        "role": role or "unknown",
        "provider": provider,
        "model": model,
        "status": status,
        "elapsed_ms": max(0, int(elapsed_ms)),
        "input_chars": max(0, int(input_chars)),
        "output_chars": None if output_chars is None else max(0, int(output_chars)),
        "messages": max(0, int(messages)),
        "json_mode": bool(json_mode),
        "max_tokens": int(max_tokens),
        "request_timeout": request_timeout,
        "attempts": max(1, int(attempts)),
        "base_host": base_host,
    }
    if error_kind:
        event["error_kind"] = error_kind
    events.append(event)


def consume_llm_timing_events() -> list[dict[str, Any]]:
    """Return and clear buffered LLM timing events for the current context."""
    events = _LLM_TIMING_EVENTS.get()
    if not events:
        return []
    out = list(events)
    events.clear()
    return out

