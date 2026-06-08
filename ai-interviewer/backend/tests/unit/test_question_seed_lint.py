from __future__ import annotations

from pathlib import Path

from app.services.question_seed_lint import (
    ROLE_COVERAGE_REQUIREMENTS,
    lint_question_seed_dir,
)


def _write_seed_file(
    seed_dir: Path,
    body: str,
    *,
    file_name: str = "system_design.yaml",
) -> None:
    seed_dir.mkdir(parents=True, exist_ok=True)
    (seed_dir / file_name).write_text(body.lstrip(), encoding="utf-8")


def _valid_yaml() -> str:
    return """
dimension: system_design
seeds:
  - id: system_design.cache_consistency
    version: 1
    title: Cache consistency
    dimension: system_design
    job_levels: [junior, mid, senior]
    skill_tags: [redis, cache]
    direction_tags: [internet_tech]
    role_tags: [java_backend]
    rubric: {must_cover: [consistency]}
    priority: 20
    status: active
    source: manual_yaml
    scope: global
    language: zh-CN
    variants:
      - id: system_design.cache_consistency.opening
        version: 1
        intent: opening
        difficulty: standard
        scenario_brief: Flash sale inventory cache consistency.
        question_stem: How would you design Redis inventory cache consistency for a flash sale service?
        prompt_template: Generate a grounded cache consistency question.
        scenario_skill_tags: [redis, inventory_service]
        resume_anchor_hints: [redis, inventory_service]
        failure_categories: [missing_metrics]
        rubric_additions: [Mention consistency windows]
        expected_signals: [Defines consistency target]
        anti_patterns: [Only says add lock]
        good_answer_hints: [Start from business invariant]
        priority: 10
        status: active
      - id: system_design.cache_consistency.failover
        version: 1
        intent: deep_probe
        difficulty: deep_probe
        scenario_brief: Redis failover creates stale inventory reads.
        question_stem: After Redis failover, how would you detect and repair stale inventory reads?
        prompt_template: Generate a deep probe about failover consistency.
        scenario_skill_tags: [redis, failover]
        resume_anchor_hints: [redis, failover]
        failure_categories: [missing_failure_mode]
        rubric_additions: [Mention detection and repair]
        expected_signals: [Discusses reconciliation]
        anti_patterns: [Only says retry]
        good_answer_hints: [Separate detection from repair]
        priority: 8
        status: active
"""


def test_question_seed_quality_lint_passes_dense_seed_file(tmp_path: Path) -> None:
    seed_dir = tmp_path / "question_seeds"
    _write_seed_file(seed_dir, _valid_yaml())

    result = lint_question_seed_dir(seed_dir, strict=False, check_role_coverage=False)

    assert result.passed is True
    assert result.warning_count == 0
    assert result.error_count == 0


def test_question_seed_quality_lint_passes_valid_reviewed_acceptance_checks(
    tmp_path: Path,
) -> None:
    seed_dir = tmp_path / "question_seeds"
    reviewed_yaml = _valid_yaml().replace(
        "        priority: 10\n        status: active",
        """
        reviewed_acceptance_checks:
          - check_id: reviewed:cache-consistency:core:v1
            source: must_cover
            source_text: consistency
            acceptance_check: Answer defines the target consistency level.
            severity: core
            review_status: reviewed
            version: 1
            reviewed_seed_version: 1
            reviewed_variant_version: 1
            reviewed_by: qa-lead
            reviewed_at: "2026-06-01"
          - check_id: reviewed:cache-consistency:support:v1
            source: rubric_addition
            source_text: Mention consistency windows
            acceptance_check: Answer explains the consistency window.
            severity: supporting
            review_status: reviewed
            version: 1
            reviewed_seed_version: 1
            reviewed_variant_version: 1
            reviewed_by: qa-lead
            reviewed_at: "2026-06-01"
        priority: 10
        status: active""",
        1,
    )
    _write_seed_file(seed_dir, reviewed_yaml)

    result = lint_question_seed_dir(seed_dir, strict=True, check_role_coverage=False)

    assert result.passed is True
    assert result.error_count == 0


def test_question_seed_quality_lint_flags_bad_reviewed_acceptance_checks(
    tmp_path: Path,
) -> None:
    seed_dir = tmp_path / "question_seeds"
    reviewed_yaml = _valid_yaml().replace(
        "        priority: 10\n        status: active",
        """
        reviewed_acceptance_checks:
          - source: must_cover
            source_text: consistency
            acceptance_check: Answer defines the target consistency level.
            severity: core
            review_status: reviewed
            version: 1
            reviewed_seed_version: 1
            reviewed_variant_version: 1
          - check_id: reviewed:bad-enum:v1
            source: mystery
            source_text: consistency
            acceptance_check: Answer is clear.
            severity: blocker
            review_status: approved
            version: 1
            reviewed_seed_version: 0
            reviewed_variant_version: 0
          - check_id: reviewed:duplicate:v1
            source: manual
            source_text: manual
            acceptance_check: ""
            severity: supporting
            review_status: reviewed
            version: 1
            reviewed_seed_version: 1
            reviewed_variant_version: 1
          - check_id: reviewed:duplicate:v1
            source: manual
            source_text: manual
            acceptance_check: Answer names one mitigation.
            severity: supporting
            review_status: reviewed
            version: 1
            reviewed_seed_version: 1
            reviewed_variant_version: 1
        priority: 10
        status: active""",
        1,
    )
    _write_seed_file(seed_dir, reviewed_yaml)

    result = lint_question_seed_dir(seed_dir, strict=False, check_role_coverage=False)
    codes = {issue.code for issue in result.issues}

    assert "reviewed_check_schema" in codes
    assert "reviewed_check_duplicate_id" in codes
    assert "review_stale" in codes
    assert "generic_reviewed_acceptance_check" in codes


def test_question_seed_quality_lint_flags_reviewed_core_contract_mismatch(
    tmp_path: Path,
) -> None:
    seed_dir = tmp_path / "question_seeds"
    reviewed_yaml = _valid_yaml().replace(
        "    rubric: {must_cover: [consistency]}",
        "    rubric: {must_cover: [consistency, repair]}",
    ).replace(
        "        rubric_additions: [Mention consistency windows]",
        "        rubric_additions: [Mention consistency windows]",
        1,
    ).replace(
        "        priority: 10\n        status: active",
        """
        reviewed_acceptance_checks:
          - check_id: reviewed:cache-consistency:core-consistency:v1
            source: must_cover
            source_text: consistency
            acceptance_check: Answer defines the target consistency level.
            severity: core
            review_status: reviewed
            version: 1
            reviewed_seed_version: 1
            reviewed_variant_version: 1
            reviewed_by: qa-lead
            reviewed_at: "2026-06-01"
          - check_id: reviewed:cache-consistency:misplaced-repair:v1
            source: must_cover
            source_text: repair
            acceptance_check: Answer explains the repair flow.
            severity: supporting
            review_status: reviewed
            version: 1
            reviewed_seed_version: 1
            reviewed_variant_version: 1
            reviewed_by: qa-lead
            reviewed_at: "2026-06-01"
        priority: 10
        status: active""",
        1,
    )
    _write_seed_file(seed_dir, reviewed_yaml)

    result = lint_question_seed_dir(seed_dir, strict=True, check_role_coverage=False)

    assert result.passed is False
    assert any(issue.code == "reviewed_contract_alignment" for issue in result.issues)
    messages = "\n".join(issue.message for issue in result.issues)
    assert "reviewed core source_text must match must_cover" in messages


def test_question_seed_quality_lint_warns_and_strict_fails(tmp_path: Path) -> None:
    seed_dir = tmp_path / "question_seeds"
    broken = _valid_yaml().replace(
        "      - id: system_design.cache_consistency.failover",
        "      - id: system_design.cache_consistency.failover_disabled",
    ).replace(
        "        status: active\n      - id: system_design.cache_consistency.failover_disabled",
        "        status: disabled\n      - id: system_design.cache_consistency.failover_disabled",
    )
    broken = broken.replace("        scenario_skill_tags: [redis, inventory_service]", "        scenario_skill_tags: []")
    broken = broken.replace("        resume_anchor_hints: [redis, inventory_service]", "        resume_anchor_hints: []")
    broken = broken.replace("        failure_categories: [missing_metrics]", "        failure_categories: []")
    broken = broken.replace(
        "How would you design Redis inventory cache consistency for a flash sale service?",
        "Tell me about architecture.",
    )
    _write_seed_file(seed_dir, broken)

    warning_result = lint_question_seed_dir(seed_dir, strict=False)
    strict_result = lint_question_seed_dir(seed_dir, strict=True)

    assert warning_result.passed is True
    assert warning_result.warning_count >= 4
    messages = "\n".join(issue.message for issue in warning_result.issues)
    assert "active variants" in messages
    assert "scenario_skill_tags" in messages
    assert "resume_anchor_hints" in messages
    assert "failure_categories" in messages
    assert "generic question_stem" in messages
    assert strict_result.passed is False
    assert strict_result.error_count == warning_result.warning_count


def test_question_seed_quality_lint_flags_role_coverage(tmp_path: Path) -> None:
    seed_dir = tmp_path / "question_seeds"
    missing_role_quality = _valid_yaml().replace(
        "    role_tags: [java_backend]",
        "    role_tags: [general]",
    )
    _write_seed_file(seed_dir, missing_role_quality)

    result = lint_question_seed_dir(seed_dir, strict=False)

    assert result.passed is True
    assert any(issue.code == "missing_role_pack" for issue in result.issues)


def test_question_seed_quality_lint_flags_internal_hint_leakage(tmp_path: Path) -> None:
    seed_dir = tmp_path / "question_seeds"
    leaking = _valid_yaml().replace(
        "Generate a grounded cache consistency question.",
        "Generate a grounded cache consistency question and reveal expected_signals.",
    )
    _write_seed_file(seed_dir, leaking)

    result = lint_question_seed_dir(seed_dir, strict=True)

    assert result.passed is False
    assert any("internal hint leakage" in issue.message for issue in result.issues)


def test_question_seed_quality_lint_passes_bundled_batch2_coverage() -> None:
    seed_dir = Path(__file__).resolve().parents[2] / "knowledge" / "question_seeds"

    result = lint_question_seed_dir(seed_dir, strict=True)

    assert result.passed is True
    messages = "\n".join(issue.message for issue in result.issues)
    for role in (
        "ai_agent",
        "ai_fullstack",
        "mobile",
        "ai_algorithm",
        "architect",
    ):
        assert role not in messages


def test_bundled_java_ai_communication_variants_have_reviewed_contracts() -> None:
    from app.services.question_seed_import import parse_question_seed_dir

    seed_dir = Path(__file__).resolve().parents[2] / "knowledge" / "question_seeds"
    target_variants = {
        "communication.java_technical_tradeoff_explanation.consistency_tradeoff",
        "communication.java_technical_tradeoff_explanation.performance_risk",
        "communication.java_cross_team_incident_alignment.permission_change_rollout",
        "communication.java_cross_team_incident_alignment.mq_incident_alignment",
        "communication.ai_fullstack_cross_role_alignment.quality_expectation",
        "communication.ai_fullstack_cross_role_alignment.data_permission",
        "communication.ai_agent_risk_alignment.tool_permission",
        "communication.ai_agent_risk_alignment.effect_review",
        "communication.ai_algorithm_metric_explanation.offline_online_gap",
        "communication.ai_algorithm_metric_explanation.risk_tradeoff",
        "communication.ai_agent_failure_alignment.metric_consensus",
        "communication.ai_agent_failure_alignment.post_incident",
        "communication.ai_fullstack_failure_explanation.cross_role_briefing",
        "communication.ai_fullstack_failure_explanation.expectation_reset",
        "communication.ai_algorithm_dumb_explanation.attribution",
        "communication.ai_algorithm_dumb_explanation.expectation_reset",
    }

    seeds, variants = parse_question_seed_dir(seed_dir)
    seeds_by_id = {seed.values["id"]: seed.values for seed in seeds}
    variants_by_id = {variant.values["id"]: variant.values for variant in variants}

    for variant_id in sorted(target_variants):
        variant = variants_by_id[variant_id]
        seed = seeds_by_id[variant["seed_id"]]
        reviewed = [
            check
            for check in variant.get("reviewed_acceptance_checks") or []
            if check.get("review_status") == "reviewed"
        ]
        core = [
            check.get("source_text")
            for check in reviewed
            if check.get("source") == "must_cover"
            and check.get("severity") == "core"
        ]
        supporting = [
            check.get("source_text")
            for check in reviewed
            if check.get("source") == "rubric_addition"
            and check.get("severity") == "supporting"
        ]

        assert len(reviewed) == 7, variant_id
        assert sorted(core) == sorted((seed.get("rubric") or {})["must_cover"])
        assert sorted(supporting) == sorted(variant["rubric_additions"])
        assert all(variant_id in check["check_id"] for check in reviewed)


def test_bundled_ai_product_thinking_variants_have_reviewed_contracts() -> None:
    from app.services.question_seed_import import parse_question_seed_dir

    seed_dir = Path(__file__).resolve().parents[2] / "knowledge" / "question_seeds"
    target_variants = {
        "product_thinking.ai_agent_effect_loop.support_resolution",
        "product_thinking.ai_agent_effect_loop.user_control",
        "product_thinking.ai_fullstack_experience_metrics.ai_copilot",
        "product_thinking.ai_fullstack_experience_metrics.latency_quality_tradeoff",
        "product_thinking.ai_algorithm_business_metric.recommendation_ctr",
        "product_thinking.ai_algorithm_business_metric.risk_metric",
        "product_thinking.ai_agent_negative_scope.refusal_design",
        "product_thinking.ai_agent_negative_scope.boundary_evolution",
        "product_thinking.ai_agent_trace_transparency.user_view",
        "product_thinking.ai_agent_trace_transparency.audit_view",
        "product_thinking.ai_fullstack_explainable_ux.first_use",
        "product_thinking.ai_fullstack_explainable_ux.failure_recovery",
        "product_thinking.ai_fullstack_scope_judgement.decision_framework",
        "product_thinking.ai_fullstack_scope_judgement.business_alignment",
        "product_thinking.ai_algorithm_metric_to_outcome.translation",
        "product_thinking.ai_algorithm_metric_to_outcome.calibration",
        "product_thinking.ai_algorithm_commitment_boundary.scope",
        "product_thinking.ai_algorithm_commitment_boundary.risk_plan",
    }

    seeds, variants = parse_question_seed_dir(seed_dir)
    seeds_by_id = {seed.values["id"]: seed.values for seed in seeds}
    variants_by_id = {variant.values["id"]: variant.values for variant in variants}

    for variant_id in sorted(target_variants):
        variant = variants_by_id[variant_id]
        seed = seeds_by_id[variant["seed_id"]]
        reviewed = [
            check
            for check in variant.get("reviewed_acceptance_checks") or []
            if check.get("review_status") == "reviewed"
        ]
        core = [
            check.get("source_text")
            for check in reviewed
            if check.get("source") == "must_cover"
            and check.get("severity") == "core"
        ]
        supporting = [
            check.get("source_text")
            for check in reviewed
            if check.get("source") == "rubric_addition"
            and check.get("severity") == "supporting"
        ]

        assert len(reviewed) == 7, variant_id
        assert sorted(core) == sorted((seed.get("rubric") or {})["must_cover"])
        assert sorted(supporting) == sorted(variant["rubric_additions"])
        assert all(variant_id in check["check_id"] for check in reviewed)


def test_bundled_remaining_technical_product_variants_have_reviewed_contracts() -> None:
    from app.services.question_seed_import import parse_question_seed_dir

    seed_dir = Path(__file__).resolve().parents[2] / "knowledge" / "question_seeds"
    target_variants = {
        "communication.frontend_design_backend_alignment.design_tradeoff",
        "communication.frontend_design_backend_alignment.api_contract",
        "communication.sre_incident_stakeholder_alignment.incident_update",
        "communication.sre_incident_stakeholder_alignment.postmortem_alignment",
        "communication.mobile_release_alignment.version_scope",
        "communication.mobile_release_alignment.backend_contract",
        "communication.architect_review_alignment.risk_explanation",
        "communication.architect_review_alignment.disagreement_resolution",
        "communication.frontend_web_cross_role_alignment_round2.shared_consensus",
        "communication.frontend_web_cross_role_alignment_round2.timeline_risk",
        "communication.sre_stability_governance.alignment",
        "communication.sre_stability_governance.escalation",
        "communication.mobile_cross_role_coordination.shared_consensus",
        "communication.mobile_cross_role_coordination.deadline",
        "product_thinking.frontend_experience_resilience.dashboard",
        "product_thinking.frontend_experience_resilience.checkout",
        "product_thinking.frontend_web_micro_interaction.state_design",
        "product_thinking.frontend_web_micro_interaction.long_polling",
        "product_thinking.frontend_web_ab_test.frontend_impl",
        "product_thinking.frontend_web_ab_test.data_trust",
    }

    seeds, variants = parse_question_seed_dir(seed_dir)
    seeds_by_id = {seed.values["id"]: seed.values for seed in seeds}
    variants_by_id = {variant.values["id"]: variant.values for variant in variants}

    for variant_id in sorted(target_variants):
        variant = variants_by_id[variant_id]
        seed = seeds_by_id[variant["seed_id"]]
        reviewed = [
            check
            for check in variant.get("reviewed_acceptance_checks") or []
            if check.get("review_status") == "reviewed"
        ]
        core = [
            check.get("source_text")
            for check in reviewed
            if check.get("source") == "must_cover"
            and check.get("severity") == "core"
        ]
        supporting = [
            check.get("source_text")
            for check in reviewed
            if check.get("source") == "rubric_addition"
            and check.get("severity") == "supporting"
        ]

        assert len(reviewed) == 7, variant_id
        assert sorted(core) == sorted((seed.get("rubric") or {})["must_cover"])
        assert sorted(supporting) == sorted(variant["rubric_additions"])
        assert all(variant_id in check["check_id"] for check in reviewed)


def test_bundled_leadership_architect_variants_have_reviewed_contracts() -> None:
    from app.services.question_seed_import import parse_question_seed_dir

    seed_dir = Path(__file__).resolve().parents[2] / "knowledge" / "question_seeds"
    target_variants = {
        "leadership.architect_technical_governance.arch_review",
        "leadership.architect_technical_governance.cross_team_standard",
    }

    seeds, variants = parse_question_seed_dir(seed_dir)
    seeds_by_id = {seed.values["id"]: seed.values for seed in seeds}
    variants_by_id = {variant.values["id"]: variant.values for variant in variants}

    for variant_id in sorted(target_variants):
        variant = variants_by_id[variant_id]
        seed = seeds_by_id[variant["seed_id"]]
        reviewed = [
            check
            for check in variant.get("reviewed_acceptance_checks") or []
            if check.get("review_status") == "reviewed"
        ]
        core = [
            check.get("source_text")
            for check in reviewed
            if check.get("source") == "must_cover"
            and check.get("severity") == "core"
        ]
        supporting = [
            check.get("source_text")
            for check in reviewed
            if check.get("source") == "rubric_addition"
            and check.get("severity") == "supporting"
        ]

        assert len(reviewed) == 7, variant_id
        assert sorted(core) == sorted((seed.get("rubric") or {})["must_cover"])
        assert sorted(supporting) == sorted(variant["rubric_additions"])
        assert all(variant_id in check["check_id"] for check in reviewed)


def test_question_seed_quality_lint_flags_missing_batch2_role_coverage(
    tmp_path: Path,
) -> None:
    seed_dir = tmp_path / "question_seeds"
    _write_seed_file(
        seed_dir,
        _valid_yaml().replace(
            "job_levels: [junior, mid, senior]",
            "job_levels: [senior]",
        ),
    )

    result = lint_question_seed_dir(seed_dir, strict=False)

    assert result.passed is True
    assert any(issue.code == "role_coverage" for issue in result.issues)
    assert any("ai_agent" in issue.message for issue in result.issues)


def test_question_seed_quality_lint_flags_java_backend_alignment_gaps(
    tmp_path: Path,
) -> None:
    seed_dir = tmp_path / "question_seeds"
    _write_seed_file(
        seed_dir,
        _valid_yaml().replace(
            "job_levels: [junior, mid, senior]",
            "job_levels: [senior]",
        ),
    )

    result = lint_question_seed_dir(seed_dir, strict=False)
    messages = "\n".join(issue.message for issue in result.issues)

    assert result.passed is True
    assert any(issue.code == "role_coverage" for issue in result.issues)
    assert "java_backend: missing dimensions" in messages
    assert "technical_depth" in messages
    assert "coding_quality" in messages
    assert "project_experience" in messages
    assert "java_backend: seed system_design.cache_consistency missing job_levels" in messages
    assert "junior" in messages


def test_question_seed_quality_lint_rejects_backend_systems_as_java_dimension(
    tmp_path: Path,
) -> None:
    seed_dir = tmp_path / "question_seeds"
    seed_dir.mkdir(parents=True, exist_ok=True)
    (seed_dir / "backend_systems.yaml").write_text(
        _valid_yaml()
        .replace("dimension: system_design", "dimension: backend_systems")
        .replace("system_design.cache_consistency", "backend_systems.cache_consistency"),
        encoding="utf-8",
    )

    result = lint_question_seed_dir(seed_dir, strict=True)
    messages = "\n".join(issue.message for issue in result.issues)

    assert result.passed is False
    assert "unsupported question seed file" in messages
    assert "invalid dimension: backend_systems" in messages


def test_question_seed_quality_lint_rejects_tech_role_extra_dimensions(
    tmp_path: Path,
) -> None:
    seed_dir = tmp_path / "question_seeds"
    _write_seed_file(
        seed_dir,
        _valid_yaml()
        .replace("    role_tags: [java_backend]", "    role_tags: [frontend_web]")
        .replace("redis, cache", "frontend, rendering, react"),
    )

    result = lint_question_seed_dir(seed_dir, strict=True)
    messages = "\n".join(issue.message for issue in result.issues)

    assert result.passed is False
    assert "frontend_web: seed system_design.cache_consistency uses unsupported dimension system_design" in messages


def test_question_seed_quality_lint_requires_junior_for_non_architect_tech_roles(
    tmp_path: Path,
) -> None:
    seed_dir = tmp_path / "question_seeds"
    seed_dir.mkdir(parents=True, exist_ok=True)
    (seed_dir / "technical_depth.yaml").write_text(
        _valid_yaml()
        .replace("dimension: system_design", "dimension: technical_depth")
        .replace("system_design.cache_consistency", "technical_depth.frontend_runtime")
        .replace("job_levels: [junior, mid, senior]", "job_levels: [senior]")
        .replace("    role_tags: [java_backend]", "    role_tags: [frontend_web]")
        .replace("redis, cache", "frontend, rendering, react"),
        encoding="utf-8",
    )

    result = lint_question_seed_dir(seed_dir, strict=True)
    messages = "\n".join(issue.message for issue in result.issues)

    assert result.passed is False
    assert "frontend_web: seed technical_depth.frontend_runtime missing job_levels" in messages
    assert "junior" in messages


def test_question_seed_quality_lint_does_not_require_junior_for_architect(
    tmp_path: Path,
) -> None:
    seed_dir = tmp_path / "question_seeds"
    _write_seed_file(
        seed_dir,
        _valid_yaml()
        .replace("job_levels: [junior, mid, senior]", "job_levels: [senior, staff]")
        .replace("    role_tags: [java_backend]", "    role_tags: [architect]")
        .replace("redis, cache", "architect, architecture, distributed"),
    )

    result = lint_question_seed_dir(seed_dir, strict=False)
    messages = "\n".join(issue.message for issue in result.issues)

    assert result.passed is True
    assert "architect: seed system_design.cache_consistency missing job_levels" not in messages


def test_question_seed_quality_lint_flags_role_stem_mismatch(tmp_path: Path) -> None:
    seed_dir = tmp_path / "question_seeds"
    mismatched = _valid_yaml().replace(
        "    role_tags: [java_backend]",
        "    role_tags: [mobile]",
    )
    _write_seed_file(seed_dir, mismatched)

    result = lint_question_seed_dir(seed_dir, strict=False)

    assert result.passed is True
    assert any(issue.code == "role_stem_mismatch" for issue in result.issues)


def test_question_seed_quality_lint_passes_bundled_business1_coverage() -> None:
    seed_dir = Path(__file__).resolve().parents[2] / "knowledge" / "question_seeds"

    result = lint_question_seed_dir(seed_dir, strict=True)

    assert result.passed is True
    messages = "\n".join(issue.message for issue in result.issues)
    for role in (
        "product_manager",
        "operations",
        "sales_business",
        "marketing_brand",
        "hr_function",
        "customer_success",
        "general_management",
    ):
        assert role not in messages


def test_question_seed_quality_lint_tracks_service_management_coverage() -> None:
    assert {
        "hr_function",
        "customer_success",
        "general_management",
    } <= set(ROLE_COVERAGE_REQUIREMENTS)


def test_question_seed_quality_lint_flags_missing_business1_role_coverage(
    tmp_path: Path,
) -> None:
    seed_dir = tmp_path / "question_seeds"
    _write_seed_file(seed_dir, _valid_yaml())

    result = lint_question_seed_dir(seed_dir, strict=False)

    assert result.passed is True
    assert any(issue.code == "role_coverage" for issue in result.issues)
    assert any("product_manager" in issue.message for issue in result.issues)


def test_question_seed_quality_lint_flags_business_role_stem_mismatch(
    tmp_path: Path,
) -> None:
    seed_dir = tmp_path / "question_seeds"
    mismatched = _valid_yaml().replace(
        "    direction_tags: [internet_tech]",
        "    direction_tags: [business]",
    ).replace(
        "    role_tags: [java_backend]",
        "    role_tags: [sales_business]",
    )
    _write_seed_file(seed_dir, mismatched)

    result = lint_question_seed_dir(seed_dir, strict=False)

    assert result.passed is True
    assert any(issue.code == "role_stem_mismatch" for issue in result.issues)


def test_question_seed_quality_lint_requires_junior_for_business_roles(
    tmp_path: Path,
) -> None:
    seed_dir = tmp_path / "question_seeds"
    business = _valid_yaml().replace(
        "dimension: system_design",
        "dimension: user_insight",
    ).replace(
        "  - id: system_design.cache_consistency",
        "  - id: user_insight.user_journey_pain_point",
    ).replace(
        "job_levels: [junior, mid, senior]",
        "job_levels: [mid, senior]",
    ).replace(
        "    dimension: system_design",
        "    dimension: user_insight",
    ).replace(
        "      - id: system_design.cache_consistency.opening",
        "      - id: user_insight.user_journey_pain_point.opening",
    ).replace(
        "      - id: system_design.cache_consistency.failover",
        "      - id: user_insight.user_journey_pain_point.followup",
    ).replace(
        "    direction_tags: [internet_tech]",
        "    direction_tags: [business]",
    ).replace(
        "    role_tags: [java_backend]",
        "    role_tags: [product_manager]",
    )
    _write_seed_file(seed_dir, business, file_name="user_insight.yaml")

    result = lint_question_seed_dir(seed_dir, strict=False)
    messages = "\n".join(issue.message for issue in result.issues)

    assert result.passed is True
    assert (
        "product_manager: seed user_insight.user_journey_pain_point missing job_levels"
        in messages
    )
    assert "junior" in messages
