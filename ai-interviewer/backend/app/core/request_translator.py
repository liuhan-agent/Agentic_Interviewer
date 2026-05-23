"""Translate a user-facing API request into graph inputs.

Mirrors the ACO four-layer model: ``request`` -> ``execution_config``
-> ``runtime_config`` -> ``initial_state``. The split is important
even for demo-sized projects because it gives you a single place to
evolve request shape without touching the graph.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from app.core.request_context import current_traceparent_trace_id
from app.core.settings import get_settings
from app.engine.workflow.state import InterviewState, build_initial_state
from app.services.resume_parser import normalise_resume_parsed_focus_areas

_ALLOWED_MODES = {"tech", "behavioral", "mixed"}
_ALLOWED_INTERVIEW_DEPTHS = {"short", "standard", "deep"}
_MAX_TURNS_LIMIT = 20
_MAX_TURN_BUDGET_LIMIT = 30
_ALLOWED_RAG_MODES = {"vector", "hybrid"}
_RAG_TOP_K_DEFAULT = 5
_RAG_TOP_K_MIN = 1
_RAG_TOP_K_MAX = 50
_LLM_TEMPERATURE_MIN = 0.0
_LLM_TEMPERATURE_MAX = 2.0

# Frontend historically types ``mode`` as ``"mixed" | "text" | "voice"``
# (the latter two describe the interaction channel, not the interview
# topic). We accept them as aliases of ``mixed`` so those values don't
# get silently coerced away and the TypeScript definition stays
# honest. The channel itself is signalled separately (HTTP vs
# ``/ws/voice/{id}``).
_MODE_ALIASES = {"text": "mixed", "voice": "mixed"}


def _new_session_id() -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    return f"sess-{stamp}-{uuid.uuid4().hex[:6]}"


def _clamp_int(value: Any, default: int, *, lower: int, upper: int) -> int:
    raw = default if value is None else int(value)
    return max(lower, min(upper, raw))


def _clamp_float(value: Any, default: float, *, lower: float, upper: float) -> float:
    raw = default if value is None else float(value)
    return max(lower, min(upper, raw))


def _safe_clamp_int(
    value: Any,
    default: int,
    *,
    lower: int,
    upper: int,
) -> int:
    """Clamp ``value`` into ``[lower, upper]``, falling back to ``default``.

    Unlike :func:`_clamp_int`, garbage values (non-numeric strings,
    booleans, lists) collapse to ``default`` instead of raising. The
    runtime-config layer accepts free-form ``dict[str, Any]`` payloads
    that are not always pre-validated by the FastAPI request schema
    (CLI demos / direct service calls), so the layer must absorb bad
    input rather than 500.
    """
    if value is None or isinstance(value, bool):
        raw = default
    else:
        try:
            raw = int(value)
        except (TypeError, ValueError):
            raw = default
    return max(lower, min(upper, raw))


def _normalise_rag_mode(value: Any) -> str:
    if isinstance(value, str) and value in _ALLOWED_RAG_MODES:
        return value
    return "vector"


def _normalise_llm_temperature(value: Any) -> float | None:
    """Clamp temperature to [0.0, 2.0] or fall back to ``None``.

    Returning ``None`` (instead of a default) preserves the long-standing
    "let LLM call sites read ``settings.llm_temperature`` when unset"
    contract; only out-of-range numerics get clamped.
    """
    if value is None or isinstance(value, bool):
        return None
    try:
        candidate = float(value)
    except (TypeError, ValueError):
        return None
    return max(_LLM_TEMPERATURE_MIN, min(_LLM_TEMPERATURE_MAX, candidate))


def _normalise_interview_depth(value: Any) -> str:
    if isinstance(value, str) and value in _ALLOWED_INTERVIEW_DEPTHS:
        return value
    return "standard"


def _execution_config(req: dict[str, Any]) -> dict[str, Any]:
    """Top-level graph knobs that can change the loop control."""
    settings = get_settings()
    return {
        "max_turns": _clamp_int(
            req.get("max_turns"),
            settings.default_max_turns,
            lower=1,
            upper=_MAX_TURNS_LIMIT,
        ),
        "quality_threshold": _clamp_float(
            req.get("quality_threshold"),
            settings.default_quality_threshold,
            lower=0.0,
            upper=10.0,
        ),
        "turn_budget": _clamp_int(
            req.get("turn_budget"),
            settings.default_turn_budget,
            lower=1,
            upper=_MAX_TURN_BUDGET_LIMIT,
        ),
    }


def _runtime_config(req: dict[str, Any]) -> dict[str, Any]:
    """Per-node execution details.

    ``use_sync_provider`` defaults to **False** so the API / WebSocket
    surface uses the durable interrupt path in ``wait_answer_node``.
    The session manager handles ``Command(resume=...)`` to re-enter
    the graph after each answer submission, and the checkpoint backend
    (MemorySaver or PostgresSaver) persists state across interrupts.

    CLI demos and tests that drive the graph synchronously should
    pass ``use_sync_provider=True`` to keep the old
    ``QueueAnswerProvider`` blocking behaviour.
    """
    return {
        "rag_top_k": _safe_clamp_int(
            req.get("rag_top_k"),
            _RAG_TOP_K_DEFAULT,
            lower=_RAG_TOP_K_MIN,
            upper=_RAG_TOP_K_MAX,
        ),
        "rag_mode": _normalise_rag_mode(req.get("rag_mode")),
        "llm_temperature": _normalise_llm_temperature(req.get("llm_temperature")),
        "interview_depth": _normalise_interview_depth(req.get("interview_depth")),
        "mode": req.get("mode", "mixed"),
        "use_sync_provider": bool(req.get("use_sync_provider", False)),
    }


def _context_flag_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [flag for flag in value if isinstance(flag, str) and flag]


def _user_material_context_flags(
    candidate: dict[str, Any],
    job_spec: dict[str, Any],
) -> dict[str, list[str]]:
    resume_parsed = candidate.get("resume_parsed") or {}
    if not isinstance(resume_parsed, dict):
        resume_parsed = {}
    return {
        "resume": _context_flag_list(resume_parsed.get("context_flags")),
        "job_spec": _context_flag_list(job_spec.get("context_flags")),
    }


def _focus_dimensions(req: dict[str, Any], job_spec: dict[str, Any]) -> list[str]:
    raw = req.get("focus_dimensions")
    if not isinstance(raw, list):
        return []
    allowed = set(job_spec.get("rubric_dimensions") or [])
    focus: list[str] = []
    for item in raw:
        if not isinstance(item, str) or item not in allowed or item in focus:
            continue
        focus.append(item)
    return focus


def _candidate_with_normalised_focus_areas(candidate: Any) -> dict[str, Any]:
    if not isinstance(candidate, dict):
        return {}
    out = dict(candidate)
    out["resume_parsed"] = normalise_resume_parsed_focus_areas(
        out.get("resume_parsed") or {}
    )
    return out


def translate_request(req: dict[str, Any]) -> tuple[str, str, InterviewState]:
    """Build ``(session_id, trace_id, initial_state)`` from a request dict.

    ``req`` should include at least ``candidate`` and ``job_spec``. All
    other fields are optional and fall back to settings defaults.
    """
    session_id = req.get("session_id") or _new_session_id()
    trace_id = (
        req.get("trace_id")
        or current_traceparent_trace_id()
        or f"trace-{uuid.uuid4().hex[:10]}"
    )
    exec_cfg = _execution_config(req)
    runtime = _runtime_config(req)
    mode_raw = req.get("mode", "mixed")
    mode_aliased = _MODE_ALIASES.get(mode_raw, mode_raw)
    mode = mode_aliased if mode_aliased in _ALLOWED_MODES else "mixed"
    if req.get("enable_video_analysis"):
        runtime["enable_video_analysis"] = True
    candidate = _candidate_with_normalised_focus_areas(req.get("candidate") or {})
    job_spec = req.get("job_spec") or {}
    initial = build_initial_state(
        session_id=session_id,
        trace_id=trace_id,
        candidate=candidate,
        job_spec=job_spec,
        context_flags=_user_material_context_flags(candidate, job_spec),
        focus_dimensions=_focus_dimensions(req, job_spec),
        mode=mode,  # type: ignore[arg-type]
        runtime_config=runtime,
        max_turns=exec_cfg["max_turns"],
        quality_threshold=exec_cfg["quality_threshold"],
        turn_budget=exec_cfg["turn_budget"],
    )
    return session_id, trace_id, initial
