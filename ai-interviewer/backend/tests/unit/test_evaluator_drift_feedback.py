"""Tests for :func:`app.ml.drift.prompt_feedback.build_evaluator_drift_negatives`.

Covers the Phase-2 Step-2 module: threshold filtering, ``top_n``
truncation, dimension scoping, quote / reason truncation, and the
"empty monitor returns empty string" contract the feature flag
relies on to collapse back to Phase-1 behaviour.
"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.ml.drift.prompt_feedback import build_evaluator_drift_negatives
from app.ml.drift.verifier_drift import (
    DriftEvent,
    get_verifier_drift_monitor,
    reset_verifier_drift_monitor_for_tests,
)


@pytest.fixture(autouse=True)
def _reset_singleton() -> None:
    reset_verifier_drift_monitor_for_tests()
    yield
    reset_verifier_drift_monitor_for_tests()


def _push(
    *,
    dimension: str = "system_design",
    check: str = "explains isolation per user",
    evidence: tuple[str, ...] = ("token bucket",),
    reasons: tuple[str, ...] = ("buzzword heavy",),
    n: int = 1,
) -> None:
    """Record ``n`` overruled events with the given pattern signal."""
    monitor = get_verifier_drift_monitor()
    for _ in range(n):
        monitor.record(
            DriftEvent(
                dimension=dimension,
                job_level="mid",
                evaluator_passed=True,
                verifier_verdict="partial",
                verifier_confidence=0.8,
                verifier_abstained=False,
                overruled=True,
                span_miss_count=0,
                span_total=0,
                timestamp=datetime.now(UTC),
                overruled_check_name=check,
                evaluator_evidence_quotes=evidence,
                verifier_reasons=reasons,
            )
        )


def test_empty_monitor_returns_empty_string() -> None:
    assert build_evaluator_drift_negatives() == ""


def test_single_event_below_min_support_returns_empty() -> None:
    """Default ``min_support=2`` filters one-off false positives out."""
    _push(n=1)
    assert build_evaluator_drift_negatives() == ""


def test_pattern_at_min_support_renders_block() -> None:
    _push(n=2)
    block = build_evaluator_drift_negatives()
    assert block.startswith("## Prior Evaluator Drift (negative examples)")
    assert "`system_design`" in block
    assert "\"explains isolation per user\"" in block
    assert "2 time(s)" in block
    assert "`\"token bucket\"`" in block
    assert '"buzzword heavy"' in block


def test_dimension_filter_scopes_patterns() -> None:
    _push(dimension="system_design", n=2)
    _push(dimension="behavioral", check="describes outcome", n=2)

    block_sd = build_evaluator_drift_negatives(dimension="system_design")
    block_bh = build_evaluator_drift_negatives(dimension="behavioral")
    block_all = build_evaluator_drift_negatives()

    assert "`system_design`" in block_sd and "`behavioral`" not in block_sd
    assert "`behavioral`" in block_bh and "`system_design`" not in block_bh
    assert "`system_design`" in block_all and "`behavioral`" in block_all


def test_top_n_truncates_even_when_many_patterns_meet_threshold() -> None:
    for i in range(5):
        _push(check=f"check-{i}", n=2)
    block = build_evaluator_drift_negatives(top_n=2)
    # Count number of bullet lines by the unique "- On dimension" prefix.
    assert block.count("- On dimension") == 2


def test_top_n_zero_or_negative_returns_empty() -> None:
    _push(n=2)
    assert build_evaluator_drift_negatives(top_n=0) == ""
    assert build_evaluator_drift_negatives(top_n=-3) == ""


def test_long_evidence_quote_is_truncated() -> None:
    long_quote = "x" * 400
    _push(evidence=(long_quote,), n=2)
    block = build_evaluator_drift_negatives()
    # The renderer caps quotes at 80 chars; verify the rendered block
    # is nowhere near the raw quote length.
    assert long_quote not in block
    assert "…" in block  # truncation ellipsis was applied


def test_empty_evidence_and_reasons_still_renders_count() -> None:
    """A pattern with no captured evidence / reasons must still
    produce a useful bullet — the count alone is a signal."""
    _push(evidence=(), reasons=(), n=2)
    block = build_evaluator_drift_negatives()
    assert block
    assert "2 time(s)" in block
    # No "evidence like" or "reasons" phrasing when those lists are empty.
    assert "evidence like" not in block
    assert "Verifier downgraded with reasons" not in block
