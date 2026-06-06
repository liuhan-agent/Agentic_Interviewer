from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
from app.models.question_bank import QuestionSeed, QuestionVariant
from app.services.question_seed_import import (
    QuestionSeedImportError,
    import_question_seed_dir,
)


def _session_factory():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)


def _seed_file(
    root: Path,
    dimension: str,
    *,
    seed_id: str | None = None,
    variant_id: str | None = None,
    file_name: str | None = None,
    status: str = "active",
) -> Path:
    seed_id = seed_id or f"{dimension}.cache_consistency"
    variant_id = variant_id or f"{seed_id}.flash_sale_inventory"
    path = root / (file_name or f"{dimension}.yaml")
    path.write_text(
        f"""
dimension: {dimension}
seeds:
  - id: {seed_id}
    version: 1
    title: 缓存一致性
    dimension: {dimension}
    job_levels: [Mid, Senior]
    skill_tags: [Redis Cache, Consistency]
    direction_tags: [Internet Tech]
    role_tags: [Java Backend]
    rubric:
      must_cover: [失效策略, 一致性权衡]
      minimum_bar: 能说清楚缓存与数据库一致性的取舍
    priority: 20
    status: {status}
    source: manual_yaml
    scope: global
    language: zh-CN
    variants:
      - id: {variant_id}
        version: 1
        intent: opening
        difficulty: standard
        scenario_brief: 秒杀库存读多写少，缓存和数据库可能短暂不一致。
        question_stem: 请设计库存缓存与扣减一致性方案。
        prompt_template: 围绕候选人的缓存经验生成一道系统设计题。
        scenario_skill_tags: [Redis, Inventory-Service]
        resume_anchor_hints: [Redis, 缓存]
        failure_categories: [Missing Tradeoff, missing_metrics]
        rubric_additions: [说明缓存失效窗口]
        expected_signals: [能区分强一致与最终一致]
        anti_patterns: [只说加锁，不讨论吞吐]
        good_answer_hints: [给出降级和补偿路径]
        priority: 10
        status: active
""".lstrip(),
        encoding="utf-8",
    )
    return path


def test_import_question_seed_dir_imports_supported_dimensions_and_normalizes_tags(
    tmp_path: Path,
) -> None:
    seed_dir = tmp_path / "question_seeds"
    seed_dir.mkdir()
    _seed_file(seed_dir, "system_design")
    _seed_file(
        seed_dir,
        "technical_depth",
        seed_id="technical_depth.java_cache_internals",
        variant_id="technical_depth.java_cache_internals.redis_consistency",
    )

    session_local = _session_factory()
    with session_local() as sess:
        result = import_question_seed_dir(seed_dir, session=sess)
        sess.commit()
        seeds = list(sess.scalars(select(QuestionSeed).order_by(QuestionSeed.id)))
        variants = list(sess.scalars(select(QuestionVariant).order_by(QuestionVariant.id)))

    assert result.imported_seeds == 2
    assert result.imported_variants == 2
    assert result.updated_seeds == 0
    assert result.updated_variants == 0
    assert [seed.dimension for seed in seeds] == ["system_design", "technical_depth"]
    assert seeds[1].skill_tags == ["redis_cache", "consistency"]
    assert seeds[1].direction_tags == ["internet_tech"]
    assert seeds[1].role_tags == ["java_backend"]
    assert seeds[1].job_levels == ["mid", "senior"]
    assert variants[1].role_tags == ["java_backend"]
    assert variants[1].scenario_skill_tags == ["redis", "inventory_service"]
    assert variants[1].failure_categories == ["missing_tradeoff", "missing_metrics"]


def test_import_question_seed_dir_imports_optional_reviewed_acceptance_checks(
    tmp_path: Path,
) -> None:
    seed_dir = tmp_path / "question_seeds"
    seed_dir.mkdir()
    (seed_dir / "system_design.yaml").write_text(
        """
dimension: system_design
seeds:
  - id: system_design.cache_consistency
    version: 3
    title: Cache consistency
    dimension: system_design
    job_levels: [senior]
    skill_tags: [redis]
    direction_tags: [internet_tech]
    role_tags: [java_backend]
    rubric:
      must_cover: [consistency target]
      minimum_bar: Explains the consistency target.
    priority: 20
    status: active
    source: manual_yaml
    scope: global
    language: zh-CN
    variants:
      - id: system_design.cache_consistency.flash_sale_inventory
        version: 7
        intent: opening
        difficulty: standard
        scenario_brief: Flash sale inventory reads are cache-heavy.
        question_stem: Design a cache consistency approach.
        prompt_template: Ask one system design question.
        scenario_skill_tags: [redis]
        resume_anchor_hints: [cache]
        failure_categories: [missing_metrics]
        rubric_additions: [mentions invalidation window]
        expected_signals: [distinguishes strong and eventual consistency]
        anti_patterns: [only says add lock]
        good_answer_hints: [define consistency target first]
        reviewed_acceptance_checks:
          - check_id: reviewed:cache-consistency:core:v1
            source: must_cover
            source_text: consistency target
            acceptance_check: Answer defines the target consistency level.
            severity: core
            review_status: reviewed
            version: 1
            reviewed_seed_version: 3
            reviewed_variant_version: 7
            reviewed_by: qa-lead
            reviewed_at: "2026-06-01"
        priority: 10
        status: active
""".lstrip(),
        encoding="utf-8",
    )

    session_local = _session_factory()
    with session_local() as sess:
        import_question_seed_dir(seed_dir, session=sess)
        variant = sess.get(
            QuestionVariant,
            "system_design.cache_consistency.flash_sale_inventory",
        )

    assert variant is not None
    assert variant.reviewed_acceptance_checks == [
        {
            "check_id": "reviewed:cache-consistency:core:v1",
            "source": "must_cover",
            "source_text": "consistency target",
            "acceptance_check": "Answer defines the target consistency level.",
            "severity": "core",
            "review_status": "reviewed",
            "version": 1,
            "reviewed_seed_version": 3,
            "reviewed_variant_version": 7,
            "reviewed_by": "qa-lead",
            "reviewed_at": "2026-06-01",
        }
    ]


def test_import_question_seed_dir_fails_atomically_with_full_error_list(
    tmp_path: Path,
) -> None:
    seed_dir = tmp_path / "question_seeds"
    seed_dir.mkdir()
    _seed_file(seed_dir, "system_design")

    duplicate_file = seed_dir / "technical_depth.yaml"
    duplicate_file.write_text(
        """
dimension: technical_depth
seeds:
  - id: system_design.cache_consistency
    version: 1
    title: 重复题
    dimension: technical_depth
    job_levels: [senior]
    skill_tags: [api]
    direction_tags: [internet_tech]
    role_tags: [java_backend]
    rubric: {}
    priority: 1
    status: active
    source: manual_yaml
    scope: global
    language: zh-CN
    variants:
      - id: system_design.cache_consistency.flash_sale_inventory
        version: 1
        intent: typo_intent
        difficulty: standard
        scenario_brief: x
        question_stem: x
        prompt_template: x
        scenario_skill_tags: []
        resume_anchor_hints: []
        failure_categories: []
        rubric_additions: []
        expected_signals: []
        anti_patterns: []
        good_answer_hints: []
        priority: 1
        status: active
""".lstrip(),
        encoding="utf-8",
    )

    session_local = _session_factory()
    with session_local() as sess:
        with pytest.raises(QuestionSeedImportError) as exc:
            import_question_seed_dir(seed_dir, session=sess)
        sess.commit()
        seeds = list(sess.scalars(select(QuestionSeed)))

    message = "\n".join(exc.value.errors)
    assert "duplicate seed id: system_design.cache_consistency" in message
    assert "duplicate variant id: system_design.cache_consistency.flash_sale_inventory" in message
    assert "invalid intent" in message
    assert seeds == []


def test_import_question_seed_dir_rejects_file_dimension_mismatch(
    tmp_path: Path,
) -> None:
    seed_dir = tmp_path / "question_seeds"
    seed_dir.mkdir()
    _seed_file(seed_dir, "system_design", file_name="technical_depth.yaml")

    session_local = _session_factory()
    with session_local() as sess:
        with pytest.raises(QuestionSeedImportError) as exc:
            import_question_seed_dir(seed_dir, session=sess)

    assert "file/dimension mismatch" in "\n".join(exc.value.errors)


def test_import_question_seed_dir_rejects_unsupported_yaml_file_name(
    tmp_path: Path,
) -> None:
    seed_dir = tmp_path / "question_seeds"
    seed_dir.mkdir()
    _seed_file(seed_dir, "system_design", file_name="misc.yaml")

    session_local = _session_factory()
    with session_local() as sess:
        with pytest.raises(QuestionSeedImportError) as exc:
            import_question_seed_dir(seed_dir, session=sess)

    assert "unsupported question seed file" in "\n".join(exc.value.errors)


def test_import_question_seed_dir_rejects_backend_systems_dimension(
    tmp_path: Path,
) -> None:
    seed_dir = tmp_path / "question_seeds"
    seed_dir.mkdir()
    _seed_file(seed_dir, "backend_systems", file_name="backend_systems.yaml")

    session_local = _session_factory()
    with session_local() as sess:
        with pytest.raises(QuestionSeedImportError) as exc:
            import_question_seed_dir(seed_dir, session=sess)

    message = "\n".join(exc.value.errors)
    assert "unsupported question seed file" in message
    assert "invalid dimension: backend_systems" in message


def test_import_question_seed_dir_rejects_non_global_scope_in_p0(
    tmp_path: Path,
) -> None:
    seed_dir = tmp_path / "question_seeds"
    seed_dir.mkdir()
    path = _seed_file(seed_dir, "system_design")
    path.write_text(
        path.read_text(encoding="utf-8").replace("    scope: global", "    scope: org"),
        encoding="utf-8",
    )

    session_local = _session_factory()
    with session_local() as sess:
        with pytest.raises(QuestionSeedImportError) as exc:
            import_question_seed_dir(seed_dir, session=sess)

    assert "P0 only supports scope=global" in "\n".join(exc.value.errors)


def test_import_question_seed_dir_rejects_missing_required_variant_field(
    tmp_path: Path,
) -> None:
    seed_dir = tmp_path / "question_seeds"
    seed_dir.mkdir()
    path = _seed_file(seed_dir, "system_design")
    text = path.read_text(encoding="utf-8")
    path.write_text(
        "\n".join(line for line in text.splitlines() if "prompt_template:" not in line)
        + "\n",
        encoding="utf-8",
    )

    session_local = _session_factory()
    with session_local() as sess:
        with pytest.raises(QuestionSeedImportError) as exc:
            import_question_seed_dir(seed_dir, session=sess)

    assert "missing required field: prompt_template" in "\n".join(exc.value.errors)


def test_import_question_seed_dir_rejects_missing_required_role_tags(
    tmp_path: Path,
) -> None:
    seed_dir = tmp_path / "question_seeds"
    seed_dir.mkdir()
    path = _seed_file(seed_dir, "system_design")
    text = path.read_text(encoding="utf-8")
    path.write_text(
        "\n".join(
            line
            for line in text.splitlines()
            if "direction_tags:" not in line and "role_tags:" not in line
        )
        + "\n",
        encoding="utf-8",
    )

    session_local = _session_factory()
    with session_local() as sess:
        with pytest.raises(QuestionSeedImportError) as exc:
            import_question_seed_dir(seed_dir, session=sess)

    message = "\n".join(exc.value.errors)
    assert "missing required field: direction_tags" in message
    assert "missing required field: role_tags" in message


def test_import_question_seed_dir_rejects_duplicate_role_tags(
    tmp_path: Path,
) -> None:
    seed_dir = tmp_path / "question_seeds"
    seed_dir.mkdir()
    path = _seed_file(seed_dir, "system_design")
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "    role_tags: [Java Backend]",
            "    role_tags: [Java Backend, java-backend]",
        ),
        encoding="utf-8",
    )

    session_local = _session_factory()
    with session_local() as sess:
        with pytest.raises(QuestionSeedImportError) as exc:
            import_question_seed_dir(seed_dir, session=sess)

    assert "duplicate role_tags" in "\n".join(exc.value.errors)


def test_import_question_seed_dir_allows_variant_role_override(
    tmp_path: Path,
) -> None:
    seed_dir = tmp_path / "question_seeds"
    seed_dir.mkdir()
    path = _seed_file(seed_dir, "system_design")
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "        scenario_skill_tags: [Redis, Inventory-Service]",
            "        role_tags: [frontend-web]\n"
            "        scenario_skill_tags: [Redis, Inventory-Service]",
        ),
        encoding="utf-8",
    )

    session_local = _session_factory()
    with session_local() as sess:
        import_question_seed_dir(seed_dir, session=sess)
        variant = sess.get(
            QuestionVariant,
            "system_design.cache_consistency.flash_sale_inventory",
        )

    assert variant is not None
    assert variant.role_tags == ["frontend_web"]


def test_import_question_seed_dir_rejects_explicit_variant_parent_mismatch(
    tmp_path: Path,
) -> None:
    seed_dir = tmp_path / "question_seeds"
    seed_dir.mkdir()
    path = _seed_file(seed_dir, "system_design")
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "      - id: system_design.cache_consistency.flash_sale_inventory\n",
            (
                "      - id: system_design.cache_consistency.flash_sale_inventory\n"
                "        seed_id: system_design.other_seed\n"
            ),
        ),
        encoding="utf-8",
    )

    session_local = _session_factory()
    with session_local() as sess:
        with pytest.raises(QuestionSeedImportError) as exc:
            import_question_seed_dir(seed_dir, session=sess)

    assert "invalid parent seed reference: system_design.other_seed" in "\n".join(
        exc.value.errors
    )


def test_import_question_seed_dir_archive_missing_marks_absent_rows_archived(
    tmp_path: Path,
) -> None:
    seed_dir = tmp_path / "question_seeds"
    seed_dir.mkdir()
    _seed_file(seed_dir, "system_design")
    _seed_file(
        seed_dir,
        "technical_depth",
        seed_id="technical_depth.java_idempotent_api",
        variant_id="technical_depth.java_idempotent_api.payment_retry",
    )

    session_local = _session_factory()
    with session_local() as sess:
        import_question_seed_dir(seed_dir, session=sess)
        (seed_dir / "technical_depth.yaml").unlink()

        result = import_question_seed_dir(seed_dir, session=sess, archive_missing=True)
        archived_seed = sess.get(QuestionSeed, "technical_depth.java_idempotent_api")
        archived_variant = sess.get(
            QuestionVariant,
            "technical_depth.java_idempotent_api.payment_retry",
        )

    assert result.archived_seeds == 1
    assert result.archived_variants == 1
    assert archived_seed is not None
    assert archived_seed.status == "archived"
    assert archived_variant is not None
    assert archived_variant.status == "archived"


def test_import_question_seed_dir_archive_missing_can_archive_only_absent_variant(
    tmp_path: Path,
) -> None:
    seed_dir = tmp_path / "question_seeds"
    seed_dir.mkdir()
    path = _seed_file(seed_dir, "system_design")
    text = path.read_text(encoding="utf-8")
    path.write_text(
        text
        + """
      - id: system_design.cache_consistency.deep_probe
        version: 1
        intent: deep_probe
        difficulty: deep_probe
        scenario_brief: Probe cache consistency under failure.
        question_stem: How would you verify consistency after Redis failover?
        prompt_template: Generate a deep probe around Redis failover consistency.
        scenario_skill_tags: [Redis]
        resume_anchor_hints: [Redis]
        failure_categories: [missing_metrics]
        rubric_additions: [Explain verification signals]
        expected_signals: [Mentions reconciliation]
        anti_patterns: [Only says retry]
        good_answer_hints: [Discuss detection and repair]
        priority: 5
        status: active
""",
        encoding="utf-8",
    )

    session_local = _session_factory()
    with session_local() as sess:
        import_question_seed_dir(seed_dir, session=sess)
        path.write_text(text, encoding="utf-8")

        result = import_question_seed_dir(seed_dir, session=sess, archive_missing=True)
        seed = sess.get(QuestionSeed, "system_design.cache_consistency")
        archived_variant = sess.get(QuestionVariant, "system_design.cache_consistency.deep_probe")

    assert result.archived_seeds == 0
    assert result.archived_variants == 1
    assert seed is not None
    assert seed.status == "active"
    assert archived_variant is not None
    assert archived_variant.status == "archived"


def test_import_question_seed_dir_imports_bundled_p0_yaml() -> None:
    seed_dir = Path(__file__).resolve().parents[2] / "knowledge" / "question_seeds"

    session_local = _session_factory()
    with session_local() as sess:
        result = import_question_seed_dir(seed_dir, session=sess)
        seeds = list(sess.scalars(select(QuestionSeed).order_by(QuestionSeed.id)))
        variants = list(sess.scalars(select(QuestionVariant).order_by(QuestionVariant.id)))

    assert result.imported_seeds >= 10
    assert result.imported_variants >= 20
    assert "backend_systems" not in {seed.dimension for seed in seeds}
    assert {"system_design", "technical_depth", "problem_solving"}.issubset(
        {seed.dimension for seed in seeds}
    )
    assert all(seed.scope == "global" for seed in seeds)
    assert all(seed.language == "zh-CN" for seed in seeds)
    assert all(seed.direction_tags for seed in seeds)
    assert all(seed.role_tags for seed in seeds)
    assert {"java_backend", "frontend_web", "sre"}.issubset(
        {role for seed in seeds for role in seed.role_tags}
    )
    java_seeds = [seed for seed in seeds if "java_backend" in set(seed.role_tags or [])]
    java_dimensions = {seed.dimension for seed in java_seeds}
    assert {
        "technical_depth",
        "system_design",
        "problem_solving",
        "coding_quality",
        "project_experience",
        "communication",
    }.issubset(java_dimensions)
    assert all("junior" in set(seed.job_levels or []) for seed in java_seeds)
    assert all(variant.seed_id in {seed.id for seed in seeds} for variant in variants)
    active_counts = {
        seed.id: sum(
            1
            for variant in variants
            if variant.seed_id == seed.id and variant.status == "active"
        )
        for seed in seeds
    }
    assert all(count >= 2 for count in active_counts.values())


def test_import_question_seed_dir_imports_bundled_batch2_roles_and_dimensions() -> None:
    seed_dir = Path(__file__).resolve().parents[2] / "knowledge" / "question_seeds"

    session_local = _session_factory()
    with session_local() as sess:
        import_question_seed_dir(seed_dir, session=sess)
        seeds = list(sess.scalars(select(QuestionSeed).order_by(QuestionSeed.id)))
        variants = list(sess.scalars(select(QuestionVariant).order_by(QuestionVariant.id)))

    roles = {role for seed in seeds for role in seed.role_tags}
    dimensions = {seed.dimension for seed in seeds}
    assert {
        "ai_agent",
        "ai_fullstack",
        "mobile",
        "ai_algorithm",
        "architect",
    }.issubset(roles)
    assert {
        "project_experience",
        "product_thinking",
        "leadership",
        "communication",
    }.issubset(dimensions)
    assert len(seeds) >= 45
    assert len(variants) >= 90

    active_counts = {
        seed.id: sum(
            1
            for variant in variants
            if variant.seed_id == seed.id and variant.status == "active"
        )
        for seed in seeds
    }
    assert all(count >= 2 for count in active_counts.values())


def test_import_question_seed_dir_aligns_internet_tech_roles_to_mainline_catalogs() -> None:
    seed_dir = Path(__file__).resolve().parents[2] / "knowledge" / "question_seeds"
    role_catalogs = {
        "frontend_web": {
            "technical_depth",
            "coding_quality",
            "problem_solving",
            "project_experience",
            "product_thinking",
            "communication",
        },
        "sre": {
            "technical_depth",
            "system_design",
            "problem_solving",
            "project_experience",
            "communication",
        },
        "ai_fullstack": {
            "technical_depth",
            "system_design",
            "product_thinking",
            "project_experience",
            "problem_solving",
            "communication",
        },
        "ai_agent": {
            "technical_depth",
            "system_design",
            "problem_solving",
            "product_thinking",
            "communication",
        },
        "mobile": {
            "technical_depth",
            "problem_solving",
            "coding_quality",
            "project_experience",
            "communication",
        },
        "ai_algorithm": {
            "technical_depth",
            "problem_solving",
            "project_experience",
            "product_thinking",
            "communication",
        },
        "architect": {
            "system_design",
            "technical_depth",
            "leadership",
            "problem_solving",
            "communication",
        },
    }
    non_architect_roles = set(role_catalogs) - {"architect"}

    session_local = _session_factory()
    with session_local() as sess:
        import_question_seed_dir(seed_dir, session=sess)
        seeds = list(sess.scalars(select(QuestionSeed).order_by(QuestionSeed.id)))

    for role, catalog in role_catalogs.items():
        role_seeds = [seed for seed in seeds if role in set(seed.role_tags or [])]
        role_dimensions = {seed.dimension for seed in role_seeds if seed.status == "active"}
        assert catalog <= role_dimensions, role
        assert not (role_dimensions - catalog), role
        if role in non_architect_roles:
            assert all(
                {"junior", "mid", "senior"} <= set(seed.job_levels or [])
                for seed in role_seeds
                if seed.status == "active"
            ), role


def test_import_question_seed_dir_imports_bundled_business_roles_and_dimensions() -> None:
    seed_dir = Path(__file__).resolve().parents[2] / "knowledge" / "question_seeds"

    session_local = _session_factory()
    with session_local() as sess:
        import_question_seed_dir(seed_dir, session=sess)
        seeds = list(sess.scalars(select(QuestionSeed).order_by(QuestionSeed.id)))
        variants = list(sess.scalars(select(QuestionVariant).order_by(QuestionVariant.id)))

    roles = {role for seed in seeds for role in seed.role_tags}
    dimensions = {seed.dimension for seed in seeds}
    assert {
        "product_manager",
        "operations",
        "sales_business",
        "marketing_brand",
        "hr_function",
        "customer_success",
        "general_management",
    }.issubset(roles)
    assert {
        "user_insight",
        "requirement_analysis",
        "prioritization",
        "metrics_thinking",
        "stakeholder_management",
        "user_growth",
        "content_operations",
        "data_analysis",
        "campaign_execution",
        "process_optimization",
        "customer_discovery",
        "solution_matching",
        "objection_handling",
        "negotiation",
        "pipeline_management",
        "market_insight",
        "brand_strategy",
        "campaign_planning",
        "channel_growth",
        "content_creativity",
        "talent_acquisition",
        "employee_relations",
        "organization_development",
        "policy_compliance",
        "service_orientation",
        "customer_empathy",
        "issue_diagnosis",
        "solution_delivery",
        "escalation_management",
        "retention_growth",
        "goal_setting",
        "team_leadership",
        "decision_making",
        "execution_management",
        "cross_functional_alignment",
    }.issubset(dimensions)

    business_seeds = [
        seed for seed in seeds if "business" in set(seed.direction_tags or [])
    ]
    business_variants = [
        variant
        for variant in variants
        if any(seed.id == variant.seed_id for seed in business_seeds)
    ]
    assert len(business_seeds) == 35
    assert len(business_variants) == 70
    assert all(seed.scope == "global" for seed in business_seeds)
    assert all(seed.language == "zh-CN" for seed in business_seeds)
    assert all(seed.direction_tags == ["business"] for seed in business_seeds)
    assert all(
        {"junior", "mid", "senior"} <= set(seed.job_levels or [])
        for seed in business_seeds
    )


def test_import_question_seed_dir_aligns_business_roles_to_mainline_catalogs() -> None:
    seed_dir = Path(__file__).resolve().parents[2] / "knowledge" / "question_seeds"
    role_dimensions = {
        "product_manager": {
            "user_insight",
            "requirement_analysis",
            "prioritization",
            "metrics_thinking",
            "stakeholder_management",
        },
        "operations": {
            "user_growth",
            "content_operations",
            "data_analysis",
            "campaign_execution",
            "process_optimization",
        },
        "sales_business": {
            "customer_discovery",
            "solution_matching",
            "objection_handling",
            "negotiation",
            "pipeline_management",
        },
        "marketing_brand": {
            "market_insight",
            "brand_strategy",
            "campaign_planning",
            "channel_growth",
            "content_creativity",
        },
        "hr_function": {
            "talent_acquisition",
            "employee_relations",
            "organization_development",
            "policy_compliance",
            "service_orientation",
        },
        "customer_success": {
            "customer_empathy",
            "issue_diagnosis",
            "solution_delivery",
            "escalation_management",
            "retention_growth",
        },
        "general_management": {
            "goal_setting",
            "team_leadership",
            "decision_making",
            "execution_management",
            "cross_functional_alignment",
        },
    }

    session_local = _session_factory()
    with session_local() as sess:
        import_question_seed_dir(seed_dir, session=sess)
        seeds = list(sess.scalars(select(QuestionSeed).order_by(QuestionSeed.id)))

    for role, expected_dimensions in role_dimensions.items():
        role_seeds = [
            seed
            for seed in seeds
            if seed.status == "active" and role in set(seed.role_tags or [])
        ]
        assert {seed.dimension for seed in role_seeds} == expected_dimensions
        assert all(seed.direction_tags == ["business"] for seed in role_seeds)
        assert all(
            {"junior", "mid", "senior"} <= set(seed.job_levels or [])
            for seed in role_seeds
        )


def test_import_question_seed_dir_rejects_dimension_outside_tech_catalog(
    tmp_path: Path,
) -> None:
    seed_dir = tmp_path / "question_seeds"
    seed_dir.mkdir()
    _seed_file(seed_dir, "model_evaluation", file_name="model_evaluation.yaml")

    session_local = _session_factory()
    with session_local() as sess:
        with pytest.raises(QuestionSeedImportError) as exc:
            import_question_seed_dir(seed_dir, session=sess)

    assert "unsupported question seed file" in "\n".join(exc.value.errors)


def test_import_question_seeds_script_uses_question_seed_dir(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from app.scripts import import_question_seeds

    calls: dict[str, object] = {}

    monkeypatch.setattr(
        import_question_seeds,
        "get_settings",
        lambda: SimpleNamespace(knowledge_dir=str(tmp_path / "knowledge")),
    )
    monkeypatch.setattr(
        import_question_seeds,
        "init_db",
        lambda: calls.setdefault("init_db", True),
    )

    @contextmanager
    def fake_get_session():
        yield "session"

    def fake_import(seed_dir: Path, *, session, archive_missing: bool):
        calls["seed_dir"] = seed_dir
        calls["session"] = session
        calls["archive_missing"] = archive_missing
        return SimpleNamespace(
            imported_seeds=1,
            updated_seeds=2,
            unchanged_seeds=3,
            imported_variants=4,
            updated_variants=5,
            unchanged_variants=6,
            archived_seeds=7,
            archived_variants=8,
        )

    monkeypatch.setattr(import_question_seeds, "get_session", fake_get_session)
    monkeypatch.setattr(import_question_seeds, "import_question_seed_dir", fake_import)

    import_question_seeds.main(archive_missing=True)

    assert calls["init_db"] is True
    assert calls["seed_dir"] == tmp_path / "knowledge" / "question_seeds"
    assert calls["session"] == "session"
    assert calls["archive_missing"] is True
