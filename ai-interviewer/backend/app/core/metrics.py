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
CHECKPOINT_WRITE_DURATION_SECONDS = Histogram(
    "checkpoint_write_duration_seconds",
    "Latency of LangGraph checkpoint writes by backend and operation.",
    ["backend", "operation"],
    buckets=(
        0.001,
        0.005,
        0.01,
        0.025,
        0.05,
        0.1,
        0.25,
        0.5,
        1.0,
        2.5,
        5.0,
        10.0,
    ),
)
CHECKPOINT_WRITE_FAILURES = Counter(
    "checkpoint_write_failures_total",
    "Checkpoint write failures by backend and operation.",
    ["backend", "operation"],
)
LLM_CALLS_TOTAL = Counter(
    "llm_calls_total",
    "LLM provider calls observed at call_chat exit.",
    ["agent_role", "provider", "model", "status"],
)
QUESTION_FALLBACKS_TOTAL = Counter(
    "question_fallbacks_total",
    "Per-turn fallback paths triggered in the interview loop. "
    "``kind`` is one of: language / duplicate / safety / "
    "contract_unsigned / evaluator_fallback.",
    ["kind"],
)
LLM_PROMPT_TOKENS_TOTAL = Counter(
    "llm_prompt_tokens_total",
    "Prompt tokens consumed by LLM calls (real or estimated).",
    ["agent_role", "provider", "model"],
)
LLM_COMPLETION_TOKENS_TOTAL = Counter(
    "llm_completion_tokens_total",
    "Completion tokens produced by LLM calls (real or estimated).",
    ["agent_role", "provider", "model"],
)
_TRACE_WRITE_SUCCESS_COUNTS: dict[str, int] = defaultdict(int)
_TRACE_WRITE_FAILURE_COUNTS: dict[str, int] = defaultdict(int)
_SETUP_PARSE_ERROR_COUNTS: dict[str, int] = defaultdict(int)
_CONTEXT_FLAG_COUNTS: dict[str, int] = defaultdict(int)
_RATE_LIMIT_BLOCK_COUNTS: dict[str, int] = defaultdict(int)
_WS_INVALID_FRAME_COUNTS: dict[str, int] = defaultdict(int)
_SESSION_PRIVACY_DELETE_COUNTS: dict[str, int] = defaultdict(int)
_LLM_CALL_COUNTS: dict[str, int] = defaultdict(int)
_LLM_PROMPT_TOKEN_COUNTS: dict[str, int] = defaultdict(int)
_LLM_COMPLETION_TOKEN_COUNTS: dict[str, int] = defaultdict(int)
_QUESTION_FALLBACK_COUNTS: dict[str, int] = defaultdict(int)


# Approximate USD price per 1K tokens, prompt / completion. Numbers
# pulled from public 2025 list prices for the most common interview-loop
# models. They are deliberately coarse: cost_summary.est_usd is an
# observability hint, not a billing source. When a model is missing we
# fall back to a tiny default so the field never returns None.
_LLM_PRICE_PER_1K: dict[str, tuple[float, float]] = {
    # OpenAI
    "gpt-4o": (0.0025, 0.01),
    "gpt-4o-mini": (0.00015, 0.0006),
    "gpt-4-turbo": (0.01, 0.03),
    "gpt-4": (0.03, 0.06),
    "gpt-3.5-turbo": (0.0005, 0.0015),
    # Anthropic
    "claude-3-5-sonnet": (0.003, 0.015),
    "claude-3-5-haiku": (0.0008, 0.004),
    "claude-3-opus": (0.015, 0.075),
    "claude-3-sonnet": (0.003, 0.015),
    "claude-3-haiku": (0.00025, 0.00125),
    # DeepSeek
    "deepseek-chat": (0.00027, 0.0011),
    "deepseek-reasoner": (0.00055, 0.0022),
    "deepseek-coder": (0.00027, 0.0011),
}
_DEFAULT_LLM_PRICE_PER_1K: tuple[float, float] = (0.0005, 0.0015)


def _resolve_llm_price(model: str) -> tuple[float, float]:
    """Return ``(prompt_per_1k, completion_per_1k)`` for ``model``.

    Match strategy: exact match first, then longest prefix match (so
    ``gpt-4o-mini-2024-07-18`` still maps to ``gpt-4o-mini``). Unknown
    models fall back to a small default so ``est_usd`` never returns
    ``None``.
    """
    if not model:
        return _DEFAULT_LLM_PRICE_PER_1K
    lowered = model.lower().strip()
    if lowered in _LLM_PRICE_PER_1K:
        return _LLM_PRICE_PER_1K[lowered]
    best: tuple[float, float] | None = None
    best_len = -1
    for key, value in _LLM_PRICE_PER_1K.items():
        if lowered.startswith(key) and len(key) > best_len:
            best, best_len = value, len(key)
    return best or _DEFAULT_LLM_PRICE_PER_1K


def estimate_llm_cost_usd(
    *,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
) -> float:
    """Best-effort USD cost estimate for one LLM call.

    Returns ``0.0`` for non-positive token counts. Uses
    :func:`_resolve_llm_price` for the per-1K rates. Six-decimal
    rounding keeps multi-call accumulation stable to ~$0.000001.
    """
    if prompt_tokens <= 0 and completion_tokens <= 0:
        return 0.0
    prompt_price, completion_price = _resolve_llm_price(model)
    cost = (
        max(0, prompt_tokens) / 1000.0 * prompt_price
        + max(0, completion_tokens) / 1000.0 * completion_price
    )
    return round(cost, 6)


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


_CHECKPOINT_WRITE_OBSERVATIONS: dict[str, list[float]] = defaultdict(list)
_CHECKPOINT_WRITE_FAILURE_COUNTS: dict[str, int] = defaultdict(int)
# How many recent observations per ``(backend, operation)`` to keep around so
# the admin dashboard can render p50 / p95 without scraping Prometheus. The
# bound is intentionally small so the in-process memory cost is negligible
# even on a sustained-traffic deployment; production observability still goes
# through the Prometheus Histogram which never gets truncated.
_CHECKPOINT_WRITE_OBSERVATION_LIMIT = 256


def record_checkpoint_write(
    *,
    backend: str,
    operation: str,
    elapsed_ms: int,
) -> None:
    """Observe one successful checkpoint-write call.

    ``backend`` is one of the configured saver names (``memory`` /
    ``postgres`` / ``unknown`` for tests). ``operation`` is the saver
    method that actually performed the write — ``put`` for full
    checkpoints, ``put_writes`` for inter-node intermediate writes.
    Both labels are required by the Prometheus contract; the helper
    normalises empty / None values to ``unknown`` so a sample is never
    silently dropped.
    """
    backend_label = (backend or "unknown") or "unknown"
    operation_label = (operation or "unknown") or "unknown"
    elapsed_seconds = max(0, int(elapsed_ms)) / 1000.0
    CHECKPOINT_WRITE_DURATION_SECONDS.labels(
        backend=backend_label,
        operation=operation_label,
    ).observe(elapsed_seconds)
    key = f"{backend_label}:{operation_label}"
    bucket = _CHECKPOINT_WRITE_OBSERVATIONS[key]
    bucket.append(elapsed_seconds * 1000.0)
    if len(bucket) > _CHECKPOINT_WRITE_OBSERVATION_LIMIT:
        # Keep only the latest N observations to bound the memory cost.
        del bucket[: len(bucket) - _CHECKPOINT_WRITE_OBSERVATION_LIMIT]


def record_checkpoint_write_failure(
    *,
    backend: str,
    operation: str,
) -> None:
    backend_label = (backend or "unknown") or "unknown"
    operation_label = (operation or "unknown") or "unknown"
    CHECKPOINT_WRITE_FAILURES.labels(
        backend=backend_label,
        operation=operation_label,
    ).inc()
    _CHECKPOINT_WRITE_FAILURE_COUNTS[f"{backend_label}:{operation_label}"] += 1


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    idx = max(0, min(len(sorted_vals) - 1, int(round(pct * (len(sorted_vals) - 1)))))
    return sorted_vals[idx]


def checkpoint_write_snapshot() -> dict[str, dict[str, Any]]:
    """Compact in-process snapshot for the admin dashboard.

    Per ``(backend, operation)`` returns the count, p50 and p95 of the
    latest observations (in milliseconds) plus any failure count. The
    Prometheus Histogram remains the source of truth for long-horizon
    aggregation; this snapshot is just a zero-dependency way for an
    admin endpoint to render a quick latency summary without scraping.
    """
    snapshot: dict[str, dict[str, Any]] = {}
    keys = sorted(
        set(_CHECKPOINT_WRITE_OBSERVATIONS) | set(_CHECKPOINT_WRITE_FAILURE_COUNTS)
    )
    for key in keys:
        observations = _CHECKPOINT_WRITE_OBSERVATIONS.get(key, [])
        snapshot[key] = {
            "count": len(observations),
            "p50_ms": round(_percentile(observations, 0.5), 3),
            "p95_ms": round(_percentile(observations, 0.95), 3),
            "p99_ms": round(_percentile(observations, 0.99), 3),
            "failures": _CHECKPOINT_WRITE_FAILURE_COUNTS.get(key, 0),
        }
    return snapshot


def reset_checkpoint_metrics_for_tests() -> None:
    _CHECKPOINT_WRITE_OBSERVATIONS.clear()
    _CHECKPOINT_WRITE_FAILURE_COUNTS.clear()


def record_llm_call(
    *,
    agent_role: str | None,
    provider: str,
    model: str,
    status: str,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
) -> None:
    """Record a single LLM call at ``call_chat`` exit.

    Increments three Counters: one for the call (success / error /
    stub), one for prompt tokens, one for completion tokens. Token
    counters are never decremented and accept estimated values when
    the provider response did not include a ``usage`` block.

    Empty / unknown labels are normalised to non-empty placeholders so
    Prometheus does not drop the sample silently.
    """
    role = (agent_role or "unknown") or "unknown"
    provider_label = (provider or "unknown") or "unknown"
    model_label = (model or "unknown") or "unknown"
    status_label = (status or "unknown") or "unknown"

    LLM_CALLS_TOTAL.labels(
        agent_role=role,
        provider=provider_label,
        model=model_label,
        status=status_label,
    ).inc()
    _LLM_CALL_COUNTS[f"{role}:{provider_label}:{model_label}:{status_label}"] += 1

    prompt = max(0, int(prompt_tokens or 0))
    completion = max(0, int(completion_tokens or 0))
    if prompt:
        LLM_PROMPT_TOKENS_TOTAL.labels(
            agent_role=role,
            provider=provider_label,
            model=model_label,
        ).inc(prompt)
        _LLM_PROMPT_TOKEN_COUNTS[
            f"{role}:{provider_label}:{model_label}"
        ] += prompt
    if completion:
        LLM_COMPLETION_TOKENS_TOTAL.labels(
            agent_role=role,
            provider=provider_label,
            model=model_label,
        ).inc(completion)
        _LLM_COMPLETION_TOKEN_COUNTS[
            f"{role}:{provider_label}:{model_label}"
        ] += completion


def llm_metrics_snapshot() -> dict[str, dict[str, int]]:
    """Read-only snapshot of LLM Counter accumulators for tests / admin."""
    return {
        "llm_calls": dict(_LLM_CALL_COUNTS),
        "llm_prompt_tokens": dict(_LLM_PROMPT_TOKEN_COUNTS),
        "llm_completion_tokens": dict(_LLM_COMPLETION_TOKEN_COUNTS),
    }


def reset_llm_metrics_for_tests() -> None:
    _LLM_CALL_COUNTS.clear()
    _LLM_PROMPT_TOKEN_COUNTS.clear()
    _LLM_COMPLETION_TOKEN_COUNTS.clear()


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


# Known fallback kinds. Unknown kinds are still recorded but counted
# under their raw label so callers see the typo / new kind explicitly
# rather than getting silently dropped.
QUESTION_FALLBACK_KINDS: tuple[str, ...] = (
    "language",
    "duplicate",
    "safety",
    "contract_unsigned",
    "evaluator_fallback",
)


def record_question_fallback(kind: str) -> None:
    """Increment the per-kind fallback Counter.

    Defensive on purpose: the callers live on the interview hot path
    (``ask_question_node`` / ``evaluator_node``). Any exception leaking
    out of an observability helper would crash the turn, so we wrap
    the Prometheus increment in a try/except and only log.
    """
    label = (kind or "unknown") or "unknown"
    try:
        QUESTION_FALLBACKS_TOTAL.labels(kind=label).inc()
    except Exception:  # pragma: no cover - never break the hot path
        pass
    _QUESTION_FALLBACK_COUNTS[label] += 1


def question_fallbacks_snapshot() -> dict[str, int]:
    """Compact snapshot keyed by ``kind`` for the admin endpoint.

    Always returns a row for every entry in ``QUESTION_FALLBACK_KINDS``
    (zero when nothing fired) so the admin dashboard can render a
    stable layout without conditional templating. Unknown kinds (e.g.
    typos at a call site) are appended as-is.
    """
    snapshot: dict[str, int] = {
        kind: _QUESTION_FALLBACK_COUNTS.get(kind, 0)
        for kind in QUESTION_FALLBACK_KINDS
    }
    for kind, count in _QUESTION_FALLBACK_COUNTS.items():
        if kind not in snapshot:
            snapshot[kind] = count
    return snapshot


def reset_question_fallback_metrics_for_tests() -> None:
    _QUESTION_FALLBACK_COUNTS.clear()


def metrics_text() -> bytes:
    return generate_latest()


def metrics_content_type() -> str:
    return CONTENT_TYPE_LATEST


def time_call(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> tuple[Any, float]:
    start = time.monotonic()
    result = fn(*args, **kwargs)
    return result, time.monotonic() - start
