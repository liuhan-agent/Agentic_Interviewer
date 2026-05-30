"""Turn-finalize node between reward update and route decision.

The workflow node name remains ``compress_context`` for compatibility,
but it no longer compresses QA history or calls a summariser in the
hot path. Its ownership is deliberately narrow: clear the raw-answer
side channel, trace the housekeeping step, then trace route_decision.

Prompt-facing history is now projected by ask_question's
HistoryContextBuilder from the complete ``qa_history`` source.
"""
from __future__ import annotations

import time
from typing import Any

from app.core.logging import get_logger
from app.core.tracer import get_tracer
from app.engine.workflow.routers import route_after_eval_diagnostics
from app.engine.workflow.state import InterviewState
from app.services.trace_nodes import trace_node_metadata

from .wait_answer import clear_raw_answer_for_state

log = get_logger(__name__)


def _clear_raw_answer_if_set(state: InterviewState) -> dict[str, Any]:
    """Return the update that clears ``current_answer_raw``.

    Emitted only when the field is non-empty so the rest of the graph's
    state reducer graph remains a strict superset of the "no change"
    shape. The clear is a single-turn ephemeral contract owned by this
    node: ``wait_answer`` stores raw text in a process-local
    side-channel, evaluator and verifier read it, and
    ``compress_context`` erases both the side-channel ref and any legacy
    raw state before the next ``director_sample``.
    """
    if clear_raw_answer_for_state(state):
        return {"current_answer_raw": "", "current_answer_raw_ref": ""}
    return {}


def _logical_turn_idx(state: InterviewState) -> int:
    try:
        return max(0, int(state.get("turn_idx", 0)) - 1)
    except (TypeError, ValueError):
        return 0


def _trace_compress_context(
    state: InterviewState,
    update: dict[str, Any],
    *,
    node_started_at: float,
) -> None:
    try:
        qa_history = state.get("qa_history", [])
        raw_answer_cleared = "current_answer_raw" in update
        get_tracer().trace_node_event(
            {**state, **update},
            node="compress_context",
            payload={
                **trace_node_metadata("compress_context"),
                "phase": "turn_finalize",
                "reason": "turn_finalize",
                "compressed_turns": 0,
                "raw_answer_cleared": raw_answer_cleared,
                "cleared_raw_answer": raw_answer_cleared,
                "summary_updated": False,
                "summary_mode": "none",
                "history_projection_owner": "ask_question",
                "qa_history_count": len(qa_history),
                "next_step": "route_decision",
                "elapsed_ms": int((time.perf_counter() - node_started_at) * 1000),
            },
            logical_turn_idx=_logical_turn_idx(state),
        )
    except Exception as e:  # pragma: no cover - side channel
        log.warning("compress_context tracer side-channel failed: %s", e)


def _trace_route_decision(state: InterviewState, update: dict[str, Any]) -> None:
    """Record the post-evaluation router decision for rhythm audits."""
    route_state = {**state, **update}
    evaluation = route_state.get("evaluation") or {}
    question = route_state.get("current_question") or {}
    diagnostics = route_after_eval_diagnostics(route_state)
    decision = diagnostics.get("decision")
    try:
        get_tracer().trace_node_event(
            route_state,
            node="route_decision",
            payload={
                "router": "route_after_eval",
                "decision": decision,
                "next_node": diagnostics.get("next_node"),
                "decision_reason": diagnostics.get("decision_reason"),
                "decision_inputs": diagnostics.get("decision_inputs") or {},
                "dimension": (
                    question.get("dimension")
                    or route_state.get("current_dimension")
                    or "unknown"
                ),
                "recommended_next": evaluation.get("recommended_next"),
                "recommended_next_plan": evaluation.get("recommended_next_plan"),
                "recommended_probe_intent": evaluation.get("recommended_probe_intent"),
                "passed": bool(evaluation.get("passed")),
                "evaluation_source": evaluation.get("source"),
                "fallback_reason": evaluation.get("fallback_reason"),
                "fallback": bool(
                    evaluation.get("source") == "fallback"
                    or evaluation.get("fallback_reason")
                ),
                "formal_turn_idx": route_state.get("formal_turn_idx"),
                "max_turns": route_state.get("max_turns"),
                "turn_budget_remaining": route_state.get("turn_budget_remaining"),
            },
            logical_turn_idx=_logical_turn_idx(route_state),
        )
    except Exception as e:  # pragma: no cover - side channel
        log.warning("route_decision tracer side-channel failed: %s", e)


def compress_context_node(state: InterviewState) -> dict[str, Any]:
    node_started_at = time.perf_counter()
    update = _clear_raw_answer_if_set(state)
    _trace_compress_context(
        state,
        update,
        node_started_at=node_started_at,
    )
    _trace_route_decision(state, update)
    return update
