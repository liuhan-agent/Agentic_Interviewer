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


def _state_with_dim(dim: str, *, prev_score: float, prev_status: str) -> dict[str, Any]:
    return {
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

    # Running 70/30 average: 0.7 * 6.0 + 0.3 * 8.0 = 4.2 + 2.4 = 6.6
    assert update["scores_per_dim"]["technical_depth"] == 6.6
    assert update["dimension_status"]["technical_depth"] == "passed"
