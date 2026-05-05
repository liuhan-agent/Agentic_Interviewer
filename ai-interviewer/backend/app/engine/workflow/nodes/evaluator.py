"""Evaluator node: score the latest answer and fold the result into state."""
from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any

from app.core.logging import get_logger
from app.core.metrics import record_question_fallback
from app.core.settings import get_settings
from app.core.tracer import get_tracer
from app.engine.agents.evaluator_agent import evaluate_answer
from app.engine.workflow.eval_helpers import is_evaluator_fallback
from app.engine.workflow.state import InterviewState, QATurn
from app.ml.drift.prompt_feedback import build_evaluator_drift_negatives
from app.ml.rl.reward_fn import immediate_reward
from app.ml.rl.thompson import get_bandit  # noqa: F401 - legacy tests patch this name

from .wait_answer import get_raw_answer_for_state

log = get_logger(__name__)


def _merge_score(existing: float, new_score: float) -> float:
    """Running average so repeated attempts at the same dim converge.

    For the first sample we simply take ``new_score``; subsequently we
    take a 70/30 blend favouring history, which prevents a single bad
    refine round from sinking a dimension that was otherwise strong.
    """
    if existing <= 0.0:
        return new_score
    return round(0.7 * existing + 0.3 * new_score, 3)


def evaluator_node(state: InterviewState) -> dict[str, Any]:
    node_started_at = time.perf_counter()
    question = state.get("current_question") or {}
    sanitised_answer = state.get("current_answer", "")
    # Scoring uses the raw text when the wait-answer side-channel still
    # has it; every downstream persistence gets the sanitised copy.
    raw_answer = get_raw_answer_for_state(state) or sanitised_answer
    dimension = question.get("dimension") or state.get("current_dimension") or "unknown"

    # Prefer the signed contract from state; fall back to the copy
    # embedded in current_question (set by ``ask_question_node``); fall
    # back again to ``None`` so evaluator_agent degrades to the legacy
    # rubric_points path.
    contract = state.get("current_contract") or question.get("contract")

    # PLAN_DRIFT_FEEDBACK Step 4: optionally splice a Markdown block
    # of "prior evaluator drift" negative examples into the Evaluator's
    # dynamic_system slot. Defaults to empty (feature flag OFF) so
    # byte-equivalence with Phase 1 is preserved for every existing
    # deployment. Exceptions in the feedback pipeline degrade silently
    # — evaluator grading is a hot path and must never fail because of
    # an observability helper.
    settings = get_settings()
    drift_negatives = ""
    if settings.enable_evaluator_prompt_feedback:
        try:
            drift_negatives = build_evaluator_drift_negatives(
                dimension=dimension,
                top_n=settings.drift_feedback_top_n,
                min_support=settings.drift_feedback_min_support,
            )
        except Exception as e:  # pragma: no cover - feedback is non-critical
            log.debug("drift feedback render failed: %s", e)

    evaluation = evaluate_answer(
        dimension=dimension,
        question=question.get("question", ""),
        rubric_points=question.get("rubric_points", []),
        answer=raw_answer,
        quality_threshold=state.get("quality_threshold", 7.5),
        contract=contract,
        drift_negatives=drift_negatives,
        video_signals=state.get("video_signals"),
        context_flags=state.get("context_flags") or {},
    )
    fallback_turn = is_evaluator_fallback(evaluation)
    if fallback_turn:
        record_question_fallback("evaluator_fallback")
    scores = dict(state.get("scores_per_dim", {}))
    if not fallback_turn:
        # Fallback evaluations come from the conservative path when the
        # LLM was unavailable — folding their score into the running
        # dim average would let LLM hiccups silently drag a strong
        # candidate's reported score down (audit finding F3). Keep the
        # dim score unchanged on fallback turns; the bandit is also
        # already protected by ``reward_update`` skipping fallbacks.
        scores[dimension] = _merge_score(
            scores.get(dimension, 0.0),
            float(evaluation.get("score", 0.0)),
        )

    status = dict(state.get("dimension_status", {}))
    if fallback_turn:
        # Same rationale: a fallback turn does not produce reliable
        # signal, so it should neither promote a dim to ``passed`` nor
        # demote a previously-passed dim back to ``active``.
        pass
    elif evaluation.get("passed"):
        status[dimension] = "passed"
    elif status.get(dimension) != "passed":
        status[dimension] = "active"

    turn_idx = state.get("turn_idx", 0)
    formal_turn_idx = state.get("formal_turn_idx", turn_idx)
    qa_turn: QATurn = {
        "turn_idx": formal_turn_idx,
        "dimension": dimension,
        "question": question.get("question", ""),
        "resume_anchor": question.get("resume_anchor") or {},
        "target_skills": question.get("target_skills") or [],
        "skill_focus": question.get("skill_focus") or {},
        # qa_history lives in the checkpoint + flows into traces, so
        # we persist the sanitised copy. The raw text was only used
        # transiently above for scoring.
        "answer": sanitised_answer,
        "selected_action": (state.get("selected_action") or {}).get("id", ""),
        "evaluation": evaluation,
        "timestamp": datetime.now(UTC).isoformat(),
    }

    turn_budget = max(0, state.get("turn_budget_remaining", 0) - 1)

    # Contract-hygiene penalties engage when we pass the current
    # contract so arms that skipped negotiation or let most acceptance
    # checks flunk accumulate a smaller posterior mass.  For turns
    # without a contract (legacy rubric_points path), the penalty
    # branch no-ops.
    preview_reward = immediate_reward(evaluation=evaluation, contract=contract)

    log.info(
        "evaluator turn=%d dim=%s score=%.2f passed=%s preview_reward=%.2f budget_left=%d",
        turn_idx,
        dimension,
        evaluation.get("score", 0),
        evaluation.get("passed"),
        preview_reward,
        turn_budget,
    )

    # NOTE: we intentionally do NOT clear the raw-answer side-channel here.
    # The verification node runs right after the evaluator and needs
    # the same unredacted text we scored on; clearing mid-chain would
    # force the verifier to judge sanitised text and silently diverge
    # from the evaluator. ``compress_context_node`` (the next node
    # downstream of verification) owns the clear instead, so the raw
    # channel survives exactly the ``wait_answer -> evaluator ->
    # verification`` span that needs it and no longer.
    updated_state: dict[str, Any] = {
        "evaluation": evaluation,
        "scores_per_dim": scores,
        "dimension_status": status,
        "qa_history": [qa_turn],
        "turn_idx": turn_idx + 1,
        "formal_turn_idx": formal_turn_idx + 1,
        "turn_budget_remaining": turn_budget,
    }

    # Tracer is side-channel: write trace from a consolidated view of the
    # state so downstream joins don't have to guess which turn we mean.
    # Reward is applied by ``reward_update_node`` after verification has
    # had a chance to amend the evaluator verdict. Keep this evaluator
    # trace as observation-only so rehydrate does not replay a
    # pre-verification reward.
    trace_view = dict(state)
    trace_view.update(updated_state)
    try:
        get_tracer().trace_evaluator(
            trace_view,
            immediate_reward=preview_reward,
            immediate_reward_applied=False,
            node_elapsed_ms=int((time.perf_counter() - node_started_at) * 1000),
        )
    except Exception as e:  # pragma: no cover
        log.warning("tracer side-channel failed: %s", e)

    return updated_state
