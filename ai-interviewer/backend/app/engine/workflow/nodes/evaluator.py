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
from app.engine.workflow.evaluation_consistency import (
    normalize_evaluation_consistency,
    sync_dimension_status,
)
from app.engine.workflow.followup_reason import attach_replay_followup_reason
from app.engine.workflow.replay_basis import sanitize_replay_question_basis
from app.engine.workflow.score_aggregation import (
    build_score_breakdowns_from_qa,
    finite_score,
    legacy_score_breakdown,
    update_score_breakdown,
)
from app.engine.workflow.state import InterviewState, QATurn
from app.ml.drift.prompt_feedback import build_evaluator_drift_negatives
from app.ml.rl.reward_fn import immediate_reward
from app.ml.rl.thompson import get_bandit  # noqa: F401 - legacy tests patch this name

from .wait_answer import get_raw_answer_for_state

log = get_logger(__name__)


def _has_scored_evaluator_turn(
    qa_history: list[dict[str, Any]],
    dimension: str,
) -> bool:
    for qa in qa_history:
        if qa.get("dimension") != dimension:
            continue
        evaluation = qa.get("evaluation") or {}
        if evaluation.get("skipped") or qa.get("answer_intent") == "skipped":
            continue
        if is_evaluator_fallback(evaluation):
            continue
        raw_score = evaluation.get("score")
        if raw_score is None or isinstance(raw_score, bool):
            continue
        try:
            float(raw_score)
        except (TypeError, ValueError):
            continue
        return True
    return False


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

    quality_threshold = state.get("quality_threshold", 7.5)
    evaluation = evaluate_answer(
        dimension=dimension,
        question=question.get("question", ""),
        rubric_points=question.get("rubric_points", []),
        answer=raw_answer,
        quality_threshold=quality_threshold,
        contract=contract,
        drift_negatives=drift_negatives,
        video_signals=state.get("video_signals"),
        context_flags=state.get("context_flags") or {},
    )
    evaluation = normalize_evaluation_consistency(
        evaluation,
        contract=contract,
        quality_threshold=float(quality_threshold),
    )
    evaluation = attach_replay_followup_reason(evaluation)
    fallback_turn = is_evaluator_fallback(evaluation)
    if fallback_turn:
        record_question_fallback("evaluator_fallback")
    scores = dict(state.get("scores_per_dim", {}))
    score_breakdowns = dict(state.get("score_breakdowns") or {})
    score_breakdowns_changed = False
    if dimension not in score_breakdowns:
        score_breakdowns.update(
            build_score_breakdowns_from_qa(list(state.get("qa_history") or []))
        )
    if not fallback_turn:
        # Fallback evaluations come from the conservative path when the
        # LLM was unavailable — folding their score into the running
        # dim average would let LLM hiccups silently drag a strong
        # candidate's reported score down (audit finding F3). Keep the
        # dim score unchanged on fallback turns; the bandit is also
        # already protected by ``reward_update`` skipping fallbacks.
        existing_score = finite_score(scores.get(dimension))
        has_prior_turn = _has_scored_evaluator_turn(
            state.get("qa_history", []),
            dimension,
        )
        if existing_score == 0.0 and not has_prior_turn:
            existing_score = None
        existing_breakdown = score_breakdowns.get(dimension)
        if existing_breakdown is None and existing_score is not None:
            existing_breakdown = legacy_score_breakdown(existing_score)
        new_score = finite_score(evaluation.get("score"))
        if new_score is not None:
            next_breakdown = update_score_breakdown(existing_breakdown, new_score)
            score_breakdowns[dimension] = next_breakdown
            scores[dimension] = next_breakdown["adopted_score"]
            score_breakdowns_changed = True

    status = sync_dimension_status(
        dict(state.get("dimension_status", {})),
        dimension,
        evaluation,
    )

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
        # Classification produced upstream by ``wait_answer_node``;
        # persisting it on the turn record means the final report,
        # replay, and any downstream training pipeline can explain why
        # a turn was scored the way it was without re-running the
        # classifier.
        "answer_intent": state.get("current_answer_intent") or "normal",
    }
    question_basis = sanitize_replay_question_basis(question.get("question_basis"))
    if question_basis is not None:
        qa_turn["question_basis"] = question_basis
    video_signals = state.get("video_signals")
    if isinstance(video_signals, dict) and video_signals:
        qa_turn["video_signals"] = video_signals

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
    if score_breakdowns_changed:
        updated_state["score_breakdowns"] = score_breakdowns

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
