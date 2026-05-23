"""Audit F3 — fallback evaluations don't pollute dim score / status.

When ``evaluator_agent`` returns a conservative fallback (``source ==
"fallback"``), the corresponding ``evaluator_node`` turn must NOT
update ``scores_per_dim`` or upgrade ``dimension_status`` — otherwise
LLM hiccups silently distort a candidate's reported strength.
"""
from __future__ import annotations

from typing import Any

import pytest

from app.engine.workflow.nodes import evaluator as evaluator_node_mod


def _fake_evaluation(*, fallback: bool, score: float = 5.0, passed: bool = False) -> dict[str, Any]:
    base: dict[str, Any] = {
        "score": score,
        "passed": passed,
        "rationale": "x",
        "weaknesses": [],
        "strengths": [],
        "rubric_coverage": {},
        "acceptance_check_results": {},
        "recommended_next": "advance",
    }
    if fallback:
        base["source"] = "fallback"
        base["fallback_reason"] = "llm_failed"
        base["weaknesses"] = ["Evaluator LLM unavailable; using conservative fallback."]
    return base


def _state_with_dim(
    dim: str,
    *,
    prev_score: float | None,
    prev_status: str,
    score_breakdown: dict[str, Any] | None = None,
) -> dict[str, Any]:
    state = {
        "session_id": "sess",
        "trace_id": "trace",
        "current_question": {"dimension": dim, "question": "Q"},
        "current_dimension": dim,
        "current_answer": "A",
        "current_answer_intent": "normal",
        "scores_per_dim": {dim: prev_score},
        "dimension_status": {dim: prev_status},
        "qa_history": [],
        "selected_action": {"id": "plan_simple"},
        "turn_idx": 0,
        "formal_turn_idx": 0,
        "turn_budget_remaining": 5,
        "quality_threshold": 7.5,
    }
    if score_breakdown is not None:
        state["score_breakdowns"] = {dim: score_breakdown}
    return state


def test_fallback_turn_does_not_update_dim_score(monkeypatch: pytest.MonkeyPatch) -> None:
    fb = _fake_evaluation(fallback=True, score=5.0)
    monkeypatch.setattr(
        evaluator_node_mod,
        "evaluate_answer",
        lambda **kwargs: fb,
    )

    state = _state_with_dim("technical_depth", prev_score=8.5, prev_status="active")
    update = evaluator_node_mod.evaluator_node(state)

    # Score should remain 8.5 — not 70/30 weighted with the fallback's 5.0
    assert update["scores_per_dim"]["technical_depth"] == 8.5
    assert "score_breakdowns" not in update


def test_fallback_turn_does_not_promote_dim_to_passed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Even a fallback that claims passed=True should not flip the status
    fb = _fake_evaluation(fallback=True, score=9.0, passed=True)
    monkeypatch.setattr(
        evaluator_node_mod,
        "evaluate_answer",
        lambda **kwargs: fb,
    )

    state = _state_with_dim("communication", prev_score=6.0, prev_status="pending")
    update = evaluator_node_mod.evaluator_node(state)

    assert update["dimension_status"]["communication"] == "pending"


def test_real_evaluation_still_updates_score_and_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real = _fake_evaluation(fallback=False, score=8.0, passed=True)
    monkeypatch.setattr(
        evaluator_node_mod,
        "evaluate_answer",
        lambda **kwargs: real,
    )

    state = _state_with_dim("technical_depth", prev_score=6.0, prev_status="pending")
    update = evaluator_node_mod.evaluator_node(state)

    assert update["scores_per_dim"]["technical_depth"] == 8.0
    breakdown = update["score_breakdowns"]["technical_depth"]
    assert breakdown == {
        "scored_turn_count": 1,
        "latest_score": 8.0,
        "best_score": 8.0,
        "average_score": 8.0,
        "adopted_score": 8.0,
        "scoring_policy": "anchor_weighted_recent",
        "anchor_count": 1,
        "anchor_average_score": 8.0,
        "best_anchor_score": 8.0,
        "anchor_breakdowns": [
            {
                "scored_turn_count": 1,
                "latest_score": 8.0,
                "best_score": 8.0,
                "average_score": 8.0,
                "adopted_score": 8.0,
                "scoring_policy": "weighted_recent",
                "anchor_key": "unanchored:technical_depth",
                "anchor_label": "\u672a\u5173\u8054\u7b80\u5386\u951a\u70b9",
                "resume_project_id": None,
                "turn_indices": [0],
            }
        ],
    }
    assert update["dimension_status"]["technical_depth"] == "passed"


def test_real_evaluation_rebuilds_score_from_qa_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real = _fake_evaluation(fallback=False, score=8.0, passed=False)
    monkeypatch.setattr(evaluator_node_mod, "evaluate_answer", lambda **_: real)

    resume_anchor = {
        "anchor_key": "focus-td",
        "label": "Technical depth anchor",
        "project_id": "proj-td",
    }
    state = _state_with_dim(
        "technical_depth",
        prev_score=5.0,
        prev_status="passed",
        score_breakdown={
            "scored_turn_count": 99,
            "latest_score": 5.0,
            "best_score": 5.0,
            "average_score": 5.0,
            "adopted_score": 5.0,
            "scoring_policy": "weighted_recent",
        },
    )
    state["current_question"]["resume_anchor"] = resume_anchor
    state["turn_idx"] = 4
    state["formal_turn_idx"] = 4
    state["qa_history"] = [
        {
            "turn_idx": idx,
            "dimension": "technical_depth",
            "resume_anchor": resume_anchor,
            "evaluation": {"score": 9.0},
            "answer_intent": "normal",
        }
        for idx in range(4)
    ]

    update = evaluator_node_mod.evaluator_node(state)

    assert update["scores_per_dim"]["technical_depth"] == 8.7
    breakdown = update["score_breakdowns"]["technical_depth"]
    assert breakdown["scored_turn_count"] == 5
    assert breakdown["latest_score"] == 8.0
    assert breakdown["best_score"] == 9.0
    assert breakdown["average_score"] == 8.7
    assert breakdown["adopted_score"] == 8.7
    assert breakdown["scoring_policy"] == "anchor_weighted_recent"
    assert breakdown["anchor_count"] == 1
    assert breakdown["anchor_breakdowns"][0] == {
        "scored_turn_count": 5,
        "latest_score": 8.0,
        "best_score": 9.0,
        "average_score": 8.8,
        "adopted_score": 8.7,
        "scoring_policy": "weighted_recent",
        "anchor_key": "focus-td",
        "anchor_label": "Technical depth anchor",
        "resume_project_id": "proj-td",
        "turn_indices": [0, 1, 2, 3, 4],
    }


def test_real_high_score_with_complete_checks_promotes_status_to_passed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real = _fake_evaluation(fallback=False, score=10.0, passed=False)
    real["acceptance_check_results"] = {
        "Explains rollback.": {"verdict": "yes", "evidence": ["rollback"]},
        "Names trade-off.": {"verdict": "yes", "evidence": ["trade-off"]},
    }
    real["rubric_coverage"] = {
        "Explains rollback.": "covered",
        "Names trade-off.": "covered",
    }
    monkeypatch.setattr(evaluator_node_mod, "evaluate_answer", lambda **_: real)

    state = _state_with_dim("system_design", prev_score=None, prev_status="pending")
    state["current_contract"] = {
        "must_cover": ["Explains rollback.", "Names trade-off."],
        "acceptance_checks": ["Explains rollback.", "Names trade-off."],
    }
    update = evaluator_node_mod.evaluator_node(state)

    assert update["qa_history"][0]["evaluation"]["passed"] is True
    assert update["dimension_status"]["system_design"] == "passed"


def test_real_high_score_with_missing_check_does_not_promote_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real = _fake_evaluation(fallback=False, score=10.0, passed=True)
    real["acceptance_check_results"] = {
        "Explains rollback.": {"verdict": "yes", "evidence": ["rollback"]},
        "Names trade-off.": {"verdict": "no", "evidence": []},
    }
    real["rubric_coverage"] = {
        "Explains rollback.": "covered",
        "Names trade-off.": "missing",
    }
    monkeypatch.setattr(evaluator_node_mod, "evaluate_answer", lambda **_: real)

    state = _state_with_dim("system_design", prev_score=None, prev_status="pending")
    state["current_contract"] = {
        "must_cover": ["Explains rollback.", "Names trade-off."],
        "acceptance_checks": ["Explains rollback.", "Names trade-off."],
    }
    update = evaluator_node_mod.evaluator_node(state)

    assert update["qa_history"][0]["evaluation"]["passed"] is False
    assert update["dimension_status"]["system_design"] == "active"
    assert "score is high but required evidence is missing" in update["qa_history"][0][
        "evaluation"
    ]["consistency_warnings"]


def test_real_zero_score_is_recorded_as_a_valid_dimension_score(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real = _fake_evaluation(fallback=False, score=0.0, passed=False)
    monkeypatch.setattr(
        evaluator_node_mod,
        "evaluate_answer",
        lambda **kwargs: real,
    )

    state = _state_with_dim("coding_quality", prev_score=None, prev_status="pending")
    update = evaluator_node_mod.evaluator_node(state)

    assert update["scores_per_dim"]["coding_quality"] == 0.0
    assert update["score_breakdowns"]["coding_quality"] == {
        "scored_turn_count": 1,
        "latest_score": 0.0,
        "best_score": 0.0,
        "average_score": 0.0,
        "adopted_score": 0.0,
        "scoring_policy": "anchor_weighted_recent",
        "anchor_count": 1,
        "anchor_average_score": 0.0,
        "best_anchor_score": 0.0,
        "anchor_breakdowns": [
            {
                "scored_turn_count": 1,
                "latest_score": 0.0,
                "best_score": 0.0,
                "average_score": 0.0,
                "adopted_score": 0.0,
                "scoring_policy": "weighted_recent",
                "anchor_key": "unanchored:coding_quality",
                "anchor_label": "\u672a\u5173\u8054\u7b80\u5386\u951a\u70b9",
                "resume_project_id": None,
                "turn_indices": [0],
            }
        ],
    }
    assert update["dimension_status"]["coding_quality"] == "active"


def test_real_evaluation_does_not_extend_legacy_breakdown_without_qa_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real = _fake_evaluation(fallback=False, score=8.0, passed=False)
    monkeypatch.setattr(evaluator_node_mod, "evaluate_answer", lambda **_: real)

    state = _state_with_dim(
        "technical_depth",
        prev_score=9.0,
        prev_status="passed",
        score_breakdown={
            "scored_turn_count": 4,
            "latest_score": 9.0,
            "best_score": 9.0,
            "average_score": 9.0,
            "adopted_score": 9.0,
            "scoring_policy": "weighted_recent",
        },
    )
    update = evaluator_node_mod.evaluator_node(state)

    assert update["scores_per_dim"]["technical_depth"] == 8.0
    breakdown = update["score_breakdowns"]["technical_depth"]
    assert breakdown["scored_turn_count"] == 1
    assert breakdown["anchor_count"] == 1
    assert breakdown["anchor_breakdowns"][0] == {
        "scored_turn_count": 1,
        "latest_score": 8.0,
        "best_score": 8.0,
        "average_score": 8.0,
        "adopted_score": 8.0,
        "scoring_policy": "weighted_recent",
        "anchor_key": "unanchored:technical_depth",
        "anchor_label": "\u672a\u5173\u8054\u7b80\u5386\u951a\u70b9",
        "resume_project_id": None,
        "turn_indices": [0],
    }


def test_legacy_zero_placeholder_is_treated_as_unscored_first_sample(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real = _fake_evaluation(fallback=False, score=7.0, passed=False)
    monkeypatch.setattr(evaluator_node_mod, "evaluate_answer", lambda **_: real)

    state = _state_with_dim("technical_depth", prev_score=0.0, prev_status="pending")
    update = evaluator_node_mod.evaluator_node(state)

    assert update["scores_per_dim"]["technical_depth"] == 7.0


def test_qa_history_persists_answer_intent_normal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When ``current_answer_intent`` is ``"normal"``, the qa_history entry
    carries the same intent so downstream report / replay can reason about
    *why* the turn was scored a given way."""
    real = _fake_evaluation(fallback=False, score=7.0, passed=False)
    monkeypatch.setattr(evaluator_node_mod, "evaluate_answer", lambda **_: real)

    state = _state_with_dim("technical_depth", prev_score=0.0, prev_status="pending")
    update = evaluator_node_mod.evaluator_node(state)

    assert update["qa_history"][0]["answer_intent"] == "normal"


@pytest.mark.parametrize(
    "intent",
    ["empty", "clarification", "repeat", "too_short", "skipped"],
)
def test_qa_history_persists_non_normal_answer_intent(
    monkeypatch: pytest.MonkeyPatch,
    intent: str,
) -> None:
    real = _fake_evaluation(fallback=False, score=4.0, passed=False)
    monkeypatch.setattr(evaluator_node_mod, "evaluate_answer", lambda **_: real)

    state = _state_with_dim("technical_depth", prev_score=0.0, prev_status="pending")
    state["current_answer_intent"] = intent

    update = evaluator_node_mod.evaluator_node(state)

    assert update["qa_history"][0]["answer_intent"] == intent


def test_qa_history_defaults_to_normal_when_intent_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Older checkpoints / partial states without ``current_answer_intent``
    fall back to ``"normal"`` so the field is never absent in the output."""
    real = _fake_evaluation(fallback=False, score=6.0, passed=False)
    monkeypatch.setattr(evaluator_node_mod, "evaluate_answer", lambda **_: real)

    state = _state_with_dim("technical_depth", prev_score=0.0, prev_status="pending")
    state.pop("current_answer_intent", None)

    update = evaluator_node_mod.evaluator_node(state)

    assert update["qa_history"][0]["answer_intent"] == "normal"


def test_qa_history_persists_minimal_injected_question_refs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real = _fake_evaluation(fallback=False, score=7.0, passed=False)
    monkeypatch.setattr(evaluator_node_mod, "evaluate_answer", lambda **_: real)

    state = _state_with_dim("system_design", prev_score=0.0, prev_status="pending")
    state["current_question"] = {
        "dimension": "system_design",
        "question": "Q",
        "selection_artifacts": {
            "rag": {"doc_refs": [{"source": "kb.md"}]},
            "question_items": [
                {
                    "seed_id": "system_design.cache",
                    "variant_id": "system_design.cache.opening",
                    "rank": 1,
                    "injected": True,
                    "scenario_brief": "do not persist",
                    "match_reasons": ["priority:100"],
                },
                {
                    "seed_id": "system_design.queue",
                    "variant_id": "system_design.queue.opening",
                    "rank": 2,
                    "injected": False,
                },
            ],
        },
    }

    update = evaluator_node_mod.evaluator_node(state)

    assert update["qa_history"][0]["selection_artifacts"] == {
        "question_items": [
            {
                "seed_id": "system_design.cache",
                "variant_id": "system_design.cache.opening",
                "rank": 1,
                "injected": True,
            }
        ]
    }
