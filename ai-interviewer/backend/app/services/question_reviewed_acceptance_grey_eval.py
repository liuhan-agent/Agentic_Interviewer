"""Read-only grey readiness gates for reviewed acceptance rollout."""
from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from typing import Any, Literal

from app.services.question_reviewed_acceptance_report import (
    ReviewedAcceptanceReport,
    aggregate_reviewed_acceptance_diagnostics,
    build_reviewed_acceptance_report,
)

ReadinessState = Literal["not_ready", "shadow_ready", "append_ready"]


@dataclass(frozen=True)
class GreyEvalThresholds:
    min_reviewed_coverage: float = 0.8
    max_stale: int = 0
    max_yaml_db_mismatch: int = 0
    min_samples: int = 20
    max_compiled_fallback_rate: float = 0.1
    max_missing_from_final_rate: float = 0.05

    def as_dict(self) -> dict[str, Any]:
        return {
            "min_reviewed_coverage": self.min_reviewed_coverage,
            "max_stale": self.max_stale,
            "max_yaml_db_mismatch": self.max_yaml_db_mismatch,
            "min_samples": self.min_samples,
            "max_compiled_fallback_rate": self.max_compiled_fallback_rate,
            "max_missing_from_final_rate": self.max_missing_from_final_rate,
        }


DEFAULT_GREY_EVAL_THRESHOLDS = GreyEvalThresholds()


@dataclass(frozen=True)
class GreyReadinessResult:
    readiness: ReadinessState
    gate_reasons: list[str] = field(default_factory=list)
    scope: dict[str, str] = field(default_factory=dict)
    metrics: dict[str, Any] = field(default_factory=dict)
    thresholds: GreyEvalThresholds = DEFAULT_GREY_EVAL_THRESHOLDS

    def as_dict(self) -> dict[str, Any]:
        return {
            "readiness": self.readiness,
            "gate_reasons": list(self.gate_reasons),
            "scope": dict(self.scope),
            "metrics": dict(self.metrics),
            "thresholds": self.thresholds.as_dict(),
        }


def evaluate_reviewed_acceptance_grey_readiness(
    *,
    report: ReviewedAcceptanceReport | dict[str, Any],
    trace_payloads: list[dict[str, Any]] | None = None,
    thresholds: GreyEvalThresholds | None = None,
    scope: dict[str, str] | None = None,
) -> GreyReadinessResult:
    """Evaluate rollout readiness without mutating runtime config."""

    active_thresholds = thresholds or DEFAULT_GREY_EVAL_THRESHOLDS
    payload = report.as_dict() if hasattr(report, "as_dict") else dict(report)
    total_variants = _safe_int(payload.get("total_variants"))
    variants_with_reviewed = _safe_int(payload.get("variants_with_reviewed"))
    reviewed_coverage = (
        variants_with_reviewed / total_variants if total_variants > 0 else 0.0
    )
    stale_count = len(payload.get("stale_reviewed_checks") or [])
    mismatch_count = len(payload.get("db_yaml_mismatches") or [])

    diagnostics = aggregate_reviewed_acceptance_diagnostics(trace_payloads or [])
    sample_count = _safe_int(diagnostics.get("total_traces"))
    fallback_count = _safe_int(
        diagnostics.get("reviewed_acceptance_compiled_fallback_count")
    )
    missing_count = _safe_int(
        diagnostics.get("reviewed_acceptance_missing_from_final_count")
    )
    compiled_fallback_rate = fallback_count / sample_count if sample_count else 0.0
    missing_from_final_rate = missing_count / sample_count if sample_count else 0.0

    content_reasons: list[str] = []
    runtime_reasons: list[str] = []
    if reviewed_coverage < active_thresholds.min_reviewed_coverage:
        content_reasons.append("insufficient_reviewed_coverage")
    if stale_count > active_thresholds.max_stale:
        content_reasons.append("stale_reviewed_checks")
    if mismatch_count > active_thresholds.max_yaml_db_mismatch:
        content_reasons.append("yaml_db_mismatch")
    if sample_count < active_thresholds.min_samples:
        runtime_reasons.append("insufficient_samples")
    if compiled_fallback_rate > active_thresholds.max_compiled_fallback_rate:
        runtime_reasons.append("high_compiled_fallback_rate")
    if missing_from_final_rate > active_thresholds.max_missing_from_final_rate:
        runtime_reasons.append("high_missing_from_final_rate")

    if content_reasons:
        readiness: ReadinessState = "not_ready"
    elif runtime_reasons:
        readiness = "shadow_ready"
    else:
        readiness = "append_ready"

    return GreyReadinessResult(
        readiness=readiness,
        gate_reasons=content_reasons + runtime_reasons,
        scope={str(key): str(value) for key, value in (scope or {}).items()},
        metrics={
            "total_variants": total_variants,
            "variants_with_reviewed": variants_with_reviewed,
            "reviewed_coverage": round(reviewed_coverage, 6),
            "stale_count": stale_count,
            "yaml_db_mismatch_count": mismatch_count,
            "sample_count": sample_count,
            "compiled_fallback_rate": round(compiled_fallback_rate, 6),
            "missing_from_final_rate": round(missing_from_final_rate, 6),
        },
        thresholds=active_thresholds,
    )


def build_reviewed_acceptance_rollout_proposal(
    *,
    report: ReviewedAcceptanceReport | dict[str, Any],
    trace_payloads: list[dict[str, Any]] | None = None,
    thresholds: GreyEvalThresholds | None = None,
    scope: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Return a read-only rollout proposal for reviewed acceptance modes."""

    readiness = evaluate_reviewed_acceptance_grey_readiness(
        report=report,
        trace_payloads=trace_payloads,
        thresholds=thresholds,
        scope=scope,
    )
    return {
        "mutates_config": False,
        "scopes": [readiness.as_dict()],
    }


def build_reviewed_acceptance_rollout_proposal_from_yaml(
    path: Any,
    *,
    trace_payloads: list[dict[str, Any]] | None = None,
    thresholds: GreyEvalThresholds | None = None,
) -> dict[str, Any]:
    report = build_reviewed_acceptance_report(yaml_path=path)
    return build_reviewed_acceptance_rollout_proposal(
        report=report,
        trace_payloads=trace_payloads,
        thresholds=thresholds,
        scope={"source": "yaml"},
    )


def audit_reviewed_acceptance_retrofit_invariants() -> dict[str, bool]:
    """Check P0-P3C invariants without modifying state."""

    from app.core.settings import Settings
    from app.engine.contracts.acceptance_compiler import (
        compile_locked_acceptance_checks,
    )
    from app.engine.contracts.seed_contract import build_locked_core_contract
    from app.engine.workflow.nodes import ask_question as ask_mod
    from app.models.question_bank import QuestionVariant
    from app.services.question_reviewed_acceptance_authoring import (
        author_reviewed_acceptance_checks,
    )
    from app.services.question_reviewed_acceptance_report import (
        build_reviewed_acceptance_report,
    )

    locked_core = build_locked_core_contract(
        contract_hints={
            "question_seed": {
                "seed_id": "seed",
                "variant_id": "variant",
                "rubric": {
                    "must_cover": ["core item"],
                    "minimum_bar": "Explains the core item.",
                },
                "rubric_additions": ["supporting item"],
            }
        },
        target_difficulty="medium",
    )
    compiled = compile_locked_acceptance_checks(locked_core)
    authoring_signature = inspect.signature(author_reviewed_acceptance_checks)
    write_default = authoring_signature.parameters["write"].default
    settings_fields = getattr(Settings, "model_fields", {})
    acceptance_default = settings_fields["contract_acceptance_mode"].default
    core_default = settings_fields["contract_core_mode"].default
    acceptance_modes = getattr(ask_mod, "_CONTRACT_ACCEPTANCE_MODES", set())

    return {
        "locked_core_contract_available": bool(locked_core),
        "compiled_acceptance_available": bool(compiled),
        "reviewed_variant_model_field_available": hasattr(
            QuestionVariant,
            "reviewed_acceptance_checks",
        ),
        "reviewed_runtime_modes_available": {
            "reviewed_shadow",
            "reviewed_append",
        }.issubset(set(acceptance_modes)),
        "runtime_defaults_unchanged": (
            acceptance_default == "shadow" and core_default == "shadow"
        ),
        "authoring_defaults_dry_run": write_default is False,
        "report_service_available": callable(build_reviewed_acceptance_report),
        "grey_eval_read_only": (
            DEFAULT_GREY_EVAL_THRESHOLDS.min_reviewed_coverage == 0.8
        ),
    }


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except Exception:
        return 0
