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


def test_structured_question_bank_is_primary_by_default():
    settings = Settings()

    assert settings.question_selector_mode == "structured_primary"
    assert {
        "java_backend",
        "frontend_web",
        "sre",
        "ai_fullstack",
        "ai_agent",
        "mobile",
        "ai_algorithm",
        "architect",
        "product_manager",
        "operations",
        "sales_business",
        "marketing_brand",
        "hr_function",
        "customer_success",
        "general_management",
    } <= set(settings.question_primary_role_tags)


def test_resolver_returns_new_business_scenario_intents(monkeypatch):
    """Smoke test for the four 2026-Q2 business-scenario intents."""
    _enable(monkeypatch)

    assert (
        pi.resolve_probe_intent(
            direction="sales_business",
            dimension="customer_discovery",
            job_level="mid",
        )
        == "case_study_probe"
    )
    assert (
        pi.resolve_probe_intent(
            direction="hr_function",
            dimension="talent_acquisition",
            job_level="mid",
        )
        == "reference_check_probe"
    )
    assert (
        pi.resolve_probe_intent(
            direction="general_management",
            dimension="cross_functional_alignment",
            job_level="senior",
        )
        == "stakeholder_pushback_probe"
    )
    assert (
        pi.resolve_probe_intent(
            direction="hr_function",
            dimension="organization_development",
            job_level="senior",
        )
        == "process_design_probe"
    )


def test_resolver_returns_process_design_for_operations(monkeypatch):
    """Operations · process_optimization should now favour process design."""
    _enable(monkeypatch)

    assert (
        pi.resolve_probe_intent(
            direction="operations",
            dimension="process_optimization",
            job_level="mid",
        )
        == "process_design_probe"
    )


def test_resolver_returns_pushback_for_pm_stakeholder_management(monkeypatch):
    """PM · stakeholder_management should now favour pushback handling."""
    _enable(monkeypatch)

    assert (
        pi.resolve_probe_intent(
            direction="product_manager",
            dimension="stakeholder_management",
            job_level="mid",
        )
        == "stakeholder_pushback_probe"
    )


def test_new_intents_have_chinese_labels():
    """Every ProbeIntent must have an entry in PROBE_INTENT_LABELS."""
    for intent in (
        "case_study_probe",
        "reference_check_probe",
        "stakeholder_pushback_probe",
        "process_design_probe",
    ):
        assert intent in pi.PROBE_INTENT_LABELS, (
            f"missing Chinese label for new intent {intent!r}"
        )
        assert pi.PROBE_INTENT_LABELS[intent], (
            f"empty Chinese label for new intent {intent!r}"
        )


def test_evaluator_hint_can_be_one_of_new_intents(monkeypatch):
    """An evaluator-supplied recommendation must propagate untouched."""
    _enable(monkeypatch)

    assert (
        pi.resolve_probe_intent(
            direction="java_backend",  # default would be debugging_probe
            dimension="technical_depth",
            evaluator_hint="case_study_probe",
        )
        == "case_study_probe"
    )


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
