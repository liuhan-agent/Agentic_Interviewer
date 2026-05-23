"""Helpers for dimension coverage and multi-turn score aggregation."""
from __future__ import annotations

import math
from typing import Any, Literal

from app.engine.workflow.eval_helpers import is_evaluator_fallback

SCORING_POLICY: Literal["weighted_recent"] = "weighted_recent"
ANCHOR_SCORING_POLICY: Literal["anchor_weighted_recent"] = "anchor_weighted_recent"
UNANCHORED_LABEL = "\u672a\u5173\u8054\u7b80\u5386\u951a\u70b9"


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


def _anchor_key_for_turn(qa: dict[str, Any], dimension: str) -> str:
    anchor = qa.get("resume_anchor") if isinstance(qa.get("resume_anchor"), dict) else {}
    key = str(anchor.get("anchor_key") or qa.get("resume_anchor_key") or "").strip()
    return key or f"unanchored:{dimension}"


def _anchor_label_for_turn(qa: dict[str, Any]) -> str:
    anchor = qa.get("resume_anchor") if isinstance(qa.get("resume_anchor"), dict) else {}
    label = str(
        anchor.get("label")
        or anchor.get("project_name")
        or qa.get("resume_anchor_label")
        or ""
    ).strip()
    return label or UNANCHORED_LABEL


def _anchor_project_id_for_turn(qa: dict[str, Any]) -> str | None:
    anchor = qa.get("resume_anchor") if isinstance(qa.get("resume_anchor"), dict) else {}
    project_id = str(
        anchor.get("project_id") or qa.get("resume_project_id") or ""
    ).strip()
    return project_id or None


def _turn_idx_for_breakdown(qa: dict[str, Any]) -> int | None:
    value = qa.get("turn_idx")
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _anchor_aware_dimension_breakdown(
    anchors: list[dict[str, Any]],
    *,
    latest_score: float,
) -> dict[str, Any]:
    anchor_scores = [
        score
        for anchor in anchors
        if (score := finite_score(anchor.get("adopted_score"))) is not None
    ]
    turn_best_scores = [
        score
        for anchor in anchors
        if (score := finite_score(anchor.get("best_score"))) is not None
    ]
    total_turns = sum(int(anchor.get("scored_turn_count") or 0) for anchor in anchors)
    anchor_average = round(sum(anchor_scores) / len(anchor_scores), 3)
    best_anchor = max(anchor_scores)
    adopted = (
        anchor_scores[0]
        if len(anchor_scores) == 1
        else round((0.8 * anchor_average) + (0.2 * best_anchor), 3)
    )
    return {
        "scored_turn_count": total_turns,
        "latest_score": latest_score,
        "best_score": max(turn_best_scores or anchor_scores),
        "average_score": anchor_average,
        "adopted_score": adopted,
        "scoring_policy": ANCHOR_SCORING_POLICY,
        "anchor_count": len(anchors),
        "anchor_average_score": anchor_average,
        "best_anchor_score": best_anchor,
        "anchor_breakdowns": anchors,
    }


def build_score_breakdowns_from_qa(
    qa_history: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    anchors_by_dim: dict[str, dict[str, dict[str, Any]]] = {}
    latest_scores: dict[str, float] = {}
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
        anchor_key = _anchor_key_for_turn(qa, dim)
        dim_anchors = anchors_by_dim.setdefault(dim, {})
        anchor_bucket = dim_anchors.setdefault(
            anchor_key,
            {
                "anchor_key": anchor_key,
                "anchor_label": _anchor_label_for_turn(qa),
                "resume_project_id": _anchor_project_id_for_turn(qa),
                "turn_indices": [],
                "breakdown": None,
            },
        )
        turn_idx = _turn_idx_for_breakdown(qa)
        if turn_idx is not None:
            anchor_bucket["turn_indices"].append(turn_idx)
        anchor_bucket["breakdown"] = update_score_breakdown(
            anchor_bucket.get("breakdown"),
            score,
        )
        latest_scores[dim] = score

    breakdowns: dict[str, dict[str, Any]] = {}
    for dim, dim_anchors in anchors_by_dim.items():
        anchors: list[dict[str, Any]] = []
        for bucket in dim_anchors.values():
            anchor_breakdown = dict(bucket.get("breakdown") or {})
            anchor_breakdown.update(
                {
                    "anchor_key": bucket["anchor_key"],
                    "anchor_label": bucket["anchor_label"],
                    "resume_project_id": bucket["resume_project_id"],
                    "turn_indices": list(bucket["turn_indices"]),
                }
            )
            anchors.append(anchor_breakdown)
        latest_score = latest_scores.get(dim)
        if latest_score is None or not anchors:
            continue
        breakdowns[dim] = _anchor_aware_dimension_breakdown(
            anchors,
            latest_score=latest_score,
        )
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
