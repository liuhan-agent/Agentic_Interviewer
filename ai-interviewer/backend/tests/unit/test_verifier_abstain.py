"""Tests for the verifier abstain path.

The verifier is allowed to flip the evaluator's verdict only when its
confidence clears ``Settings.verifier_min_override_confidence``. Below
that threshold we keep ``passed`` as evaluated and surface the
concerns as ``soft_warnings`` for the next round.
"""
from __future__ import annotations

from typing import Any

from app.engine.workflow.nodes.refine_followup import refine_followup_node
from app.engine.workflow.nodes.verification import (
    _apply_verification,
    _min_override_confidence,
)


# Snapshot the live threshold for tests that want a "just below /
# just above" delta. Reading once at import time mirrors the
# behaviour of the legacy module-level constant we replaced.
MIN_OVERRIDE_CONFIDENCE = _min_override_confidence()


def _base_evaluation(**overrides: Any) -> dict[str, Any]:
    ev: dict[str, Any] = {
        "score": 7.6,
        "passed": True,
        "recommended_next": "advance",
        "recommended_next_plan": "adaptive",
        "strengths": ["clear structure"],
        "weaknesses": [],
        "rubric_coverage": {"depth": "covered"},
        "acceptance_check_results": {},
    }
    ev.update(overrides)
    return ev


def _verif(**overrides: Any) -> dict[str, Any]:
    v: dict[str, Any] = {
        "verifier_available": True,
        "verdict": "partial",
        "reasons_to_doubt": ["answer glossed over failover"],
        "would_ask_next": "walk through a partition scenario",
        "confidence": 0.7,
        "rationale": "plausible but handwavy",
    }
    v.update(overrides)
    return v


def test_low_confidence_partial_does_not_flip_passed() -> None:
    evaluation = _base_evaluation()
    verification = _verif(confidence=MIN_OVERRIDE_CONFIDENCE - 0.1)

    updated = _apply_verification(evaluation, verification)

    assert updated["passed"] is True
    assert updated.get("verifier_abstained") is True
    assert "answer glossed over failover" in updated["soft_warnings"]
    # weaknesses should NOT have been mutated on the abstain path
    assert updated["weaknesses"] == []


def test_low_confidence_fail_still_abstains() -> None:
    evaluation = _base_evaluation()
    verification = _verif(verdict="fail", confidence=0.3)

    updated = _apply_verification(evaluation, verification)

    assert updated["passed"] is True
    assert updated.get("verifier_abstained") is True
    assert updated.get("verifier_forced_refine") is not True


def test_high_confidence_partial_flips_passed() -> None:
    evaluation = _base_evaluation()
    verification = _verif(confidence=0.8, verdict="partial")

    updated = _apply_verification(evaluation, verification)

    assert updated["passed"] is False
    assert updated["recommended_next"] == "refine"
    assert updated["recommended_next_plan"] == "deep_probe"
    assert "answer glossed over failover" in updated["weaknesses"]
    assert updated.get("verifier_abstained") is not True


def test_high_confidence_fail_marks_forced_refine() -> None:
    evaluation = _base_evaluation()
    verification = _verif(confidence=0.9, verdict="fail")

    updated = _apply_verification(evaluation, verification)

    assert updated["passed"] is False
    assert updated.get("verifier_forced_refine") is True


def test_pass_verdict_is_unchanged_regardless_of_confidence() -> None:
    evaluation = _base_evaluation()
    verification = _verif(verdict="pass", confidence=0.1)

    updated = _apply_verification(evaluation, verification)

    assert updated == evaluation


def test_soft_warnings_propagate_into_refine_contract_hints() -> None:
    """When refine_followup runs on an evaluation carrying
    soft_warnings (e.g. from a previous abstain + subsequent explicit
    refine), the hints sent to the next contract round include them."""
    state: dict[str, Any] = {
        "session_id": "sess-x",
        "trace_id": "trace-x",
        "current_dimension": "system_design",
        "evaluation": {
            "passed": False,
            "recommended_next": "refine",
            "recommended_next_plan": "deep_probe",
            "weaknesses": ["shallow on consistency"],
            "rubric_coverage": {},
            "soft_warnings": ["partition handling unclear"],
        },
    }
    out = refine_followup_node(state)  # type: ignore[arg-type]

    hints = out["pending_contract_hints"]
    assert hints["must_address"] == ["shallow on consistency"]
    assert hints["prior_soft_warnings"] == ["partition handling unclear"]
    assert out["pending_plan_template"] == "deep_probe"


def test_abstain_preserves_existing_soft_warnings_without_duplication() -> None:
    evaluation = _base_evaluation(soft_warnings=["earlier concern"])
    verification = _verif(
        confidence=0.2,
        reasons_to_doubt=["earlier concern", "new concern"],
    )

    updated = _apply_verification(evaluation, verification)

    assert updated["soft_warnings"] == ["earlier concern", "new concern"]
