"""Conditional-edge routers for the interview workflow.

These are *not* nodes; they never mutate state. They read the current
state and return the next edge label. Keeping them in their own module
makes the graph topology easy to reason about (the ACO "node vs
condition function" split).
"""
from __future__ import annotations

from typing import Literal

from app.core.logging import get_logger
from app.engine.workflow.eval_helpers import is_evaluator_fallback
from app.engine.workflow.state import InterviewState

log = get_logger(__name__)

AfterEval = Literal["refine", "next_question", "end"]
AfterSkip = Literal["next_question", "end"]
AfterWait = Literal["self_intro_parse", "skip_question", "evaluator", "end"]

DEFAULT_MAX_REFINES_PER_DIMENSION = 2


def _all_dims_done(state: InterviewState) -> bool:
    status = state.get("dimension_status", {})
    dims = state.get("dimensions", [])
    if not dims:
        return True
    return all(status.get(d) == "passed" for d in dims)


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
    if _all_dims_done(state):
        log.info("router: end after skip (all dims passed)")
        return "end"
    return "next_question"


def route_after_eval(state: InterviewState) -> AfterEval:
    """Decide what happens after the evaluator has scored an answer.

    - ``refine``   : same dimension, not passed, still has budget
    - ``next_question`` : move on to the next dimension (or repeat
      elsewhere) via director sampling
    - ``end`` : budget exhausted, max turns reached, all dimensions
      passed, or the session was cancelled.
    """
    if state.get("status") == "cancelled":
        log.info("router: end (session cancelled by client)")
        return "end"

    evaluation = state.get("evaluation", {})
    formal_turn_idx = state.get("formal_turn_idx", state.get("turn_idx", 0))
    max_turns = state.get("max_turns", 8)
    budget = state.get("turn_budget_remaining", 0)

    if formal_turn_idx >= max_turns or budget <= 0:
        log.info(
            "router: end (budget exhausted: formal_turn=%d/%d, budget=%d)",
            formal_turn_idx,
            max_turns,
            budget,
        )
        return "end"

    if _all_dims_done(state):
        log.info("router: end (all dims passed)")
        return "end"

    recommended = evaluation.get("recommended_next")
    if evaluation.get("source") == "fallback" or evaluation.get("fallback_reason"):
        log.info("router: next_question (evaluator fallback)")
        return "next_question"
    if recommended == "refine" and not evaluation.get("passed"):
        if should_advance_for_coverage(state):
            log.info("router: next_question (refine cap reached)")
            return "next_question"
        log.info("router: refine (evaluator recommended)")
        return "refine"
    if evaluation.get("passed"):
        log.info("router: next_question (dim passed)")
        return "next_question"
    log.info("router: refine (default, not passed)")
    return "refine"
