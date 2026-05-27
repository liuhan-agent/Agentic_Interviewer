"""Conditional-edge routers for the interview workflow.

These are *not* nodes; they never mutate state. They read the current
state and return the next edge label. Keeping them in their own module
makes the graph topology easy to reason about (the ACO "node vs
condition function" split).
"""
from __future__ import annotations

from typing import Any, Literal, cast

from app.core.logging import get_logger
from app.engine.resume_plan import has_available_resume_anchor_slot
from app.engine.workflow.eval_helpers import is_evaluator_fallback
from app.engine.workflow.state import InterviewState

log = get_logger(__name__)

AfterEval = Literal["refine", "next_question", "end"]
AfterSkip = Literal["next_question", "end"]
AfterWait = Literal["self_intro_parse", "skip_question", "evaluator", "end"]

DEFAULT_MAX_REFINES_PER_DIMENSION = 2

_AFTER_EVAL_NEXT_NODE: dict[AfterEval, str] = {
    "refine": "refine_followup",
    "next_question": "director_sample",
    "end": "final_report",
}


def _all_dims_done(state: InterviewState) -> bool:
    status = state.get("dimension_status", {})
    dims = state.get("dimensions", [])
    if not dims:
        return True
    return all(status.get(d) == "passed" for d in dims)


def _has_anchor_expansion_slot(state: InterviewState) -> bool:
    rc = state.get("runtime_config") or {}
    depth = str(rc.get("interview_depth") or "standard")
    if depth not in {"standard", "deep"}:
        return False
    return has_available_resume_anchor_slot(
        candidate=state.get("candidate", {}) or {},
        job_spec=state.get("job_spec", {}) or {},
        qa_history=list(state.get("qa_history") or []),
        interview_depth=depth,
        focus_dimensions=list(state.get("focus_dimensions") or []),
        self_intro_profile=state.get("self_intro_profile") or {},
    )


def _max_refines_per_dimension(state: InterviewState) -> int:
    rc = state.get("runtime_config") or {}
    try:
        configured = int(rc.get(
            "max_refines_per_dimension",
            DEFAULT_MAX_REFINES_PER_DIMENSION,
        ))
    except (TypeError, ValueError):
        configured = DEFAULT_MAX_REFINES_PER_DIMENSION
    return max(1, configured)


def _attempts_for_dimension(state: InterviewState, dimension: str) -> int:
    """Count *real* attempts at ``dimension`` (audit finding F4).

    Fallback turns are deliberately excluded: they happen during LLM
    outages and do not represent the candidate genuinely struggling
    on the dim. Counting them would let two flaky LLM calls trip
    coverage advance and force a switch away from a dim the
    interviewer never really probed.
    """
    return sum(
        1
        for qa in state.get("qa_history", [])
        if qa.get("dimension") == dimension
        and not is_evaluator_fallback(qa.get("evaluation") or {})
    )


def _has_pending_other_dimension(state: InterviewState, current_dim: str) -> bool:
    status = state.get("dimension_status", {})
    return any(
        dim != current_dim and status.get(dim) in {None, "pending", "active"}
        for dim in state.get("dimensions", [])
    )


def should_advance_for_coverage(state: InterviewState) -> bool:
    """Return True when another dimension should get the next turn."""
    evaluation = state.get("evaluation", {}) or {}
    if evaluation.get("passed"):
        return False
    current_dim = str(
        state.get("current_dimension")
        or (state.get("current_question") or {}).get("dimension")
        or ""
    )
    if not current_dim or not _has_pending_other_dimension(state, current_dim):
        return False
    return (
        _attempts_for_dimension(state, current_dim)
        >= _max_refines_per_dimension(state)
    )


def _route_after_eval_result(
    *,
    decision: AfterEval,
    decision_reason: str,
    decision_inputs: dict[str, Any],
) -> dict[str, Any]:
    return {
        "decision": decision,
        "next_node": _AFTER_EVAL_NEXT_NODE[decision],
        "decision_reason": decision_reason,
        "decision_inputs": decision_inputs,
    }


def route_after_eval_diagnostics(state: InterviewState) -> dict[str, Any]:
    """Explain the post-evaluation conditional edge without mutating state."""
    evaluation = state.get("evaluation", {}) or {}
    question = state.get("current_question") or {}
    formal_turn_idx = state.get("formal_turn_idx", state.get("turn_idx", 0))
    max_turns = state.get("max_turns", 8)
    budget = state.get("turn_budget_remaining", 0)
    current_dim = str(
        state.get("current_dimension")
        or question.get("dimension")
        or ""
    )
    all_dims_done = _all_dims_done(state)
    has_anchor_expansion_slot = _has_anchor_expansion_slot(state)
    current_dimension_attempts = (
        _attempts_for_dimension(state, current_dim) if current_dim else 0
    )
    max_refines = _max_refines_per_dimension(state)
    has_pending_other = (
        _has_pending_other_dimension(state, current_dim) if current_dim else False
    )
    evaluator_fallback = bool(
        evaluation.get("source") == "fallback"
        or evaluation.get("fallback_reason")
    )
    coverage_advance = bool(
        not evaluation.get("passed")
        and current_dim
        and has_pending_other
        and current_dimension_attempts >= max_refines
    )
    decision_inputs = {
        "formal_turn_idx": formal_turn_idx,
        "max_turns": max_turns,
        "turn_budget_remaining": budget,
        "current_dimension": current_dim or None,
        "recommended_next": evaluation.get("recommended_next"),
        "passed": bool(evaluation.get("passed")),
        "evaluator_fallback": evaluator_fallback,
        "all_dimensions_done": all_dims_done,
        "has_anchor_expansion_slot": has_anchor_expansion_slot,
        "coverage_advance": coverage_advance,
        "current_dimension_attempts": current_dimension_attempts,
        "max_refines_per_dimension": max_refines,
        "has_pending_other_dimension": has_pending_other,
    }

    if state.get("status") == "cancelled":
        return _route_after_eval_result(
            decision="end",
            decision_reason="session_cancelled",
            decision_inputs=decision_inputs,
        )

    if formal_turn_idx >= max_turns:
        return _route_after_eval_result(
            decision="end",
            decision_reason="turn_limit_reached",
            decision_inputs=decision_inputs,
        )
    if budget <= 0:
        return _route_after_eval_result(
            decision="end",
            decision_reason="budget_exhausted",
            decision_inputs=decision_inputs,
        )

    if all_dims_done and not has_anchor_expansion_slot:
        return _route_after_eval_result(
            decision="end",
            decision_reason="all_dimensions_passed",
            decision_inputs=decision_inputs,
        )
    if all_dims_done:
        return _route_after_eval_result(
            decision="next_question",
            decision_reason="anchor_expansion",
            decision_inputs=decision_inputs,
        )

    recommended = evaluation.get("recommended_next")
    if evaluator_fallback:
        return _route_after_eval_result(
            decision="next_question",
            decision_reason="evaluator_fallback",
            decision_inputs=decision_inputs,
        )
    if recommended == "refine" and not evaluation.get("passed"):
        if coverage_advance:
            return _route_after_eval_result(
                decision="next_question",
                decision_reason="coverage_advance",
                decision_inputs=decision_inputs,
            )
        return _route_after_eval_result(
            decision="refine",
            decision_reason="evaluator_recommended_refine",
            decision_inputs=decision_inputs,
        )
    if evaluation.get("passed"):
        return _route_after_eval_result(
            decision="next_question",
            decision_reason="dimension_passed",
            decision_inputs=decision_inputs,
        )
    return _route_after_eval_result(
        decision="refine",
        decision_reason="default_not_passed_refine",
        decision_inputs=decision_inputs,
    )


def route_after_wait(state: InterviewState) -> AfterWait:
    """Cancel short-circuit between ``wait_answer`` and ``evaluator``.

    When the client has torn down the WebSocket (or posted an
    explicit cancel) the ``wait_answer`` node returns with
    ``status=cancelled``. We don't want the evaluator to score an
    empty/placeholder answer and certainly don't want to update the
    bandit with that signal, so we skip ``evaluator`` entirely and
    go straight to ``final_report`` with whatever partial state we
    have.
    """
    if state.get("status") == "cancelled":
        log.info("route_after_wait: end (session cancelled)")
        return "end"
    if state.get("current_answer_intent") == "skipped":
        log.info("route_after_wait: skip_question")
        return "skip_question"
    question = state.get("current_question") or {}
    if question.get("question_type") == "self_intro":
        return "self_intro_parse"
    return "evaluator"


def route_after_skip(state: InterviewState) -> AfterSkip:
    formal_turn_idx = state.get("formal_turn_idx", state.get("turn_idx", 0))
    max_turns = state.get("max_turns", 8)
    budget = state.get("turn_budget_remaining", 0)
    if formal_turn_idx >= max_turns or budget <= 0:
        log.info(
            "router: end after skip (formal_turn=%d/%d, budget=%d)",
            formal_turn_idx,
            max_turns,
            budget,
        )
        return "end"
    if _all_dims_done(state) and not _has_anchor_expansion_slot(state):
        log.info("router: end after skip (all dims passed)")
        return "end"
    if _all_dims_done(state):
        log.info("router: next_question after skip (anchor expansion)")
        return "next_question"
    return "next_question"


def route_after_eval(state: InterviewState) -> AfterEval:
    """Decide what happens after the evaluator has scored an answer.

    - ``refine``   : same dimension, not passed, still has budget
    - ``next_question`` : move on to the next dimension (or repeat
      elsewhere) via director sampling
    - ``end`` : budget exhausted, max turns reached, all dimensions
      passed, or the session was cancelled.
    """
    diagnostics = route_after_eval_diagnostics(state)
    decision = cast(AfterEval, diagnostics["decision"])
    log.info(
        "router: %s (%s)",
        decision,
        diagnostics.get("decision_reason") or "unknown",
    )
    return decision
