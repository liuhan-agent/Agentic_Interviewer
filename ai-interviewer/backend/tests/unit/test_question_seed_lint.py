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
