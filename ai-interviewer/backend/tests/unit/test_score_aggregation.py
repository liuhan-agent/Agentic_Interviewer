from __future__ import annotations

from app.engine.workflow.score_aggregation import (
    build_score_breakdowns_from_qa,
    is_valid_scored_evaluation,
    update_score_breakdown,
)


def test_weighted_recent_breakdown_tracks_latest_best_average_and_adopted() -> None:
    breakdown = None
    for score in [9.0, 9.0, 9.0, 9.0, 8.0]:
        breakdown = update_score_breakdown(breakdown, score)

    assert breakdown == {
        "scored_turn_count": 5,
        "latest_score": 8.0,
        "best_score": 9.0,
        "average_score": 8.8,
        "adopted_score": 8.7,
        "scoring_policy": "weighted_recent",
    }


def test_real_zero_score_is_valid_and_counted() -> None:
    breakdown = update_score_breakdown(None, 0.0)

    assert breakdown["scored_turn_count"] == 1
    assert breakdown["latest_score"] == 0.0
    assert breakdown["best_score"] == 0.0
    assert breakdown["average_score"] == 0.0
    assert breakdown["adopted_score"] == 0.0
    assert is_valid_scored_evaluation({"score": 0.0}) is True


def test_fallback_skipped_and_missing_scores_are_not_valid_scored_evaluations() -> None:
    assert is_valid_scored_evaluation({"score": 5.0, "source": "fallback"}) is False
    assert is_valid_scored_evaluation({"score": 5.0, "skipped": True}) is False
    assert is_valid_scored_evaluation({"score": None}) is False
    assert is_valid_scored_evaluation({"score": True}) is False


def test_build_score_breakdowns_from_qa_ignores_fallback_turns() -> None:
    qa_history = [
        {"dimension": "technical_depth", "evaluation": {"score": 9.0}},
        {
            "dimension": "technical_depth",
            "evaluation": {"score": 3.0, "source": "fallback"},
        },
        {"dimension": "technical_depth", "evaluation": {"score": 8.0}},
    ]

    breakdowns = build_score_breakdowns_from_qa(qa_history)

    breakdown = breakdowns["technical_depth"]
    assert breakdown["scored_turn_count"] == 2
    assert breakdown["latest_score"] == 8.0
    assert breakdown["best_score"] == 9.0
    assert breakdown["average_score"] == 8.7
    assert breakdown["adopted_score"] == 8.7
    assert breakdown["scoring_policy"] == "anchor_weighted_recent"
    assert breakdown["anchor_count"] == 1
    assert breakdown["anchor_breakdowns"][0]["anchor_key"] == "unanchored:technical_depth"


def test_anchor_aware_breakdown_keeps_same_anchor_weighted_recent() -> None:
    qa_history = [
        {
            "turn_idx": 0,
            "dimension": "technical_depth",
            "resume_anchor": {
                "anchor_key": "focus-a",
                "label": "Payment consistency",
                "project_id": "proj-pay",
            },
            "evaluation": {"score": 8.0},
        },
        {
            "turn_idx": 1,
            "dimension": "technical_depth",
            "resume_anchor": {
                "anchor_key": "focus-a",
                "label": "Payment consistency",
                "project_id": "proj-pay",
            },
            "evaluation": {"score": 9.0},
        },
    ]

    breakdowns = build_score_breakdowns_from_qa(qa_history)
    breakdown = breakdowns["technical_depth"]

    assert breakdown["adopted_score"] == 8.3
    assert breakdown["anchor_count"] == 1
    assert breakdown["scoring_policy"] == "anchor_weighted_recent"
    assert breakdown["anchor_breakdowns"][0]["adopted_score"] == 8.3
    assert breakdown["anchor_breakdowns"][0]["scoring_policy"] == "weighted_recent"
    assert breakdown["anchor_breakdowns"][0]["turn_indices"] == [0, 1]


def test_anchor_aware_breakdown_aggregates_multiple_resume_anchors() -> None:
    qa_history = [
        {
            "turn_idx": 0,
            "dimension": "technical_depth",
            "resume_anchor": {
                "anchor_key": "focus-a",
                "label": "Payment consistency",
                "project_id": "proj-pay",
            },
            "evaluation": {"score": 8.0},
        },
        {
            "turn_idx": 1,
            "dimension": "technical_depth",
            "resume_anchor": {
                "anchor_key": "focus-a",
                "label": "Payment consistency",
                "project_id": "proj-pay",
            },
            "evaluation": {"score": 9.0},
        },
        {
            "turn_idx": 2,
            "dimension": "technical_depth",
            "resume_anchor": {
                "anchor_key": "focus-b",
                "label": "Cache failover",
                "project_id": "proj-cache",
            },
            "evaluation": {"score": 7.0},
        },
    ]

    breakdowns = build_score_breakdowns_from_qa(qa_history)
    breakdown = breakdowns["technical_depth"]

    assert breakdown["adopted_score"] == 7.78
    assert breakdown["anchor_average_score"] == 7.65
    assert breakdown["best_anchor_score"] == 8.3
    assert breakdown["anchor_count"] == 2
    assert [a["anchor_key"] for a in breakdown["anchor_breakdowns"]] == [
        "focus-a",
        "focus-b",
    ]


def test_anchor_aware_breakdown_groups_unanchored_turns_by_dimension() -> None:
    qa_history = [
        {
            "turn_idx": 3,
            "dimension": "coding_quality",
            "evaluation": {"score": 7.5},
        }
    ]

    breakdowns = build_score_breakdowns_from_qa(qa_history)
    anchor = breakdowns["coding_quality"]["anchor_breakdowns"][0]

    assert anchor["anchor_key"] == "unanchored:coding_quality"
    assert anchor["anchor_label"] == "\u672a\u5173\u8054\u7b80\u5386\u951a\u70b9"
