"""Decorate a LangGraph checkpoint saver with write-latency observability.

Why this lives outside ``langgraph_workflow.py``
------------------------------------------------
Wrapping the saver is a cross-cutting concern: every backend
(``MemorySaver``, ``PostgresSaver``, future custom savers) needs the
same instrumentation, and so does any test that builds its own saver
and wants the same metrics to fire. Pulling the wrapping logic into a
single module keeps ``langgraph_workflow.py`` focused on graph
construction and lets unit tests exercise the wrapper without spinning
up the full graph.

Why instance-level monkey-patching (not subclassing)
----------------------------------------------------
``BaseCheckpointSaver`` exposes ``put`` / ``put_writes`` /
``aput`` / ``aput_writes``. Subclassing means we have to keep the
class hierarchy in lock-step with whatever LangGraph adds next; the
wrapper would break silently when the upstream library introduces a
new write method. Monkey-patching the bound methods on the saver
instance keeps every other method (``get`` / ``list`` / ``setup`` /
the connection-pool plumbing on Postgres / etc.) untouched and
forwards new write methods automatically as long as we hook them by
name.
"""
from __future__ import annotations

import inspect
import time
from typing import Any

from app.core.logging import get_logger
from app.core.metrics import record_checkpoint_write, record_checkpoint_write_failure
from app.core.timing import record_checkpoint_write_event

log = get_logger(__name__)

_SYNC_WRITE_METHODS = ("put", "put_writes")
_ASYNC_WRITE_METHODS = ("aput", "aput_writes")
_WRAPPED_MARKER = "_checkpoint_metrics_wrapped"


def _record(operation: str, backend: str, started_at: float) -> None:
    elapsed_ms = int((time.perf_counter() - started_at) * 1000)
    record_checkpoint_write(
        backend=backend, operation=operation, elapsed_ms=elapsed_ms
    )
    record_checkpoint_write_event(elapsed_ms=elapsed_ms)


def _record_failure(operation: str, backend: str) -> None:
    record_checkpoint_write_failure(backend=backend, operation=operation)


def _wrap_sync_method(saver: Any, method_name: str, backend: str) -> None:
    original = getattr(saver, method_name, None)
    if original is None or not callable(original):
        return

    def timed(*args: Any, **kwargs: Any) -> Any:
        started_at = time.perf_counter()
        try:
            result = original(*args, **kwargs)
        except Exception:
            _record_failure(method_name, backend)
            raise
        _record(method_name, backend, started_at)
        return result

    setattr(saver, method_name, timed)


def _wrap_async_method(saver: Any, method_name: str, backend: str) -> None:
    original = getattr(saver, method_name, None)
    if original is None or not callable(original):
        return

    if not inspect.iscoroutinefunction(original):
        # Some savers expose async-named methods as plain callables
        # returning awaitables. Treat both cases uniformly: wrap the
        # call result with an inline awaiter.
        def timed_callable(*args: Any, **kwargs: Any) -> Any:
            started_at = time.perf_counter()
            try:
                result = original(*args, **kwargs)
            except Exception:
                _record_failure(method_name, backend)
                raise
            if inspect.isawaitable(result):
                async def _await_with_record() -> Any:
                    try:
                        out = await result
                    except Exception:
                        _record_failure(method_name, backend)
                        raise
                    _record(method_name, backend, started_at)
                    return out

                return _await_with_record()
            _record(method_name, backend, started_at)
            return result

        setattr(saver, method_name, timed_callable)
        return

    async def timed_async(*args: Any, **kwargs: Any) -> Any:
        started_at = time.perf_counter()
        try:
            result = await original(*args, **kwargs)
        except Exception:
            _record_failure(method_name, backend)
            raise
        _record(method_name, backend, started_at)
        return result

    setattr(saver, method_name, timed_async)


def wrap_saver_with_metrics(saver: Any, *, backend: str) -> Any:
    """Patch a checkpoint saver instance to record write latency.

    Idempotent: re-wrapping a saver is a no-op (we mark the instance
    with a private attribute on the first call). This keeps the
    behaviour stable when both ``build_workflow`` and an explicit test
    fixture try to wrap the same saver.

    The function returns the same instance so callers can still write
    ``saver = wrap_saver_with_metrics(get_my_saver(), backend="postgres")``
    in a single line.
    """
    if saver is None:
        return saver
    if getattr(saver, _WRAPPED_MARKER, False):
        return saver

    backend_label = (backend or "unknown") or "unknown"
    for method_name in _SYNC_WRITE_METHODS:
        try:
            _wrap_sync_method(saver, method_name, backend_label)
        except Exception as exc:  # pragma: no cover - defensive
            log.debug(
                "checkpoint metrics: failed to wrap %s on %s: %s",
                method_name,
                saver.__class__.__name__,
                exc,
            )
    for method_name in _ASYNC_WRITE_METHODS:
        try:
            _wrap_async_method(saver, method_name, backend_label)
        except Exception as exc:  # pragma: no cover - defensive
            log.debug(
                "checkpoint metrics: failed to wrap %s on %s: %s",
                method_name,
                saver.__class__.__name__,
                exc,
            )
    try:
        setattr(saver, _WRAPPED_MARKER, True)
    except Exception:  # pragma: no cover - some savers freeze attrs
        log.debug(
            "checkpoint metrics: cannot mark %s as wrapped",
            saver.__class__.__name__,
        )
    return saver
