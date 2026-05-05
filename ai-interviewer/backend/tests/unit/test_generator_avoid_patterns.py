"""Tests for :func:`app.ml.drift.prompt_feedback.build_generator_avoid_patterns`.

Companion to :mod:`tests.unit.test_evaluator_drift_feedback`. Both
helpers read the same ``overruled_patterns`` snapshot, but this one
renders the Generator-facing "avoid" block (question-authoring
framing) rather than the Evaluator-facing "grade stricter" block.
Covers the same filtering / top-N / dimension scoping matrix,
plus the Generator-specific renderer text.
"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.ml.drift.prompt_feedback import build_generator_avoid_patterns
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
    assert build_generator_avoid_patterns() == ""


def test_below_min_support_returns_empty() -> None:
    _push(n=1)
    assert build_generator_avoid_patterns() == ""


def test_at_min_support_renders_generator_block() -> None:
    """At threshold, the renderer must produce the Generator-framed
    block (header + "design the question AWAY from ..." wording)."""
    _push(n=2)
    block = build_generator_avoid_patterns()
    assert block.startswith(
        "## Avoid Patterns (historical verifier signal)"
    )
    # Question-authoring framing — explicitly different from the
    # Evaluator "grade stricter" wording.
    assert "drafting THIS question" in block
    assert "ALONE cannot satisfy" in block
    assert '"explains isolation per user"' in block
    assert "2 time(s)" in block
    assert "`\"token bucket\"`" in block


def test_generator_and_evaluator_render_different_wording() -> None:
    """Same drift data, two renderers -> two distinct messages. This
    is the whole point of the companion-function design."""
    from app.ml.drift.prompt_feedback import (
        build_evaluator_drift_negatives,
    )

    _push(n=2)
    evaluator_block = build_evaluator_drift_negatives()
    generator_block = build_generator_avoid_patterns()

    assert evaluator_block
    assert generator_block
    assert evaluator_block != generator_block
    # The evaluator-facing block asks for stricter grading;
    # the generator-facing block asks for question redesign.
    assert "cautionary patterns" in evaluator_block
    assert "reframe the question" in generator_block


def test_dimension_filter_scopes_generator_patterns() -> None:
    _push(dimension="system_design", n=2)
    _push(dimension="behavioral", check="describes outcome", n=2)

    block_sd = build_generator_avoid_patterns(dimension="system_design")
    block_bh = build_generator_avoid_patterns(dimension="behavioral")

    assert "dimension `system_design`" in block_sd
    assert "behavioral" not in block_sd.split(
        "## Avoid Patterns (historical verifier signal)"
    )[1].splitlines()[2:][0]
    assert "dimension `behavioral`" in block_bh


def test_top_n_truncates_patterns() -> None:
    for i in range(5):
        _push(check=f"check-{i}", n=2)
    block = build_generator_avoid_patterns(top_n=2)
    assert block.count("- Check ") == 2


def test_top_n_zero_returns_empty() -> None:
    _push(n=2)
    assert build_generator_avoid_patterns(top_n=0) == ""


def test_empty_evidence_still_renders_count_without_evidence_clause() -> None:
    """A pattern with no captured evidence must still produce a
    useful bullet — the count alone signals the dimension is risky."""
    _push(evidence=(), reasons=(), n=2)
    block = build_generator_avoid_patterns()
    assert block
    assert "2 time(s)" in block
    # No "with evidence like" clause when evidence list is empty.
    assert "with evidence like" not in block


def test_long_evidence_quote_is_truncated() -> None:
    long_quote = "x" * 400
    _push(evidence=(long_quote,), n=2)
    block = build_generator_avoid_patterns()
    assert long_quote not in block
    assert "…" in block
