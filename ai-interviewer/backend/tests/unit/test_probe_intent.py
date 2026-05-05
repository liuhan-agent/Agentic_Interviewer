from __future__ import annotations

from types import SimpleNamespace

from app.core.settings import Settings
from app.engine.workflow import probe_intent as pi


def _enable(monkeypatch) -> None:
    monkeypatch.setattr(
        pi,
        "get_settings",
        lambda: SimpleNamespace(enable_probe_intent=True),
    )


def test_resolver_uses_direction_dimension_defaults(monkeypatch):
    _enable(monkeypatch)

    assert (
        pi.resolve_probe_intent(
            direction="java_backend",
            dimension="system_design",
            job_level="senior",
        )
        == "architecture_challenge"
    )
    assert (
        pi.resolve_probe_intent(
            direction="product_manager",
            dimension="metrics_thinking",
            job_level="mid",
        )
        == "metric_probe"
    )
    assert (
        pi.resolve_probe_intent(
            direction="sales_business",
            dimension="objection_handling",
            job_level="mid",
        )
        == "objection_probe"
    )


def test_resolver_coverage_closeout_has_highest_priority(monkeypatch):
    _enable(monkeypatch)

    assert (
        pi.resolve_probe_intent(
            direction="product_manager",
            dimension="metrics_thinking",
            evaluator_hint="metric_probe",
            failure_category="missing_tradeoff",
            coverage_closeout=True,
        )
        == "coverage_closeout"
    )


def test_resolver_uses_failure_category_before_direction_default(monkeypatch):
    _enable(monkeypatch)

    assert (
        pi.resolve_probe_intent(
            direction="product_manager",
            dimension="user_insight",
            failure_category="missing_metrics",
        )
        == "metric_probe"
    )
    assert (
        pi.resolve_probe_intent(
            direction="java_backend",
            dimension="technical_depth",
            failure_category="missing_tradeoff",
        )
        == "tradeoff_probe"
    )
    assert (
        pi.resolve_probe_intent(
            direction="frontend",
            dimension="product_thinking",
            failure_category="unclear_architecture",
        )
        == "architecture_challenge"
    )


def test_resolver_prefers_failure_reason_over_direction_default(monkeypatch):
    _enable(monkeypatch)

    assert (
        pi.resolve_probe_intent(
            direction="java_backend",
            dimension="system_design",
            failure_reason="answer lacks concrete evidence",
        )
        == "evidence_probe"
    )


def test_resolver_stays_disabled_without_flag(monkeypatch):
    monkeypatch.setattr(
        pi,
        "get_settings",
        lambda: SimpleNamespace(enable_probe_intent=False),
    )

    assert (
        pi.resolve_probe_intent(
            direction="java_backend",
            dimension="system_design",
        )
        is None
    )


def test_probe_intent_is_enabled_by_default():
    assert Settings().enable_probe_intent is True


def test_normalize_failure_category_from_reason_and_missing_items():
    assert (
        pi.normalize_failure_category(
            failure_reason="answer lacks metrics",
            weaknesses=[],
            missing_must_cover=[],
        )
        == "missing_metrics"
    )
    assert (
        pi.normalize_failure_category(
            failure_reason="",
            weaknesses=["没有解释取舍"],
            missing_must_cover=[],
        )
        == "missing_tradeoff"
    )
    assert (
        pi.normalize_failure_category(
            failure_reason="",
            weaknesses=[],
            missing_must_cover=["root cause analysis"],
        )
        == "weak_debugging"
    )
