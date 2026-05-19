"""Tests for the ``failure_categories`` field surfaced by ``evaluator_agent``.

The evaluator LLM is asked to classify the answer's shortcomings into the
fixed :data:`app.engine.workflow.state.FailureCategory` enum so downstream
signal / usage / strategy reasoning can consume a structured taxonomy
instead of free-form ``failure_reason``.

What these tests pin down:

1. Happy path: a valid mixed list survives untouched.
2. Defensive enum filter: unknown / blank values are dropped, duplicates
   collapsed, while legal values keep their order.
3. Hard cap at 3 entries: anything longer is truncated.
4. Empty list and missing key both degrade to ``[]`` — never ``None``.
5. The conservative fallback evaluation (LLM unavailable) also carries
   ``failure_categories: []`` so every downstream consumer can rely on
   the key existing.
"""
from __future__ import annotations

from typing import Any

from app.engine.agents import evaluator_agent as eval_mod
from app.engine.agents.llm_client import LLMTransient


def _make_fake_call(payload_json: str):
    def fake_call(messages, *, json_mode=False, **kwargs):  # type: ignore[no-untyped-def]
        return payload_json

    return fake_call


def _evaluate(**overrides: Any) -> dict[str, Any]:
    return eval_mod.evaluate_answer(
        dimension="system_design",
        question="Explain how you'd scale this service.",
        rubric_points=["metrics", "trade-offs"],
        answer="We mostly talked about boxes and lines without numbers.",
        quality_threshold=7.5,
        contract={
            "must_cover": ["metrics", "trade-offs"],
            "acceptance_checks": ["Mentions concrete metrics.", "Explains trade-offs."],
        },
        **overrides,
    )


def test_evaluator_returns_valid_failure_categories(monkeypatch) -> None:
    monkeypatch.setattr(
        eval_mod,
        "call_chat",
        _make_fake_call(
            '{"score": 5.5, "passed": false, '
            '"strengths": [], "weaknesses": ["缺少指标"], '
            '"acceptance_check_results": {}, '
            '"recommended_next": "refine", '
            '"failure_categories": ["missing_metrics", "missing_evidence"], '
            '"rationale": "ok"}'
        ),
    )

    result = _evaluate()

    assert result["failure_categories"] == ["missing_metrics", "missing_evidence"]


def test_evaluator_filters_invalid_failure_categories(monkeypatch) -> None:
    """Unknown enum values are dropped; duplicates collapse to first occurrence."""
    monkeypatch.setattr(
        eval_mod,
        "call_chat",
        _make_fake_call(
            '{"score": 5.0, "passed": false, '
            '"strengths": [], "weaknesses": [], '
            '"acceptance_check_results": {}, '
            '"recommended_next": "refine", '
            '"failure_categories": ['
            '"missing_metrics", "bogus_category", "", '
            '"missing_metrics", "weak_debugging"'
            "], "
            '"rationale": "noisy"}'
        ),
    )

    result = _evaluate()

    assert result["failure_categories"] == ["missing_metrics", "weak_debugging"]


def test_evaluator_truncates_failure_categories_to_three(monkeypatch) -> None:
    """Five valid entries — keep the first three so prompts stay bounded."""
    monkeypatch.setattr(
        eval_mod,
        "call_chat",
        _make_fake_call(
            '{"score": 5.0, "passed": false, '
            '"strengths": [], "weaknesses": [], '
            '"acceptance_check_results": {}, '
            '"recommended_next": "refine", '
            '"failure_categories": ['
            '"missing_evidence", "missing_metrics", "missing_tradeoff", '
            '"unclear_architecture", "weak_debugging"'
            "], "
            '"rationale": "broad"}'
        ),
    )

    result = _evaluate()

    assert result["failure_categories"] == [
        "missing_evidence",
        "missing_metrics",
        "missing_tradeoff",
    ]


def test_evaluator_empty_failure_categories(monkeypatch) -> None:
    monkeypatch.setattr(
        eval_mod,
        "call_chat",
        _make_fake_call(
            '{"score": 8.0, "passed": true, '
            '"strengths": ["clear"], "weaknesses": [], '
            '"acceptance_check_results": {}, '
            '"recommended_next": "advance", '
            '"failure_categories": [], '
            '"rationale": "great"}'
        ),
    )

    result = _evaluate()

    assert result["failure_categories"] == []


def test_evaluator_missing_failure_categories_key(monkeypatch) -> None:
    """If the model omits the key entirely, default to ``[]`` (never ``None``)."""
    monkeypatch.setattr(
        eval_mod,
        "call_chat",
        _make_fake_call(
            '{"score": 7.0, "passed": true, '
            '"strengths": [], "weaknesses": [], '
            '"acceptance_check_results": {}, '
            '"recommended_next": "advance", '
            '"rationale": "no field"}'
        ),
    )

    result = _evaluate()

    assert "failure_categories" in result
    assert result["failure_categories"] == []


def test_fallback_evaluation_carries_empty_failure_categories(monkeypatch) -> None:
    """LLM transient -> fallback path; downstream consumers can always
    access ``failure_categories`` without isinstance guards."""

    def fake_call(*_args: Any, **_kwargs: Any) -> str:
        raise LLMTransient("Connection error.")

    monkeypatch.setattr(eval_mod, "call_chat", fake_call)

    result = _evaluate()

    assert result["source"] == "fallback"
    assert result["failure_categories"] == []
