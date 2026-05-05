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
# Latest checkpoint-write duration observed in the current execution context.
# Set by the saver wrapper in ``app/engine/workflow/checkpoint_metrics.py``
# every time the checkpointer writes; read by ``reward_update_node`` so the
# trace payload can carry ``db_write_ms`` next to the existing
# ``elapsed_ms``. Per-context (not global) so concurrent sessions do not
# clobber each other's measurements.
_LATEST_DB_WRITE_MS: ContextVar[int | None] = ContextVar(
    "latest_db_write_ms",
    default=None,
)


def start_timing_trace() -> Token[list[dict[str, Any]] | None]:
    """Start a fresh timing buffer for the current execution context."""
    _LATEST_DB_WRITE_MS.set(None)
    return _LLM_TIMING_EVENTS.set([])


def reset_timing_trace(token: Token[list[dict[str, Any]] | None]) -> None:
    """Restore the previous timing buffer and clear per-segment write timing."""
    _LLM_TIMING_EVENTS.reset(token)
    _LATEST_DB_WRITE_MS.set(None)


def record_checkpoint_write_event(*, elapsed_ms: int) -> None:
    """Stash the latest checkpoint-write duration for the current context.

    The value is intentionally last-write-wins: by the time a node reads it
    via :func:`get_latest_db_write_ms`, the most recent saver write is the
    most relevant. Older writes are still permanently aggregated in the
    Prometheus Histogram via :func:`app.core.metrics.record_checkpoint_write`
    so multi-write spans are not lost from observability.
    """
    _LATEST_DB_WRITE_MS.set(max(0, int(elapsed_ms)))


def get_latest_db_write_ms() -> int | None:
    """Read the most recent checkpoint-write duration in this context."""
    return _LATEST_DB_WRITE_MS.get()


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
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
    usage_estimated: bool = False,
) -> None:
    """Append one LLM timing event if a buffer is active.

    ``prompt_tokens`` / ``completion_tokens`` are recorded when the
    provider returned a usage block, or when the caller estimated
    them from char counts. ``usage_estimated`` distinguishes the two
    cases so downstream cost summaries can flag low-confidence rows.
    """
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
    if prompt_tokens is not None:
        event["prompt_tokens"] = max(0, int(prompt_tokens))
    if completion_tokens is not None:
        event["completion_tokens"] = max(0, int(completion_tokens))
    if usage_estimated:
        event["usage_estimated"] = True
    events.append(event)


def consume_llm_timing_events() -> list[dict[str, Any]]:
    """Return and clear buffered LLM timing events for the current context."""
    events = _LLM_TIMING_EVENTS.get()
    if not events:
        return []
    out = list(events)
    events.clear()
    return out
