"""Tests for app.services.scoring_credibility."""
from __future__ import annotations

from app.services.scoring_credibility import compute_credibility


class TestComputeCredibility:
    def test_zero_turns_is_low(self):
        result = compute_credibility(
            total_turns=0,
            evaluator_fallback_count=0,
        )
        assert result["credibility_level"] == "low"
        assert result["total_turns"] == 0

    def test_normal_session_is_high(self):
        result = compute_credibility(
            total_turns=8,
            evaluator_fallback_count=0,
            evidence_summary={
                "total_quotes": 20,
                "matched_quotes": 18,
                "unmatched_quotes": 2,
                "match_rate": 0.9,
            },
            contract_summary={
                "total_checks": 10,
                "checks_yes": 8,
                "checks_partial": 2,
                "checks_no": 0,
            },
        )
        assert result["credibility_level"] == "high"
        assert result["fallback_rate"] == 0.0
        assert result["evidence_span_miss_rate"] <= 0.3
        assert result["contract_no_rate"] == 0.0
        assert result["verification_forced_refine"] is False

    def test_high_fallback_rate_drops_to_medium(self):
        """A single high-fallback indicator alone yields medium;
        needs a second signal to reach low."""
        result = compute_credibility(
            total_turns=6,
            evaluator_fallback_count=4,
        )
        assert result["credibility_level"] == "medium"
        assert result["fallback_rate"] > 0.5

    def test_moderate_fallback_is_medium(self):
        result = compute_credibility(
            total_turns=8,
            evaluator_fallback_count=3,
        )
        assert result["credibility_level"] == "medium"
        assert 0.25 < result["fallback_rate"] <= 0.5

    def test_high_span_miss_rate_drops_credibility(self):
        result = compute_credibility(
            total_turns=5,
            evaluator_fallback_count=0,
            evidence_summary={
                "total_quotes": 10,
                "unmatched_quotes": 6,
            },
        )
        assert result["credibility_level"] in ("low", "medium")
        assert result["evidence_span_miss_rate"] > 0.5

    def test_high_contract_no_rate_is_medium(self):
        result = compute_credibility(
            total_turns=5,
            evaluator_fallback_count=0,
            contract_summary={
                "total_checks": 10,
                "checks_no": 6,
            },
        )
        assert result["credibility_level"] == "medium"
        assert result["contract_no_rate"] > 0.5

    def test_forced_refine_adds_signal(self):
        result = compute_credibility(
            total_turns=5,
            evaluator_fallback_count=0,
            verification={"forced_refine": True},
        )
        assert result["credibility_level"] == "medium"
        assert result["verification_forced_refine"] is True

    def test_multiple_low_signals_stack_to_low(self):
        result = compute_credibility(
            total_turns=4,
            evaluator_fallback_count=3,
            evidence_summary={
                "total_quotes": 8,
                "unmatched_quotes": 5,
            },
            contract_summary={
                "total_checks": 6,
                "checks_no": 4,
            },
            verification={"forced_refine": True},
        )
        assert result["credibility_level"] == "low"

    def test_missing_evidence_summary_safe(self):
        result = compute_credibility(
            total_turns=5,
            evaluator_fallback_count=0,
            evidence_summary=None,
        )
        assert result["evidence_span_miss_rate"] == 0.0

    def test_missing_contract_summary_safe(self):
        result = compute_credibility(
            total_turns=5,
            evaluator_fallback_count=0,
            contract_summary=None,
        )
        assert result["contract_no_rate"] == 0.0

    def test_output_shape_always_stable(self):
        expected_keys = {
            "credibility_level",
            "fallback_rate",
            "evidence_span_miss_rate",
            "contract_no_rate",
            "verification_forced_refine",
            "total_turns",
            "evaluator_fallback_count",
        }
        result = compute_credibility(total_turns=1, evaluator_fallback_count=0)
        assert set(result.keys()) == expected_keys

    def test_rates_are_clamped_to_unit_interval(self):
        result = compute_credibility(
            total_turns=2,
            evaluator_fallback_count=5,
            evidence_summary={
                "total_quotes": 3,
                "unmatched_quotes": 10,
            },
        )
        assert 0.0 <= result["fallback_rate"] <= 1.0
        assert 0.0 <= result["evidence_span_miss_rate"] <= 1.0
