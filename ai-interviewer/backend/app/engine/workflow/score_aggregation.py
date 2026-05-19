"""Helpers for dimension coverage and multi-turn score aggregation."""
from __future__ import annotations

import math
from typing import Any, Literal

from app.engine.workflow.eval_helpers import is_evaluator_fallback

SCORING_POLICY: Literal["weighted_recent"] = "weighted_recent"


def finite_score(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        score = float(value)
    except (TypeError, ValueError):
        return None
    return score if math.isfinite(score) else None


def is_valid_scored_evaluation(
    evaluation: dict[str, Any] | None,
    *,
    answer_intent: str | None = None,
) -> bool:
    evaluation = evaluation or {}
    if answer_intent == "skipped" or evaluation.get("skipped"):
        return False
    if is_evaluator_fallback(evaluation):
        return False
    return finite_score(evaluation.get("score")) is not None


def update_score_breakdown(
    existing: dict[str, Any] | None,
    score: float,
) -> dict[str, Any]:
    score = float(score)
    count = int((existing or {}).get("scored_turn_count") or 0)
    if count <= 0:
        return {
            "scored_turn_count": 1,
            "latest_score": score,
            "best_score": score,
            "average_score": score,
            "adopted_score": score,
            "scoring_policy": SCORING_POLICY,
        }

    prev_avg = finite_score((existing or {}).get("average_score")) or 0.0
    prev_adopted = finite_score((existing or {}).get("adopted_score"))
    if prev_adopted is None:
        prev_adopted = finite_score((existing or {}).get("latest_score")) or score
    prev_best = finite_score((existing or {}).get("best_score"))
    if prev_best is None:
        prev_best = prev_adopted

    next_count = count + 1
    return {
        "scored_turn_count": next_count,
        "latest_score": score,
        "best_score": max(prev_best, score),
        "average_score": round(((prev_avg * count) + score) / next_count, 3),
        "adopted_score": round((0.7 * prev_adopted) + (0.3 * score), 3),
        "scoring_policy": SCORING_POLICY,
    }


def legacy_score_breakdown(score: float) -> dict[str, Any]:
    score = float(score)
    return {
        "scored_turn_count": 1,
        "latest_score": score,
        "best_score": score,
        "average_score": score,
        "adopted_score": score,
        "scoring_policy": SCORING_POLICY,
    }


def build_score_breakdowns_from_qa(
    qa_history: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    breakdowns: dict[str, dict[str, Any]] = {}
    for qa in qa_history:
        dim = str(qa.get("dimension") or "")
        if not dim:
            continue
        evaluation = qa.get("evaluation") or {}
        if not is_valid_scored_evaluation(
            evaluation,
            answer_intent=str(qa.get("answer_intent") or ""),
        ):
            continue
        score = finite_score(evaluation.get("score"))
        if score is None:
            continue
        breakdowns[dim] = update_score_breakdown(breakdowns.get(dim), score)
    return breakdowns


def scored_dimensions_from_state(state: dict[str, Any]) -> set[str]:
    scored: set[str] = set()
    for dim, breakdown in (state.get("score_breakdowns") or {}).items():
        if finite_score((breakdown or {}).get("adopted_score")) is not None:
            scored.add(str(dim))

    for dim, breakdown in build_score_breakdowns_from_qa(
        list(state.get("qa_history") or [])
    ).items():
        if finite_score(breakdown.get("adopted_score")) is not None:
            scored.add(str(dim))

    return scored
