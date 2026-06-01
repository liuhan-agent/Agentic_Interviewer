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
from app.engine.workflow.depth_followup import (
    DEPTH_FOLLOWUP_PHASE,
    preserve_depth_followup_dimension_status,
    sanitize_depth_followup_metadata,
)
from app.engine.workflow.eval_helpers import is_evaluator_fallback
from app.engine.workflow.evaluation_consistency import (
    normalize_evaluation_consistency,
    sync_dimension_status,
)
from app.engine.workflow.followup_reason import attach_replay_followup_reason
from app.engine.workflow.replay_basis import sanitize_replay_question_basis
from app.engine.workflow.score_aggregation import build_score_breakdowns_from_qa
from app.engine.workflow.state import InterviewState, QATurn
from app.ml.drift.prompt_feedback import build_evaluator_drift_negatives
from app.ml.rl.reward_fn import immediate_reward
from app.ml.rl.thompson import get_bandit  # noqa: F401 - legacy tests patch this name
from app.models import get_session
from app.services.question_selector import build_question_history_selection_artifacts
from app.services.strategy_learning_facts import upsert_interview_turn

from .wait_answer import get_raw_answer_for_state

log = get_logger(__name__)


def _failure_categories_for_drift_feedback(
    state: InterviewState,
    question: dict[str, Any],
) -> list[str]:
    artifacts = question.get("selection_artifacts") or {}
    raw = None
    if isinstance(artifacts, dict):
        raw = artifacts.get("failure_categories")
    if not raw:
        raw = (state.get("evaluation") or {}).get("failure_categories")
    if not isinstance(raw, list):
        return []
    return [str(value) for value in raw if isinstance(value, str) and value.strip()]


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
                failure_categories=_failure_categories_for_drift_feedback(
                    state,
                    question,
                ),
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

    status = sync_dimension_status(
        dict(state.get("dimension_status", {})),
        dimension,
        evaluation,
    )
    status = preserve_depth_followup_dimension_status(
        state=state,
        status=status,
        dimension=str(dimension),
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
        # The pending QA turn later lands in qa_history, so persist the
        # sanitised copy. The raw text was only used transiently above
        # for scoring.
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
    depth_followup = sanitize_depth_followup_metadata(question.get("depth_followup"))
    if question.get("phase") == DEPTH_FOLLOWUP_PHASE or depth_followup:
        qa_turn["phase"] = DEPTH_FOLLOWUP_PHASE
        if depth_followup:
            qa_turn["depth_followup"] = depth_followup
    question_basis = sanitize_replay_question_basis(question.get("question_basis"))
    if question_basis is not None:
        qa_turn["question_basis"] = question_basis
    history_selection_artifacts = build_question_history_selection_artifacts(question)
    if history_selection_artifacts:
        qa_turn["selection_artifacts"] = history_selection_artifacts
    video_signals = state.get("video_signals")
    if isinstance(video_signals, dict) and video_signals:
        qa_turn["video_signals"] = video_signals

    if not fallback_turn:
        rebuilt_breakdowns = build_score_breakdowns_from_qa(
            list(state.get("qa_history") or []) + [qa_turn]
        )
        next_breakdown = rebuilt_breakdowns.get(dimension)
        if next_breakdown is not None:
            score_breakdowns[dimension] = next_breakdown
            scores[dimension] = next_breakdown["adopted_score"]
            score_breakdowns_changed = True

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
    # from the evaluator. ``turn_finalize_node`` (the next node
    # downstream of verification) owns the clear instead, so the raw
    # channel survives exactly the ``wait_answer -> evaluator ->
    # verification`` span that needs it and no longer.
    updated_state: dict[str, Any] = {
        "evaluation": evaluation,
        "scores_per_dim": scores,
        "dimension_status": status,
        "pending_qa_turn": qa_turn,
        "turn_idx": turn_idx + 1,
        "formal_turn_idx": formal_turn_idx + 1,
        "turn_budget_remaining": turn_budget,
    }
    if score_breakdowns_changed:
        updated_state["score_breakdowns"] = score_breakdowns

    _persist_interview_turn_fact(
        state=state,
        question=question,
        qa_turn=qa_turn,
        turn_idx=formal_turn_idx,
        preview_reward=preview_reward,
    )

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


def _persist_interview_turn_fact(
    *,
    state: InterviewState,
    question: dict[str, Any],
    qa_turn: QATurn,
    turn_idx: int,
    preview_reward: float,
) -> None:
    try:
        action = state.get("selected_action") or {}
        policy_context_keys = (
            state.get("policy_context_keys")
            or action.get("policy_context_keys")
            or []
        )
        evaluation = qa_turn.get("evaluation") or {}
        with get_session() as session:
            upsert_interview_turn(
                session,
                session_id=str(state.get("session_id") or ""),
                turn_idx=int(turn_idx),
                trace_id=_optional_str(state.get("trace_id")),
                dimension=str(qa_turn.get("dimension") or "unknown"),
                job_level=_optional_str((state.get("job_spec") or {}).get("level")),
                question=str(qa_turn.get("question") or ""),
                answer=str(qa_turn.get("answer") or ""),
                **_resume_anchor_fact_fields(question),
                selected_action=_optional_str(qa_turn.get("selected_action")),
                policy_context_keys=[
                    str(key) for key in policy_context_keys if str(key or "").strip()
                ],
                selection_artifacts=dict(qa_turn.get("selection_artifacts") or {}),
                evaluation=dict(evaluation),
                failure_categories=_failure_categories(evaluation),
                score=_optional_float(evaluation.get("score")),
                passed=_optional_bool(evaluation.get("passed")),
                immediate_reward=None,
            )
    except Exception as e:  # pragma: no cover - fact persistence is side-channel
        log.warning(
            "interview turn fact persistence failed preview_reward=%.2f: %s",
            preview_reward,
            e,
        )


def _failure_categories(evaluation: dict[str, Any]) -> list[str]:
    raw = evaluation.get("failure_categories")
    if not isinstance(raw, list):
        return []
    return [str(value) for value in raw if isinstance(value, str) and value.strip()]


def _resume_anchor_fact_fields(question: dict[str, Any]) -> dict[str, str | None]:
    anchor = question.get("resume_anchor")
    if not isinstance(anchor, dict):
        anchor = {}
    label = anchor.get("label") or anchor.get("project_name")
    return {
        "resume_anchor_key": _optional_str(anchor.get("anchor_key")),
        "resume_anchor_label": _optional_str(label),
        "resume_project_id": _optional_str(anchor.get("project_id")),
    }


def _optional_str(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _optional_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _optional_bool(value: Any) -> bool | None:
    if value is None:
        return None
    return bool(value)
