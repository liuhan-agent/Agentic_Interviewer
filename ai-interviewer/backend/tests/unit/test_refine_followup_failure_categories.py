"""Tests for ``refine_followup_node`` consuming structured failure_categories.

PR2 extends the existing ``refine_followup`` -> ``contract_hints`` handshake
so the next round's generator / probe-intent resolver can rely on a
structured taxonomy when one is available, while still degrading to the
free-text :func:`normalize_failure_category` inference when the evaluator
LLM omitted the field.

Contract pinned here:

1. When ``evaluation.failure_categories`` is non-empty, it wins. The
   downstream ``contract_hints`` carry both the multi-value list AND the
   single legacy ``failure_category`` (first entry) for backwards compat.
2. When the evaluator output is empty / missing, fall back to the
   keyword-driven ``normalize_failure_category(...)`` inference and wrap
   the single category as a one-item list.
3. When both sources are silent, leave ``failure_category(ies)`` keys
   absent from ``contract_hints`` — i.e. the existing "clean refine"
   shape is byte-identical, so other PR's tests don't drift.
"""
from __future__ import annotations

from typing import Any

from app.engine.workflow.nodes.refine_followup import refine_followup_node


def _base_state(evaluation: dict[str, Any]) -> dict[str, Any]:
    return {
        "session_id": "sess-refine-failure-categories",
        "trace_id": "trace-refine-failure-categories",
        "job_spec": {"level": "senior"},
        "dimensions": ["system_design"],
        "dimension_status": {"system_design": "active"},
        "current_dimension": "system_design",
        "turn_idx": 1,
        "evaluation": evaluation,
        "qa_history": [],
        "refine_mode": False,
        "runtime_config": {"policy_mode": "template"},
    }


def test_evaluator_failure_categories_take_priority_over_inferred() -> None:
    """Evaluator output wins even when the keyword inference would pick
    a different category — that's the whole point of letting the LLM
    classify directly."""
    state = _base_state(
        {
            "score": 6.0,
            "passed": False,
            "weaknesses": ["架构边界不清"],
            "failure_reason": "架构边界不清",
            "failure_categories": ["missing_metrics", "missing_evidence"],
            "recommended_next": "refine",
        }
    )

    update = refine_followup_node(state)

    hints = update["pending_contract_hints"]
    assert hints["failure_categories"] == ["missing_metrics", "missing_evidence"]
    assert hints["failure_category"] == "missing_metrics"


def test_falls_back_to_normalize_when_evaluator_omits_categories() -> None:
    """No ``failure_categories`` from the evaluator -> infer from
    ``failure_reason + weaknesses + missing_must_cover`` keywords and
    wrap the single hit as a one-item list."""
    state = _base_state(
        {
            "score": 5.5,
            "passed": False,
            "weaknesses": ["缺少量化指标"],
            "failure_reason": "回答里没有任何量化数据",
            "recommended_next": "refine",
        }
    )

    update = refine_followup_node(state)

    hints = update["pending_contract_hints"]
    assert hints["failure_categories"] == ["missing_metrics"]
    assert hints["failure_category"] == "missing_metrics"


def test_evaluator_empty_list_still_triggers_fallback_inference() -> None:
    """An explicit empty list is semantically equivalent to "model said
    nothing"; we should still try the keyword inference instead of
    treating ``[]`` as a confident "no category"."""
    state = _base_state(
        {
            "score": 6.0,
            "passed": False,
            "weaknesses": ["缺少具体例子"],
            "failure_reason": "答案里没有讲到任何具体项目",
            "failure_categories": [],
            "recommended_next": "refine",
        }
    )

    update = refine_followup_node(state)

    hints = update["pending_contract_hints"]
    assert hints["failure_categories"] == ["missing_evidence"]
    assert hints["failure_category"] == "missing_evidence"


def test_no_failure_signals_keeps_hints_clean() -> None:
    """Both sources silent -> the contract_hints stay byte-equivalent to
    the pre-PR2 'clean refine' shape (no ``failure_category(ies)`` keys)."""
    state = _base_state(
        {
            "score": 6.5,
            "passed": False,
            "weaknesses": [],
            "failure_reason": None,
            "recommended_next": "refine",
        }
    )

    update = refine_followup_node(state)

    hints = update["pending_contract_hints"]
    assert "failure_categories" not in hints
    assert "failure_category" not in hints


def test_evaluator_categories_filter_unknown_enums_defensively() -> None:
    """Even if upstream regresses and lets bogus values through, the
    contract_hints must only carry legal enum values."""
    state = _base_state(
        {
            "score": 5.0,
            "passed": False,
            "weaknesses": [],
            "failure_reason": None,
            # ``bogus_category`` slipped through; we must drop it.
            "failure_categories": ["bogus_category", "weak_debugging"],
            "recommended_next": "refine",
        }
    )

    update = refine_followup_node(state)

    hints = update["pending_contract_hints"]
    assert hints["failure_categories"] == ["weak_debugging"]
    assert hints["failure_category"] == "weak_debugging"


def test_must_address_dedupes_repeated_gap_cluster() -> None:
    state = _base_state(
        {
            "score": 6.0,
            "passed": False,
            "weaknesses": [
                "Need clarify compensation success rate, retry window, manual fallback fields",
                "Please add retry window, manual fallback fields, and compensation success rate",
                "Need clarify compensation success rate, retry window, manual fallback fields",
            ],
            "rubric_coverage": {
                "retry window": "missing",
                "manual fallback fields": "missing",
            },
            "recommended_next": "refine",
        }
    )

    update = refine_followup_node(state)

    hints = update["pending_contract_hints"]
    assert hints["must_address"] == [
        "Need clarify compensation success rate, retry window, manual fallback fields"
    ]
    assert hints["missing_must_cover"] == ["retry window"]
