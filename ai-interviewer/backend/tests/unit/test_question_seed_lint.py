from __future__ import annotations

from pathlib import Path

from app.services.question_seed_lint import lint_question_seed_dir


def _write_seed_file(seed_dir: Path, body: str) -> None:
    seed_dir.mkdir(parents=True, exist_ok=True)
    (seed_dir / "system_design.yaml").write_text(body.lstrip(), encoding="utf-8")


def _valid_yaml() -> str:
    return """
dimension: system_design
seeds:
  - id: system_design.cache_consistency
    version: 1
    title: Cache consistency
    dimension: system_design
    job_levels: [senior]
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
    _write_seed_file(seed_dir, _valid_yaml())

    result = lint_question_seed_dir(seed_dir, strict=False)

    assert result.passed is True
    assert any(issue.code == "role_coverage" for issue in result.issues)
    assert any("ai_agent" in issue.message for issue in result.issues)


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
    ):
        assert role not in messages


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
