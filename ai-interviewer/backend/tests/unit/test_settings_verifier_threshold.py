"""Audit P3 — verifier abstain threshold reads from Settings.

Locks in the configurability fix: the previous hard-coded 0.55 lived
in ``nodes/verification.py`` and could only be changed via a code
deploy. Now ops can tune ``VERIFIER_MIN_OVERRIDE_CONFIDENCE`` via env.
"""
from __future__ import annotations

import pytest

from app.core import settings as settings_mod
from app.engine.workflow.nodes import verification as verification_node


def _evaluation(passed: bool = True, score: float = 8.0) -> dict:
    return {
        "passed": passed,
        "score": score,
        "weaknesses": [],
        "rationale": "ok",
    }


def _verification(verdict: str, confidence: float) -> dict:
    return {
        "verifier_available": True,
        "verdict": verdict,
        "confidence": confidence,
        "reasons_to_doubt": ["lacks numbers"],
    }


def test_default_threshold_is_zero_point_five_five() -> None:
    settings_mod.get_settings.cache_clear()
    assert verification_node._min_override_confidence() == 0.55


def test_env_override_changes_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VERIFIER_MIN_OVERRIDE_CONFIDENCE", "0.8")
    settings_mod.get_settings.cache_clear()
    try:
        assert verification_node._min_override_confidence() == 0.8
    finally:
        settings_mod.get_settings.cache_clear()


def test_apply_verification_abstains_below_threshold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        verification_node,
        "_min_override_confidence",
        lambda: 0.7,
    )
    out = verification_node._apply_verification(
        _evaluation(passed=True),
        _verification("partial", confidence=0.6),
    )
    # Confidence 0.6 < 0.7 → abstain (passed unchanged, soft_warnings appended)
    assert out["passed"] is True
    assert out.get("verifier_abstained") is True
    assert "lacks numbers" in (out.get("soft_warnings") or [])


def test_apply_verification_overrules_above_threshold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        verification_node,
        "_min_override_confidence",
        lambda: 0.5,
    )
    out = verification_node._apply_verification(
        _evaluation(passed=True),
        _verification("partial", confidence=0.6),
    )
    # Confidence 0.6 >= 0.5 → overrule (passed flipped, recommended_next set)
    assert out["passed"] is False
    assert out["recommended_next"] == "refine"
    assert out["recommended_next_plan"] == "deep_probe"
