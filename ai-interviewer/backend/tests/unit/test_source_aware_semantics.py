from __future__ import annotations

import pytest

from app.engine.workflow.evaluation_consistency import (
    normalize_evaluation_consistency,
)
from app.ml.rl import reward_fn


def _base_eval(*, score: float = 8.5) -> dict:
    return {
        "score": score,
        "passed": True,
        "recommended_next": "advance",
        "acceptance_check_results": {
            "core check": {"verdict": "yes"},
        },
    }


def _result_item(
    *,
    text: str,
    source: str,
    severity: str,
    verdict: str,
    result_present: bool = True,
) -> dict:
    return {
        "text": text,
        "source": source,
        "severity": severity,
        "verdict": verdict,
        "result_present": result_present,
    }


def test_reviewed_core_no_still_triggers_hard_fail() -> None:
    evaluation = _base_eval()
    evaluation["acceptance_check_results"] = {
        "core check": {"verdict": "no"},
    }
    evaluation["acceptance_check_result_items"] = [
        _result_item(
            text="core check",
            source="reviewed",
            severity="core",
            verdict="no",
        )
    ]

    normalized = normalize_evaluation_consistency(
        evaluation,
        contract={},
        quality_threshold=7.5,
    )

    assert normalized["passed"] is False
    assert normalized["recommended_next"] == "refine"
    assert normalized["normalization_reason"] == "required_evidence_missing"


def test_reviewed_supporting_no_does_not_trigger_hard_fail() -> None:
    evaluation = _base_eval()
    evaluation["acceptance_check_results"] = {
        "supporting check": {"verdict": "no"},
    }
    evaluation["acceptance_check_result_items"] = [
        _result_item(
            text="supporting check",
            source="reviewed",
            severity="supporting",
            verdict="no",
        )
    ]

    normalized = normalize_evaluation_consistency(
        evaluation,
        contract={},
        quality_threshold=7.5,
    )

    assert normalized["passed"] is True
    assert normalized["recommended_next"] == "advance"
    assert normalized.get("normalization_reason") not in {
        "required_evidence_missing",
    }


def test_adaptive_context_no_does_not_trigger_hard_fail() -> None:
    evaluation = _base_eval()
    evaluation["acceptance_check_results"] = {
        "context check": {"verdict": "no"},
    }
    evaluation["acceptance_check_result_items"] = [
        _result_item(
            text="context check",
            source="adaptive_context",
            severity="supporting",
            verdict="no",
        )
    ]

    normalized = normalize_evaluation_consistency(
        evaluation,
        contract={},
        quality_threshold=7.5,
    )

    assert normalized["passed"] is True
    assert normalized["recommended_next"] == "advance"


def test_legacy_no_without_structured_items_keeps_hard_fail_behavior() -> None:
    evaluation = _base_eval()
    evaluation["acceptance_check_results"] = {
        "legacy check": {"verdict": "no"},
    }

    normalized = normalize_evaluation_consistency(
        evaluation,
        contract={},
        quality_threshold=7.5,
    )

    assert normalized["passed"] is False
    assert normalized["recommended_next"] == "refine"
    assert normalized["normalization_reason"] == "required_evidence_missing"


def test_empty_structured_items_fall_back_to_legacy_results() -> None:
    evaluation = _base_eval()
    evaluation["acceptance_check_results"] = {
        "legacy check": {"verdict": "no"},
    }
    evaluation["acceptance_check_result_items"] = []

    normalized = normalize_evaluation_consistency(
        evaluation,
        contract={},
        quality_threshold=7.5,
    )

    assert normalized["passed"] is False
    assert normalized["recommended_next"] == "refine"
    assert normalized["normalization_reason"] == "required_evidence_missing"


def test_rubric_missing_stays_hard_fail_with_soft_result_items() -> None:
    evaluation = _base_eval()
    evaluation["acceptance_check_results"] = {
        "supporting check": {"verdict": "yes"},
    }
    evaluation["acceptance_check_result_items"] = [
        _result_item(
            text="supporting check",
            source="reviewed",
            severity="supporting",
            verdict="yes",
        )
    ]
    evaluation["rubric_coverage"] = {"must cover": "missing"}

    normalized = normalize_evaluation_consistency(
        evaluation,
        contract={},
        quality_threshold=7.5,
    )

    assert normalized["passed"] is False
    assert normalized["recommended_next"] == "refine"
    assert normalized["normalization_reason"] == "required_evidence_missing"


def test_reward_legacy_no_rate_keeps_existing_penalty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        reward_fn,
        "get_settings",
        lambda: type(
            "S",
            (),
            {
                "reward_passed_bonus": 0.1,
                "reward_coverage_bonus": 0.0,
                "reward_contract_unsigned_penalty": 0.0,
                "reward_acceptance_no_rate_threshold": 0.5,
                "reward_acceptance_no_penalty": 0.1,
                "reward_verifier_forced_refine_penalty": 0.0,
                "reward_contract_gate_enforced_cap": 0.5,
            },
        )(),
    )
    evaluation = {
        "score": 8.0,
        "passed": True,
        "acceptance_check_results": {
            "a": {"verdict": "no"},
            "b": {"verdict": "no"},
            "c": {"verdict": "yes"},
        },
    }

    assert reward_fn.immediate_reward(evaluation=evaluation, contract={}) == pytest.approx(
        0.8
    )


def test_reward_structured_soft_no_does_not_count_as_hard_no_penalty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        reward_fn,
        "get_settings",
        lambda: type(
            "S",
            (),
            {
                "reward_passed_bonus": 0.1,
                "reward_coverage_bonus": 0.0,
                "reward_contract_unsigned_penalty": 0.0,
                "reward_acceptance_no_rate_threshold": 0.5,
                "reward_acceptance_no_penalty": 0.1,
                "reward_verifier_forced_refine_penalty": 0.0,
                "reward_contract_gate_enforced_cap": 0.5,
            },
        )(),
    )
    evaluation = {
        "score": 8.0,
        "passed": True,
        "acceptance_check_results": {
            "supporting a": {"verdict": "no"},
            "context b": {"verdict": "no"},
            "core c": {"verdict": "yes"},
        },
        "acceptance_check_result_items": [
            _result_item(
                text="supporting a",
                source="reviewed",
                severity="supporting",
                verdict="no",
            ),
            _result_item(
                text="context b",
                source="adaptive_context",
                severity="supporting",
                verdict="no",
            ),
            _result_item(
                text="core c",
                source="reviewed",
                severity="core",
                verdict="yes",
            ),
        ],
    }

    assert reward_fn.immediate_reward(evaluation=evaluation, contract={}) == pytest.approx(
        0.9
    )


def test_reward_structured_reviewed_core_no_still_counts_as_hard_no_penalty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        reward_fn,
        "get_settings",
        lambda: type(
            "S",
            (),
            {
                "reward_passed_bonus": 0.1,
                "reward_coverage_bonus": 0.0,
                "reward_contract_unsigned_penalty": 0.0,
                "reward_acceptance_no_rate_threshold": 0.5,
                "reward_acceptance_no_penalty": 0.1,
                "reward_verifier_forced_refine_penalty": 0.0,
                "reward_contract_gate_enforced_cap": 0.5,
            },
        )(),
    )
    evaluation = {
        "score": 8.0,
        "passed": True,
        "acceptance_check_results": {
            "core a": {"verdict": "no"},
            "core b": {"verdict": "no"},
            "supporting c": {"verdict": "yes"},
        },
        "acceptance_check_result_items": [
            _result_item(
                text="core a",
                source="reviewed",
                severity="core",
                verdict="no",
            ),
            _result_item(
                text="core b",
                source="reviewed",
                severity="core",
                verdict="no",
            ),
            _result_item(
                text="supporting c",
                source="reviewed",
                severity="supporting",
                verdict="yes",
            ),
        ],
    }

    assert reward_fn.immediate_reward(evaluation=evaluation, contract={}) == pytest.approx(
        0.8
    )
