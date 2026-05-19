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

    assert breakdowns["technical_depth"] == {
        "scored_turn_count": 2,
        "latest_score": 8.0,
        "best_score": 9.0,
        "average_score": 8.5,
        "adopted_score": 8.7,
        "scoring_policy": "weighted_recent",
    }
