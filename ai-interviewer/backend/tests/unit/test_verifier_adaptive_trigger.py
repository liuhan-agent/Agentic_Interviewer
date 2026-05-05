"""Tests for the adaptive verifier-trigger feedback loop.

The adaptive layer sits on top of the rule-based baseline in
:func:`app.engine.agents.verification.should_trigger`. It reads the
per-dimension ``override_rate`` from :mod:`app.ml.drift.verifier_drift`
and:

- **forces a verifier call** when ``override_rate >= high_threshold``
  (the dimension is historically bluff-prone — catch it again);
- **skips the verifier call** when ``override_rate <= low_threshold``
  AND the evaluator's score is comfortably above threshold (the
  dimension has earned the evaluator's trust — save the LLM call);
- **passes through** to the baseline rules otherwise.

Each test manipulates the drift monitor directly via :class:`DriftEvent`
records instead of going through the full ``verification_node`` so we
isolate the trigger decision from the rest of the workflow.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from app.core.settings import get_settings
from app.engine.agents.verification import should_trigger
from app.ml.drift.verifier_drift import (
    DriftEvent,
    get_verifier_drift_monitor,
    reset_verifier_drift_monitor_for_tests,
)

# --------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_settings_and_monitor(monkeypatch: pytest.MonkeyPatch):
    """Every test starts with a clean drift monitor and default settings.

    The monitor is a process-wide singleton; leaking events between
    tests would make per-dimension calls / override_rate assertions
    flaky.  The settings cache is cleared so env-level overrides
    take effect on the next ``get_settings()`` call.
    """
    reset_verifier_drift_monitor_for_tests()
    get_settings.cache_clear()
    yield
    reset_verifier_drift_monitor_for_tests()
    get_settings.cache_clear()


def _seed_events(
    *,
    dimension: str,
    calls: int,
    overrides: int,
    job_level: str = "senior",
) -> None:
    """Push ``calls`` synthetic DriftEvents into the monitor so the
    per-dimension snapshot has ``override_rate = overrides / calls``.
    """
    monitor = get_verifier_drift_monitor()
    now = datetime.now(UTC)
    for i in range(calls):
        monitor.record(
            DriftEvent(
                dimension=dimension,
                job_level=job_level,
                evaluator_passed=True,
                verifier_verdict="partial" if i < overrides else "pass",
                verifier_confidence=0.8,
                verifier_abstained=False,
                overruled=i < overrides,
                span_miss_count=0,
                span_total=0,
                timestamp=now,
            )
        )


def _clean_pass_eval(*, score: float) -> dict[str, Any]:
    """An evaluator verdict that the baseline rules would NOT trigger
    on (clear pass, no partial, not marginal).  We use this to prove
    adaptive can *add* triggers; and we use it to prove adaptive can
    *remove* triggers when combined with senior_always.
    """
    return {
        "passed": True,
        "score": score,
        "acceptance_check_results": {
            "c1": {"verdict": "yes", "evidence": ["q1"]},
        },
    }


# --------------------------------------------------------------------
# Disabled path — nothing changes
# --------------------------------------------------------------------


def test_adaptive_off_by_default_preserves_legacy_behaviour(
    monkeypatch: pytest.MonkeyPatch,
):
    """Default ``verifier_adaptive_trigger=False`` means the drift
    monitor state has zero effect on ``should_trigger``."""
    monkeypatch.setenv("VERIFIER_ADAPTIVE_TRIGGER", "false")
    monkeypatch.setenv("ENABLE_VERIFIER_DRIFT_MONITOR", "true")
    _seed_events(dimension="api_design", calls=100, overrides=99)

    # Clean non-senior pass with no marginal score, no partials, no
    # deep_probe contract, non-bluff-prone dim -> baseline says SKIP.
    decision = should_trigger(
        evaluation=_clean_pass_eval(score=9.5),
        contract={"bar_level": "adaptive"},
        quality_threshold=7.0,
        job_level="mid",
        dimension="api_design",
    )
    assert decision is False


def test_adaptive_on_but_drift_monitor_off_skips_adaptive(
    monkeypatch: pytest.MonkeyPatch,
):
    """Both knobs must be ON for adaptive to engage."""
    monkeypatch.setenv("VERIFIER_ADAPTIVE_TRIGGER", "true")
    monkeypatch.setenv("ENABLE_VERIFIER_DRIFT_MONITOR", "false")
    _seed_events(dimension="api_design", calls=100, overrides=99)

    decision = should_trigger(
        evaluation=_clean_pass_eval(score=9.5),
        contract={"bar_level": "adaptive"},
        quality_threshold=7.0,
        job_level="mid",
        dimension="api_design",
    )
    assert decision is False


# --------------------------------------------------------------------
# Minimum-samples gate
# --------------------------------------------------------------------


def test_adaptive_requires_min_samples_per_dimension(
    monkeypatch: pytest.MonkeyPatch,
):
    """Before the per-dim window has ``verifier_adaptive_min_samples``
    events, adaptive must pass through to the baseline to avoid acting
    on statistical noise."""
    monkeypatch.setenv("VERIFIER_ADAPTIVE_TRIGGER", "true")
    monkeypatch.setenv("ENABLE_VERIFIER_DRIFT_MONITOR", "true")
    monkeypatch.setenv("VERIFIER_ADAPTIVE_MIN_SAMPLES", "30")
    # 100% override rate, but only 10 events (< 30) — should NOT
    # affect the baseline decision
    _seed_events(dimension="api_design", calls=10, overrides=10)

    decision = should_trigger(
        evaluation=_clean_pass_eval(score=9.5),
        contract={"bar_level": "adaptive"},
        quality_threshold=7.0,
        job_level="mid",
        dimension="api_design",
    )
    assert decision is False  # baseline says skip, adaptive passes through


# --------------------------------------------------------------------
# High drift — force trigger on an otherwise clean pass
# --------------------------------------------------------------------


def test_high_override_rate_forces_trigger_even_when_baseline_skips(
    monkeypatch: pytest.MonkeyPatch,
):
    """Dimension with high historical override rate should get
    verified even on a squeaky-clean pass that baseline would skip."""
    monkeypatch.setenv("VERIFIER_ADAPTIVE_TRIGGER", "true")
    monkeypatch.setenv("ENABLE_VERIFIER_DRIFT_MONITOR", "true")
    monkeypatch.setenv("VERIFIER_ADAPTIVE_HIGH_THRESHOLD", "0.25")
    monkeypatch.setenv("VERIFIER_ADAPTIVE_MIN_SAMPLES", "30")
    # 40 calls, 20 overrides -> override_rate=0.5 > 0.25
    _seed_events(dimension="api_design", calls=40, overrides=20)

    decision = should_trigger(
        evaluation=_clean_pass_eval(score=9.5),
        contract={"bar_level": "adaptive"},
        quality_threshold=7.0,
        job_level="mid",
        dimension="api_design",
    )
    assert decision is True  # adaptive overrides baseline


# --------------------------------------------------------------------
# Low drift — skip the verifier when pass is safely above threshold
# --------------------------------------------------------------------


def test_low_override_rate_allows_skipping_clear_pass_even_on_senior(
    monkeypatch: pytest.MonkeyPatch,
):
    """Dimension with almost no historical override + score comfortably
    above threshold -> adaptive skips even when ``senior_always`` would
    fire on a senior candidate."""
    monkeypatch.setenv("VERIFIER_ADAPTIVE_TRIGGER", "true")
    monkeypatch.setenv("ENABLE_VERIFIER_DRIFT_MONITOR", "true")
    monkeypatch.setenv("VERIFIER_ADAPTIVE_LOW_THRESHOLD", "0.05")
    monkeypatch.setenv("VERIFIER_ADAPTIVE_MIN_SAMPLES", "30")
    monkeypatch.setenv("VERIFIER_SENIOR_ALWAYS", "true")
    monkeypatch.setenv("VERIFIER_MARGIN", "1.0")
    # 200 calls, 2 overrides -> override_rate=0.01 <= 0.05
    _seed_events(dimension="api_design", calls=200, overrides=2)

    # Senior + clean pass with score > threshold + margin
    decision = should_trigger(
        evaluation=_clean_pass_eval(score=9.5),
        contract={"bar_level": "adaptive"},
        quality_threshold=7.0,
        job_level="senior",
        dimension="api_design",
    )
    assert decision is False  # adaptive flips senior_always OFF


def test_low_override_rate_still_triggers_on_marginal_pass(
    monkeypatch: pytest.MonkeyPatch,
):
    """Even a low-drift dimension must keep verifying marginal passes
    — the margin is where verifier signal is most valuable."""
    monkeypatch.setenv("VERIFIER_ADAPTIVE_TRIGGER", "true")
    monkeypatch.setenv("ENABLE_VERIFIER_DRIFT_MONITOR", "true")
    monkeypatch.setenv("VERIFIER_ADAPTIVE_LOW_THRESHOLD", "0.05")
    monkeypatch.setenv("VERIFIER_ADAPTIVE_MIN_SAMPLES", "30")
    monkeypatch.setenv("VERIFIER_MARGIN", "1.0")
    _seed_events(dimension="api_design", calls=200, overrides=2)

    # Score 7.2 with threshold 7.0 -> abs(score-threshold)=0.2 < 1.0
    # = MARGINAL. Baseline says TRIGGER. Adaptive must NOT override
    # to False here because adaptive only skips comfortably-clean
    # passes.
    eval_marginal = {
        "passed": True,
        "score": 7.2,
        "acceptance_check_results": {
            "c1": {"verdict": "yes", "evidence": ["q"]}
        },
    }
    decision = should_trigger(
        evaluation=eval_marginal,
        contract={"bar_level": "adaptive"},
        quality_threshold=7.0,
        job_level="mid",
        dimension="api_design",
    )
    assert decision is True  # baseline fires; adaptive does NOT skip


# --------------------------------------------------------------------
# Mid-range override rate — pass-through to baseline
# --------------------------------------------------------------------


def test_clean_deep_probe_pass_without_evidence_gap_skips_verifier() -> None:
    """Deep-probe questions are important, but a clean, well-evidenced
    pass should not pay the verifier LLM tax solely because of the
    question template.
    """
    decision = should_trigger(
        evaluation=_clean_pass_eval(score=9.5),
        contract={"bar_level": "deep_probe"},
        quality_threshold=7.0,
        job_level="mid",
        dimension="api_design",
    )

    assert decision is False


def test_deep_probe_with_unsupported_yes_triggers_verifier() -> None:
    """Deep-probe still triggers when the evaluator claims a check was
    satisfied but provides no evidence quote to support it.
    """
    evaluation = {
        "passed": True,
        "score": 9.5,
        "acceptance_check_results": {
            "c1": {"verdict": "yes", "evidence": []},
        },
    }

    decision = should_trigger(
        evaluation=evaluation,
        contract={"bar_level": "deep_probe"},
        quality_threshold=7.0,
        job_level="mid",
        dimension="api_design",
    )

    assert decision is True


def test_clean_bluff_prone_dimension_without_evidence_gap_skips_verifier() -> None:
    """Bluff-prone dimensions are no longer unconditional verifier
    triggers; clean, evidenced passes can move on.
    """
    decision = should_trigger(
        evaluation=_clean_pass_eval(score=9.5),
        contract={"bar_level": "adaptive"},
        quality_threshold=7.0,
        job_level="mid",
        dimension="system_design",
    )

    assert decision is False


def test_bluff_prone_dimension_with_unsupported_yes_triggers_verifier() -> None:
    evaluation = {
        "passed": True,
        "score": 9.5,
        "acceptance_check_results": {
            "c1": {"verdict": "yes", "evidence": []},
        },
    }

    decision = should_trigger(
        evaluation=evaluation,
        contract={"bar_level": "adaptive"},
        quality_threshold=7.0,
        job_level="mid",
        dimension="system_design",
    )

    assert decision is True


def test_mid_override_rate_passes_through_to_baseline(
    monkeypatch: pytest.MonkeyPatch,
):
    """An override_rate between the two thresholds leaves baseline in
    charge (no adaptive decision either way)."""
    monkeypatch.setenv("VERIFIER_ADAPTIVE_TRIGGER", "true")
    monkeypatch.setenv("ENABLE_VERIFIER_DRIFT_MONITOR", "true")
    monkeypatch.setenv("VERIFIER_ADAPTIVE_HIGH_THRESHOLD", "0.25")
    monkeypatch.setenv("VERIFIER_ADAPTIVE_LOW_THRESHOLD", "0.05")
    monkeypatch.setenv("VERIFIER_ADAPTIVE_MIN_SAMPLES", "30")
    monkeypatch.setenv("VERIFIER_SENIOR_ALWAYS", "true")
    # 40 calls, 6 overrides -> override_rate=0.15 (middle band)
    _seed_events(dimension="api_design", calls=40, overrides=6)

    # Senior + clean pass -> baseline TRIGGERS (senior_always).
    # Middle-band drift does NOT override, so we still trigger.
    decision = should_trigger(
        evaluation=_clean_pass_eval(score=9.5),
        contract={"bar_level": "adaptive"},
        quality_threshold=7.0,
        job_level="senior",
        dimension="api_design",
    )
    assert decision is True  # baseline (senior_always) stays in charge


# --------------------------------------------------------------------
# Per-dimension isolation — adaptive decision is scoped to the dim
# --------------------------------------------------------------------


def test_adaptive_decision_is_per_dimension(
    monkeypatch: pytest.MonkeyPatch,
):
    """A hot dimension's override_rate must not spill into a different
    dimension.  We seed ``api_design`` with heavy drift and
    ``system_design`` with light drift and assert the decision differs
    per-dimension despite identical evaluator input.

    Uses a bumped ``VERIFIER_DRIFT_WINDOW_SIZE`` so the two per-dim
    populations fit concurrently in the rolling window; with the
    default ``200`` the 40 api_design events would otherwise be
    evicted by the 200 frontend_craft events and the per-dim
    override_rate would read as zero.
    """
    monkeypatch.setenv("VERIFIER_ADAPTIVE_TRIGGER", "true")
    monkeypatch.setenv("ENABLE_VERIFIER_DRIFT_MONITOR", "true")
    monkeypatch.setenv("VERIFIER_ADAPTIVE_HIGH_THRESHOLD", "0.25")
    monkeypatch.setenv("VERIFIER_ADAPTIVE_LOW_THRESHOLD", "0.05")
    monkeypatch.setenv("VERIFIER_ADAPTIVE_MIN_SAMPLES", "30")
    monkeypatch.setenv("VERIFIER_DIMENSIONS_BLUFF_PRONE", "[]")
    monkeypatch.setenv("VERIFIER_DRIFT_WINDOW_SIZE", "1000")
    _seed_events(dimension="api_design", calls=40, overrides=25)
    _seed_events(dimension="frontend_craft", calls=200, overrides=4)

    eval_clean = _clean_pass_eval(score=9.5)

    # High-drift dim: adaptive forces TRIGGER
    assert should_trigger(
        evaluation=eval_clean,
        contract={"bar_level": "adaptive"},
        quality_threshold=7.0,
        job_level="mid",
        dimension="api_design",
    ) is True

    # Low-drift dim (same evaluator, same score): adaptive forces SKIP
    assert should_trigger(
        evaluation=eval_clean,
        contract={"bar_level": "adaptive"},
        quality_threshold=7.0,
        job_level="mid",
        dimension="frontend_craft",
    ) is False


# --------------------------------------------------------------------
# Evaluator says fail — adaptive never overrides that
# --------------------------------------------------------------------


def test_failure_short_circuits_regardless_of_drift(
    monkeypatch: pytest.MonkeyPatch,
):
    """``passed=False`` must always short-circuit to ``False`` before
    any adaptive/drift logic runs, to keep the ``should_trigger``
    contract simple for callers."""
    monkeypatch.setenv("VERIFIER_ADAPTIVE_TRIGGER", "true")
    monkeypatch.setenv("ENABLE_VERIFIER_DRIFT_MONITOR", "true")
    _seed_events(dimension="api_design", calls=100, overrides=99)

    decision = should_trigger(
        evaluation={"passed": False, "score": 3.0},
        contract={"bar_level": "deep_probe"},
        quality_threshold=7.0,
        job_level="senior",
        dimension="api_design",
    )
    assert decision is False


def test_adaptive_ignores_unavailable_drift_backend(
    monkeypatch: pytest.MonkeyPatch,
):
    """Redis/backend outage must fall back to baseline, not stale drift."""
    monkeypatch.setenv("VERIFIER_ADAPTIVE_TRIGGER", "true")
    monkeypatch.setenv("ENABLE_VERIFIER_DRIFT_MONITOR", "true")
    monkeypatch.setenv("VERIFIER_ADAPTIVE_HIGH_THRESHOLD", "0.25")
    monkeypatch.setenv("VERIFIER_ADAPTIVE_MIN_SAMPLES", "30")

    class _UnavailableMonitor:
        def snapshot(self) -> dict[str, Any]:
            return {
                "backend_unavailable": True,
                "per_dimension": {
                    "api_design": {"calls": 100, "override_rate": 0.99}
                },
            }

    from app.ml.drift import verifier_drift as drift_mod

    monkeypatch.setattr(
        drift_mod,
        "get_verifier_drift_monitor",
        lambda: _UnavailableMonitor(),
    )

    decision = should_trigger(
        evaluation=_clean_pass_eval(score=9.5),
        contract={"bar_level": "adaptive"},
        quality_threshold=7.0,
        job_level="mid",
        dimension="api_design",
    )

    assert decision is False
