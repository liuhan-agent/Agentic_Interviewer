"""Prometheus metrics used by the API and workflow side channels."""
from __future__ import annotations

import time
from collections import defaultdict
from collections.abc import Callable
from typing import Any

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

HTTP_REQUESTS = Counter(
    "http_requests_total",
    "HTTP requests served by the API.",
    ["method", "path", "status"],
)
HTTP_REQUEST_DURATION = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency in seconds.",
    ["method", "path"],
)
TRACE_WRITE_SUCCESS = Counter(
    "trace_write_success_total",
    "Successful local trace writes.",
    ["operation"],
)
TRACE_WRITE_FAILURES = Counter(
    "trace_write_failures_total",
    "Failed local trace writes swallowed by the tracer.",
    ["operation"],
)
VERIFIER_DRIFT_EVENTS = Counter(
    "verifier_drift_events_total",
    "Verifier drift observations accepted by the configured backend.",
    ["dimension", "verdict", "overruled", "abstained"],
)
VERIFIER_DRIFT_STORE_ERRORS = Counter(
    "verifier_drift_store_errors_total",
    "Verifier drift backend store/read errors.",
    ["backend"],
)
SETUP_PARSE_ERRORS = Counter(
    "setup_parse_errors_total",
    "Setup parsing errors by endpoint and code.",
    ["endpoint", "code"],
)
CONTEXT_FLAGS = Counter(
    "context_flags_total",
    "User-material context flags emitted by parsers.",
    ["source", "flag"],
)
RATE_LIMIT_BLOCKS = Counter(
    "rate_limit_blocks_total",
    "Rate limit blocks by endpoint.",
    ["endpoint"],
)
WS_INVALID_FRAMES = Counter(
    "ws_invalid_frames_total",
    "Invalid voice WebSocket frames by reason.",
    ["reason"],
)
SESSION_PRIVACY_DELETES = Counter(
    "session_privacy_deletes_total",
    "Privacy deletion operations by kind.",
    ["kind"],
)
_TRACE_WRITE_SUCCESS_COUNTS: dict[str, int] = defaultdict(int)
_TRACE_WRITE_FAILURE_COUNTS: dict[str, int] = defaultdict(int)
_SETUP_PARSE_ERROR_COUNTS: dict[str, int] = defaultdict(int)
_CONTEXT_FLAG_COUNTS: dict[str, int] = defaultdict(int)
_RATE_LIMIT_BLOCK_COUNTS: dict[str, int] = defaultdict(int)
_WS_INVALID_FRAME_COUNTS: dict[str, int] = defaultdict(int)
_SESSION_PRIVACY_DELETE_COUNTS: dict[str, int] = defaultdict(int)


def record_http_request(method: str, path: str, status: int, duration: float) -> None:
    HTTP_REQUESTS.labels(method=method, path=path, status=str(status)).inc()
    HTTP_REQUEST_DURATION.labels(method=method, path=path).observe(duration)


def record_trace_write_success(operation: str) -> None:
    _TRACE_WRITE_SUCCESS_COUNTS[operation] += 1
    TRACE_WRITE_SUCCESS.labels(operation=operation).inc()


def record_trace_write_failure(operation: str) -> None:
    _TRACE_WRITE_FAILURE_COUNTS[operation] += 1
    TRACE_WRITE_FAILURES.labels(operation=operation).inc()


def trace_write_success_total(operation: str) -> int:
    return _TRACE_WRITE_SUCCESS_COUNTS.get(operation, 0)


def trace_write_failures_total(operation: str) -> int:
    return _TRACE_WRITE_FAILURE_COUNTS.get(operation, 0)


def tracer_health_snapshot() -> dict[str, Any]:
    operations = sorted(
        set(_TRACE_WRITE_SUCCESS_COUNTS) | set(_TRACE_WRITE_FAILURE_COUNTS)
    )
    per_operation = {
        op: {
            "success": trace_write_success_total(op),
            "failures": trace_write_failures_total(op),
        }
        for op in operations
    }
    success_total = sum(_TRACE_WRITE_SUCCESS_COUNTS.values())
    failures_total = sum(_TRACE_WRITE_FAILURE_COUNTS.values())
    return {
        "status": "degraded" if failures_total else "ok",
        "trace_write_success_total": success_total,
        "trace_write_failures_total": failures_total,
        "operations": per_operation,
    }


def record_verifier_drift_event(
    *,
    dimension: str,
    verdict: str,
    overruled: bool,
    abstained: bool,
) -> None:
    VERIFIER_DRIFT_EVENTS.labels(
        dimension=dimension,
        verdict=verdict,
        overruled=str(bool(overruled)).lower(),
        abstained=str(bool(abstained)).lower(),
    ).inc()


def record_verifier_drift_store_error(backend: str) -> None:
    VERIFIER_DRIFT_STORE_ERRORS.labels(backend=backend).inc()


def record_setup_parse_error(endpoint: str, code: str) -> None:
    key = f"{endpoint}:{code}"
    _SETUP_PARSE_ERROR_COUNTS[key] += 1
    SETUP_PARSE_ERRORS.labels(endpoint=endpoint, code=code).inc()


def record_context_flags(source: str, flags: list[str]) -> None:
    for flag in flags:
        _CONTEXT_FLAG_COUNTS[f"{source}:{flag}"] += 1
        CONTEXT_FLAGS.labels(source=source, flag=flag).inc()


def record_rate_limit_block(endpoint: str) -> None:
    _RATE_LIMIT_BLOCK_COUNTS[endpoint] += 1
    RATE_LIMIT_BLOCKS.labels(endpoint=endpoint).inc()


def record_ws_invalid_frame(reason: str) -> None:
    _WS_INVALID_FRAME_COUNTS[reason] += 1
    WS_INVALID_FRAMES.labels(reason=reason).inc()


def record_session_privacy_delete(kind: str, count: int = 1) -> None:
    if count <= 0:
        return
    _SESSION_PRIVACY_DELETE_COUNTS[kind] += count
    SESSION_PRIVACY_DELETES.labels(kind=kind).inc(count)


def security_metrics_snapshot() -> dict[str, dict[str, int]]:
    return {
        "setup_parse_errors": dict(_SETUP_PARSE_ERROR_COUNTS),
        "context_flags": dict(_CONTEXT_FLAG_COUNTS),
        "rate_limit_blocks": dict(_RATE_LIMIT_BLOCK_COUNTS),
        "ws_invalid_frames": dict(_WS_INVALID_FRAME_COUNTS),
        "session_privacy_deletes": dict(_SESSION_PRIVACY_DELETE_COUNTS),
    }


def reset_security_metrics_for_tests() -> None:
    _SETUP_PARSE_ERROR_COUNTS.clear()
    _CONTEXT_FLAG_COUNTS.clear()
    _RATE_LIMIT_BLOCK_COUNTS.clear()
    _WS_INVALID_FRAME_COUNTS.clear()
    _SESSION_PRIVACY_DELETE_COUNTS.clear()


def metrics_text() -> bytes:
    return generate_latest()


def metrics_content_type() -> str:
    return CONTENT_TYPE_LATEST


def time_call(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> tuple[Any, float]:
    start = time.monotonic()
    result = fn(*args, **kwargs)
    return result, time.monotonic() - start
