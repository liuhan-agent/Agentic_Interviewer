from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from app.scripts.evaluate_reviewed_acceptance_grey import main as grey_script_main
from app.services.question_reviewed_acceptance_grey_eval import (
    DEFAULT_GREY_EVAL_THRESHOLDS,
    audit_reviewed_acceptance_retrofit_invariants,
    build_reviewed_acceptance_rollout_proposal,
    evaluate_reviewed_acceptance_grey_readiness,
)
from app.services.question_reviewed_acceptance_report import ReviewedAcceptanceReport


def _report(
    *,
    total_variants: int = 10,
    variants_with_reviewed: int = 9,
    stale: int = 0,
    mismatches: int = 0,
) -> ReviewedAcceptanceReport:
    return ReviewedAcceptanceReport(
        total_seeds=1,
        total_variants=total_variants,
        variants_with_reviewed=variants_with_reviewed,
        variants_without_reviewed=total_variants - variants_with_reviewed,
        reviewed_status_counts={"reviewed": variants_with_reviewed},
        stale_reviewed_checks=[
            {
                "seed_id": "system_design.cache_consistency",
                "variant_id": f"variant-{idx}",
                "check_id": f"stale-{idx}",
                "reviewed_seed_version": 1,
                "current_seed_version": 2,
                "reviewed_variant_version": 1,
                "current_variant_version": 2,
            }
            for idx in range(stale)
        ],
        db_yaml_mismatches=[
            {
                "variant_id": f"variant-{idx}",
                "check_id": f"mismatch-{idx}",
                "reason": "field_mismatch",
                "fields": ["acceptance_check"],
            }
            for idx in range(mismatches)
        ],
        variants_with_compiled_fallback_available=total_variants,
    )


def _trace(
    *,
    source: str = "reviewed",
    applied: bool = True,
    missing: bool = False,
) -> dict[str, Any]:
    return {
        "contract_diagnostics": {
            "reviewed_acceptance_source": source,
            "reviewed_acceptance_present": source == "reviewed",
            "reviewed_acceptance_applied": applied,
            "reviewed_acceptance_missing_from_final": (
                ["Answer explicitly covers consistency target."] if missing else []
            ),
        }
    }


def test_grey_eval_returns_append_ready_when_all_thresholds_pass() -> None:
    result = evaluate_reviewed_acceptance_grey_readiness(
        report=_report(),
        trace_payloads=[_trace() for _ in range(25)],
        scope={"dimension": "system_design", "role": "java_backend"},
    )

    assert result.readiness == "append_ready"
    assert result.gate_reasons == []
    assert result.scope == {"dimension": "system_design", "role": "java_backend"}
    assert result.metrics["reviewed_coverage"] == 0.9
    assert result.metrics["compiled_fallback_rate"] == 0.0
    assert result.metrics["missing_from_final_rate"] == 0.0


def test_grey_eval_returns_shadow_ready_for_runtime_risk_reasons() -> None:
    traces = [_trace() for _ in range(7)]
    traces += [_trace(source="compiled_fallback", applied=False) for _ in range(2)]
    traces += [_trace(source="reviewed", applied=False, missing=True)]

    result = evaluate_reviewed_acceptance_grey_readiness(
        report=_report(),
        trace_payloads=traces,
    )

    assert result.readiness == "shadow_ready"
    assert result.gate_reasons == [
        "insufficient_samples",
        "high_compiled_fallback_rate",
        "high_missing_from_final_rate",
    ]
    assert result.metrics["sample_count"] == 10


def test_grey_eval_returns_not_ready_for_content_and_sync_gate_reasons() -> None:
    result = evaluate_reviewed_acceptance_grey_readiness(
        report=_report(
            total_variants=10,
            variants_with_reviewed=5,
            stale=1,
            mismatches=1,
        ),
        trace_payloads=[_trace() for _ in range(25)],
    )

    assert result.readiness == "not_ready"
    assert result.gate_reasons == [
        "insufficient_reviewed_coverage",
        "stale_reviewed_checks",
        "yaml_db_mismatch",
    ]


def test_rollout_proposal_is_read_only_and_reports_scope() -> None:
    proposal = build_reviewed_acceptance_rollout_proposal(
        report=_report(),
        trace_payloads=[_trace() for _ in range(25)],
        scope={"seed_id": "system_design.cache_consistency"},
    )

    assert proposal["mutates_config"] is False
    assert proposal["scopes"][0]["readiness"] == "append_ready"
    assert proposal["scopes"][0]["scope"] == {
        "seed_id": "system_design.cache_consistency"
    }


def _seed_yaml() -> str:
    check = {
        "check_id": "reviewed:cache:core:v1",
        "source": "must_cover",
        "source_text": "consistency target",
        "acceptance_check": "Answer defines the target consistency level.",
        "severity": "core",
        "review_status": "reviewed",
        "version": 1,
        "reviewed_seed_version": 2,
        "reviewed_variant_version": 3,
        "reviewed_by": "qa-lead",
        "reviewed_at": "2026-06-01",
    }
    rendered = yaml.safe_dump(
        {"reviewed_acceptance_checks": [check]},
        allow_unicode=True,
        sort_keys=False,
    )
    extra = "\n".join(f"        {line}" for line in rendered.splitlines())
    return f"""
dimension: system_design
seeds:
  - id: system_design.cache_consistency
    version: 2
    title: Cache consistency
    dimension: system_design
    job_levels: [junior, mid, senior]
    skill_tags: [redis, cache]
    direction_tags: [internet_tech]
    role_tags: [java_backend]
    rubric:
      must_cover: [consistency target]
      minimum_bar: Explains consistency.
    priority: 20
    status: active
    source: manual_yaml
    scope: global
    language: zh-CN
    variants:
      - id: system_design.cache_consistency.flash_sale_inventory
        version: 3
        intent: opening
        difficulty: standard
        scenario_brief: Flash sale inventory reads are cache-heavy.
        question_stem: Design a cache consistency approach.
        prompt_template: Ask one system design question.
        scenario_skill_tags: [redis]
        resume_anchor_hints: [cache]
        failure_categories: [missing_metrics]
        rubric_additions: [invalidation window]
        expected_signals: [distinguishes strong and eventual consistency]
        anti_patterns: [only says add lock]
        good_answer_hints: [define consistency target first]
{extra}
        priority: 10
        status: active
""".lstrip()


def test_grey_eval_script_prints_json_and_does_not_mutate_yaml(
    tmp_path: Path,
    capsys,
) -> None:
    seed_dir = tmp_path / "question_seeds"
    seed_dir.mkdir()
    seed_file = seed_dir / "system_design.yaml"
    seed_file.write_text(_seed_yaml(), encoding="utf-8")
    before = seed_file.read_text(encoding="utf-8")

    grey_script_main(str(seed_dir))

    output = yaml.safe_load(capsys.readouterr().out)
    assert output["mutates_config"] is False
    assert output["scopes"][0]["readiness"] == "shadow_ready"
    assert output["scopes"][0]["gate_reasons"] == ["insufficient_samples"]
    assert seed_file.read_text(encoding="utf-8") == before


def test_final_retrofit_audit_covers_p0_through_p3c_invariants() -> None:
    audit = audit_reviewed_acceptance_retrofit_invariants()

    assert audit == {
        "locked_core_contract_available": True,
        "compiled_acceptance_available": True,
        "reviewed_variant_model_field_available": True,
        "reviewed_runtime_modes_available": True,
        "runtime_defaults_unchanged": True,
        "authoring_defaults_dry_run": True,
        "report_service_available": True,
        "grey_eval_read_only": True,
    }
    assert DEFAULT_GREY_EVAL_THRESHOLDS.min_reviewed_coverage == 0.8
