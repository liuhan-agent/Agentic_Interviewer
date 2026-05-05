"""Tests for the ``overruled_patterns`` aggregation (``PLAN_DRIFT_FEEDBACK`` Step 1).

Covers the per-(dimension, check_name) bucket produced inside
:meth:`VerifierDriftMonitor.snapshot`: count aggregation, evidence /
reasons de-duplication, non-overruled events getting excluded, and
deterministic sort order.

The existing ``test_verifier_drift.py`` covers the top-level counters;
this file focuses exclusively on the new pattern bucket so regression
fingerprints stay small.
"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.ml.drift.verifier_drift import (
    DriftEvent,
    VerifierDriftMonitor,
    reset_verifier_drift_monitor_for_tests,
)


@pytest.fixture(autouse=True)
def _reset_singleton() -> None:
    reset_verifier_drift_monitor_for_tests()
    yield
    reset_verifier_drift_monitor_for_tests()


def _event(
    *,
    dimension: str = "system_design",
    overruled: bool = True,
    check: str | None = "explains isolation per user",
    evidence: tuple[str, ...] = ("token bucket",),
    reasons: tuple[str, ...] = ("buzzword heavy",),
) -> DriftEvent:
    return DriftEvent(
        dimension=dimension,
        job_level="mid",
        evaluator_passed=True,
        verifier_verdict="partial",
        verifier_confidence=0.8,
        verifier_abstained=False,
        overruled=overruled,
        span_miss_count=0,
        span_total=0,
        timestamp=datetime.now(UTC),
        overruled_check_name=check,
        evaluator_evidence_quotes=evidence,
        verifier_reasons=reasons,
    )


def test_overruled_patterns_empty_when_no_events() -> None:
    monitor = VerifierDriftMonitor(window_size=10)
    assert monitor.snapshot()["overruled_patterns"] == []


def test_overruled_patterns_skips_non_overruled_events() -> None:
    """Events that did not actually overrule must not contribute to
    the pattern bucket, even when they carry ``overruled_check_name``
    (that field is only meaningful for overruled events)."""
    monitor = VerifierDriftMonitor(window_size=10)
    monitor.record(_event(overruled=False, check="foo"))
    monitor.record(_event(overruled=True, check=None))  # no check → skip
    assert monitor.snapshot()["overruled_patterns"] == []


def test_overruled_patterns_count_aggregates_same_bucket() -> None:
    monitor = VerifierDriftMonitor(window_size=10)
    for _ in range(3):
        monitor.record(_event())
    patterns = monitor.snapshot()["overruled_patterns"]
    assert len(patterns) == 1
    assert patterns[0]["count"] == 3
    assert patterns[0]["dimension"] == "system_design"
    assert patterns[0]["check"] == "explains isolation per user"


def test_overruled_patterns_separate_buckets_by_dim_and_check() -> None:
    monitor = VerifierDriftMonitor(window_size=10)
    monitor.record(_event(dimension="system_design", check="isolation"))
    monitor.record(_event(dimension="system_design", check="isolation"))
    monitor.record(_event(dimension="system_design", check="burst handling"))
    monitor.record(_event(dimension="behavioral", check="isolation"))
    patterns = monitor.snapshot()["overruled_patterns"]
    keys = [(p["dimension"], p["check"], p["count"]) for p in patterns]
    # Sort: count DESC then (dimension, check) ASC.
    assert keys == [
        ("system_design", "isolation", 2),
        ("behavioral", "isolation", 1),
        ("system_design", "burst handling", 1),
    ]


def test_overruled_patterns_evidence_dedupes_preserving_first_seen() -> None:
    monitor = VerifierDriftMonitor(window_size=10)
    monitor.record(_event(evidence=("token bucket", "Raft")))
    monitor.record(_event(evidence=("Raft", "leader election")))
    monitor.record(_event(evidence=("token bucket",)))
    patterns = monitor.snapshot()["overruled_patterns"]
    assert len(patterns) == 1
    # Insertion order preserved; duplicates collapsed.
    assert patterns[0]["sample_evidence"] == [
        "token bucket",
        "Raft",
        "leader election",
    ]


def test_overruled_patterns_evidence_capped_at_five() -> None:
    """The hard cap prevents a very chatty evaluator + long window
    combo from blowing up the pattern bucket."""
    monitor = VerifierDriftMonitor(window_size=20)
    for i in range(10):
        monitor.record(_event(evidence=(f"quote-{i}",)))
    patterns = monitor.snapshot()["overruled_patterns"]
    assert len(patterns[0]["sample_evidence"]) == 5
    assert patterns[0]["sample_evidence"] == [f"quote-{i}" for i in range(5)]


def test_overruled_patterns_reasons_dedupe_and_cap() -> None:
    monitor = VerifierDriftMonitor(window_size=20)
    for i in range(7):
        monitor.record(
            _event(reasons=(f"reason-{i}", "common reason"))
        )
    patterns = monitor.snapshot()["overruled_patterns"]
    reasons = patterns[0]["reasons_sample"]
    assert len(reasons) == 5
    # "common reason" enters the bucket on the first event and then
    # gets skipped by the dedupe logic; reason-0 .. reason-3 take the
    # remaining slots before the cap.
    assert reasons[:5] == [
        "reason-0",
        "common reason",
        "reason-1",
        "reason-2",
        "reason-3",
    ]


def test_overruled_patterns_ignores_empty_quote_entries() -> None:
    monitor = VerifierDriftMonitor(window_size=10)
    monitor.record(
        _event(evidence=("", "token bucket", ""), reasons=("", "vague"))
    )
    patterns = monitor.snapshot()["overruled_patterns"]
    assert patterns[0]["sample_evidence"] == ["token bucket"]
    assert patterns[0]["reasons_sample"] == ["vague"]


def test_overruled_patterns_unchanged_top_level_shape() -> None:
    """``overruled_patterns`` is an additive key; the existing
    top-level snapshot contract must not shift under its weight."""
    monitor = VerifierDriftMonitor(window_size=10)
    monitor.record(_event())
    snap = monitor.snapshot()
    # Every pre-PLAN_DRIFT_FEEDBACK key still present and typed
    # correctly.
    for key in (
        "window_size",
        "samples",
        "calls",
        "overrides",
        "abstains",
        "override_rate",
        "abstain_rate",
        "span_miss_rate",
        "per_dimension",
        "per_verdict",
    ):
        assert key in snap
    assert isinstance(snap["overruled_patterns"], list)
