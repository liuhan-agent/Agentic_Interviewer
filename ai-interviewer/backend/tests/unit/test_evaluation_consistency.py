from __future__ import annotations

from app.engine.workflow.evaluation_consistency import (
    normalize_evaluation_consistency,
    sync_dimension_status,
)


def _contract() -> dict[str, object]:
    return {
        "must_cover": ["Explains rollback.", "Names trade-off."],
        "acceptance_checks": ["Explains rollback.", "Names trade-off."],
    }


def _evaluation(
    *,
    score: float,
    passed: bool,
    checks: dict[str, object] | None = None,
    coverage: dict[str, str] | None = None,
) -> dict[str, object]:
    return {
        "score": score,
        "passed": passed,
        "recommended_next": "advance",
        "recommended_next_plan": "adaptive",
        "strengths": [],
        "weaknesses": [],
        "rationale": "r",
        "acceptance_check_results": checks
        if checks is not None
        else {
            "Explains rollback.": {"verdict": "yes", "evidence": ["rollback"]},
            "Names trade-off.": {"verdict": "yes", "evidence": ["trade-off"]},
        },
        "rubric_coverage": coverage
        if coverage is not None
        else {
            "Explains rollback.": "covered",
            "Names trade-off.": "covered",
        },
    }


def test_high_score_with_complete_checks_is_promoted_to_passed() -> None:
    evaluation = _evaluation(score=10.0, passed=False)

    normal = normalize_evaluation_consistency(
        evaluation,
        contract=_contract(),
        quality_threshold=7.5,
    )

    assert normal["passed"] is True
    assert normal["recommended_next"] == "advance"


def test_perfect_score_with_missing_required_evidence_is_not_passed() -> None:
    evaluation = _evaluation(
        score=10.0,
        passed=True,
        checks={
            "Explains rollback.": {"verdict": "yes", "evidence": ["rollback"]},
            "Names trade-off.": {"verdict": "no", "evidence": []},
        },
        coverage={
            "Explains rollback.": "covered",
            "Names trade-off.": "missing",
        },
    )

    normal = normalize_evaluation_consistency(
        evaluation,
        contract=_contract(),
        quality_threshold=7.5,
    )

    assert normal["score"] == 10.0
    assert normal["passed"] is False
    assert normal["recommended_next"] == "refine"
    assert "score is high but required evidence is missing" in normal["consistency_warnings"]


def test_above_threshold_partial_coverage_can_be_promoted_to_passed() -> None:
    evaluation = _evaluation(
        score=9.0,
        passed=False,
        checks={
            "Explains rollback.": {"verdict": "yes", "evidence": ["rollback"]},
            "Names trade-off.": {"verdict": "partial", "evidence": ["trade-off"]},
        },
        coverage={
            "Explains rollback.": "covered",
            "Names trade-off.": "partial",
        },
    )

    normal = normalize_evaluation_consistency(
        evaluation,
        contract=_contract(),
        quality_threshold=7.5,
    )

    assert normal["passed"] is True


def test_promoted_pass_clears_refine_routing_fields() -> None:
    evaluation = _evaluation(score=9.0, passed=False)
    evaluation["recommended_next"] = "refine"
    evaluation["recommended_next_plan"] = "deep_probe"

    normal = normalize_evaluation_consistency(
        evaluation,
        contract=_contract(),
        quality_threshold=7.5,
    )

    assert normal["passed"] is True
    assert normal["recommended_next"] == "advance"
    assert normal["recommended_next_plan"] is None
    assert normal["consistency_normalized"] is True
    assert normal["normalization_reason"] == "score_and_coverage_promoted_pass"


def test_below_threshold_is_never_passed() -> None:
    evaluation = _evaluation(score=6.5, passed=True)

    normal = normalize_evaluation_consistency(
        evaluation,
        contract=_contract(),
        quality_threshold=7.5,
    )

    assert normal["passed"] is False
    assert normal["recommended_next"] == "refine"


def test_evaluator_fallback_is_not_normalized() -> None:
    evaluation = _evaluation(score=9.0, passed=False)
    evaluation["source"] = "fallback"
    evaluation["fallback_reason"] = "llm_failed"
    evaluation["recommended_next"] = "refine"
    evaluation["recommended_next_plan"] = "simple"

    normal = normalize_evaluation_consistency(
        evaluation,
        contract=_contract(),
        quality_threshold=7.5,
    )

    assert normal == evaluation


def test_high_confidence_verifier_override_wins_over_perfect_score() -> None:
    evaluation = _evaluation(score=10.0, passed=True)
    verification = {
        "verifier_available": True,
        "verdict": "partial",
        "confidence": 0.9,
        "reasons_to_doubt": ["evidence is too generic"],
    }

    normal = normalize_evaluation_consistency(
        evaluation,
        contract=_contract(),
        quality_threshold=7.5,
        verification=verification,
        verifier_min_override_confidence=0.55,
    )

    assert normal["passed"] is False
    assert normal["recommended_next"] == "refine"
    assert normal["recommended_next_plan"] == "deep_probe"


def test_low_confidence_verifier_override_only_adds_soft_warning() -> None:
    evaluation = _evaluation(score=10.0, passed=True)
    verification = {
        "verifier_available": True,
        "verdict": "fail",
        "confidence": 0.4,
        "reasons_to_doubt": ["maybe missing concrete metrics"],
    }

    normal = normalize_evaluation_consistency(
        evaluation,
        contract=_contract(),
        quality_threshold=7.5,
        verification=verification,
        verifier_min_override_confidence=0.55,
    )

    assert normal["passed"] is True
    assert normal["soft_warnings"] == ["maybe missing concrete metrics"]
    assert normal["verifier_abstained"] is True


def test_sync_dimension_status_uses_final_evaluation_without_demoting_passed_fallback() -> None:
    passed_status = sync_dimension_status(
        {"system_design": "active"},
        "system_design",
        {"passed": True},
    )
    active_status = sync_dimension_status(
        {"system_design": "passed"},
        "system_design",
        {"passed": False},
    )
    fallback_status = sync_dimension_status(
        {"system_design": "passed"},
        "system_design",
        {"passed": False, "source": "fallback"},
    )

    assert passed_status["system_design"] == "passed"
    assert active_status["system_design"] == "active"
    assert fallback_status["system_design"] == "passed"
