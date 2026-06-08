from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
from app.models.question_bank import (
    QuestionRewardRollout,
    QuestionSeed,
    QuestionUsageStats,
    QuestionVariant,
)
from app.services import question_selector
from app.services.question_fit_profile import QuestionFitProfile, build_question_fit_profile
from app.services.question_seed_import import import_question_seed_dir
from app.services.question_selector import select_question_candidates


def _session_factory():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)


def _add_seed(
    sess,
    seed_id: str,
    *,
    dimension: str = "system_design",
    job_levels: list[str] | None = None,
    skill_tags: list[str] | None = None,
    failure_categories: list[str] | None = None,
    resume_anchor_hints: list[str] | None = None,
    intent: str = "opening",
    difficulty: str = "standard",
    seed_priority: int = 10,
    variant_priority: int = 10,
    seed_status: str = "active",
    variant_status: str = "active",
    scope: str = "global",
    variant_id: str | None = None,
    direction_tags: list[str] | None = None,
    role_tags: list[str] | None = None,
    variant_role_tags: list[str] | None = None,
    reviewed_acceptance_checks: list[dict] | None = None,
) -> str:
    variant_id = variant_id or f"{seed_id}.{intent}"
    sess.add(
        QuestionSeed(
            id=seed_id,
            version=1,
            title=seed_id,
            dimension=dimension,
            job_levels=job_levels or ["senior"],
            skill_tags=skill_tags or [],
            direction_tags=direction_tags or ["internet_tech"],
            role_tags=role_tags or ["java_backend"],
            rubric={"must_cover": ["x"]},
            priority=seed_priority,
            status=seed_status,
            source="manual_yaml",
            scope=scope,
            language="zh-CN",
        )
    )
    variant_values = {
        "id": variant_id,
        "seed_id": seed_id,
        "version": 1,
        "intent": intent,
        "difficulty": difficulty,
        "scenario_brief": f"scenario for {variant_id}",
        "question_stem": f"question for {variant_id}",
        "prompt_template": f"prompt for {variant_id}",
        "scenario_skill_tags": skill_tags or [],
        "resume_anchor_hints": resume_anchor_hints or [],
        "failure_categories": failure_categories or [],
        "rubric_additions": ["addition"],
        "expected_signals": ["signal"],
        "anti_patterns": ["anti"],
        "good_answer_hints": ["hint"],
        "role_tags": variant_role_tags or role_tags or ["java_backend"],
        "priority": variant_priority,
        "status": variant_status,
    }
    if reviewed_acceptance_checks is not None:
        variant_values["reviewed_acceptance_checks"] = reviewed_acceptance_checks
    sess.add(QuestionVariant(**variant_values))
    return variant_id


def test_question_seed_contract_hints_include_seed_and_variant_versions() -> None:
    candidate = question_selector.QuestionCandidate(
        seed_id="system_design.cache_consistency",
        variant_id="system_design.cache_consistency.flash_sale_inventory",
        seed_version=3,
        variant_version=7,
        rank=1,
        match_score=42.0,
        match_reasons=["priority"],
        injected=True,
        title="Cache consistency",
        dimension="system_design",
        seed_priority=30,
        variant_priority=20,
        skill_tags=["redis"],
        direction_tags=["internet_tech"],
        role_tags=["java_backend"],
        rubric={"must_cover": ["consistency target"]},
        intent="opening",
        difficulty="standard",
        scenario_brief="Flash-sale inventory reads are cache-heavy.",
        question_stem="Design a cache consistency approach.",
        prompt_template="Ask a system design question.",
        scenario_skill_tags=["redis"],
        resume_anchor_hints=["cache"],
        failure_categories=["missing_metrics"],
        rubric_additions=["mentions invalidation window"],
        expected_signals=["distinguishes strong and eventual consistency"],
        anti_patterns=["only says add lock"],
        good_answer_hints=["define consistency target first"],
        reviewed_acceptance_checks=[
            {
                "check_id": "reviewed:cache-consistency:core:v1",
                "acceptance_check": "Answer defines the target consistency level.",
                "review_status": "reviewed",
            }
        ],
    )

    hints = question_selector.build_question_seed_contract_hints(candidate)

    assert hints["question_seed"]["seed_version"] == 3
    assert hints["question_seed"]["variant_version"] == 7
    assert hints["question_seed"]["rubric"] == {"must_cover": ["consistency target"]}
    assert hints["question_seed"]["reviewed_acceptance_checks"][0]["check_id"] == (
        "reviewed:cache-consistency:core:v1"
    )


def test_select_question_candidates_carries_reviewed_acceptance_checks() -> None:
    reviewed_checks = [
        {
            "check_id": "reviewed:cache-consistency:core:v1",
            "source": "must_cover",
            "source_text": "consistency target",
            "acceptance_check": "Answer defines the target consistency level.",
            "severity": "core",
            "review_status": "reviewed",
            "version": 1,
            "reviewed_seed_version": 1,
            "reviewed_variant_version": 1,
            "reviewed_by": "qa-lead",
            "reviewed_at": "2026-06-01",
        }
    ]
    session_local = _session_factory()
    with session_local() as sess:
        _add_seed(
            sess,
            "system_design.reviewed",
            skill_tags=["redis"],
            reviewed_acceptance_checks=reviewed_checks,
        )
        sess.commit()

        result = select_question_candidates(
            sess,
            dimension="system_design",
            job_level="senior",
            probe_intent="opening",
            top_k=1,
        )

    candidate = result.candidates[0]
    assert candidate.reviewed_acceptance_checks == reviewed_checks


def test_selector_hard_filters_status_scope_dimension_and_job_level() -> None:
    session_local = _session_factory()
    with session_local() as sess:
        good_variant = _add_seed(sess, "system_design.good", skill_tags=["redis"])
        _add_seed(sess, "system_design.disabled_seed", seed_status="disabled")
        _add_seed(sess, "system_design.archived_seed", seed_status="archived")
        _add_seed(sess, "system_design.draft_variant", variant_status="draft")
        _add_seed(sess, "system_design.archived_variant", variant_status="archived")
        _add_seed(sess, "backend_systems.wrong_dimension", dimension="backend_systems")
        _add_seed(sess, "system_design.wrong_level", job_levels=["junior"])
        _add_seed(sess, "system_design.org_scope", scope="org")
        sess.commit()

        result = select_question_candidates(
            sess,
            dimension="system_design",
            job_level="senior",
            probe_intent="opening",
            top_k=3,
        )

    assert [candidate.variant_id for candidate in result.candidates] == [good_variant]
    assert result.candidates[0].rank == 1


def test_selector_breaks_ties_deterministically_after_seed_diversity() -> None:
    session_local = _session_factory()
    with session_local() as sess:
        _add_seed(
            sess,
            "system_design.beta",
            skill_tags=["redis"],
            seed_priority=10,
            variant_priority=10,
            variant_id="system_design.beta.opening",
        )
        _add_seed(
            sess,
            "system_design.alpha",
            skill_tags=["redis"],
            seed_priority=10,
            variant_priority=10,
            variant_id="system_design.alpha.opening",
        )
        sess.add(
            QuestionVariant(
                id="system_design.alpha.alt_opening",
                seed_id="system_design.alpha",
                version=1,
                intent="opening",
                difficulty="standard",
                scenario_brief="alternate alpha scenario",
                question_stem="alternate alpha question",
                prompt_template="alternate alpha prompt",
                scenario_skill_tags=["redis"],
                resume_anchor_hints=[],
                failure_categories=[],
                rubric_additions=["addition"],
                expected_signals=["signal"],
                anti_patterns=["anti"],
                good_answer_hints=["hint"],
                role_tags=["java_backend"],
                priority=10,
                status="active",
            )
        )
        sess.commit()

        result = select_question_candidates(
            sess,
            dimension="system_design",
            job_level="senior",
            target_skills=["redis"],
            probe_intent="opening",
            top_k=3,
        )

    assert [candidate.variant_id for candidate in result.candidates] == [
        "system_design.alpha.alt_opening",
        "system_design.beta.opening",
        "system_design.alpha.opening",
    ]
    assert [candidate.rank for candidate in result.candidates] == [1, 2, 3]


def test_selector_prefers_distinct_seed_ids_in_top_k_when_available() -> None:
    session_local = _session_factory()
    with session_local() as sess:
        _add_seed(
            sess,
            "system_design.alpha",
            skill_tags=["redis"],
            seed_priority=10,
            variant_priority=10,
            variant_id="system_design.alpha.opening",
        )
        sess.add(
            QuestionVariant(
                id="system_design.alpha.alt_opening",
                seed_id="system_design.alpha",
                version=1,
                intent="opening",
                difficulty="standard",
                scenario_brief="alternate alpha scenario",
                question_stem="alternate alpha question",
                prompt_template="alternate alpha prompt",
                scenario_skill_tags=["redis"],
                resume_anchor_hints=[],
                failure_categories=[],
                rubric_additions=["addition"],
                expected_signals=["signal"],
                anti_patterns=["anti"],
                good_answer_hints=["hint"],
                role_tags=["java_backend"],
                priority=10,
                status="active",
            )
        )
        _add_seed(
            sess,
            "system_design.beta",
            skill_tags=["redis"],
            seed_priority=10,
            variant_priority=10,
            variant_id="system_design.beta.opening",
        )
        _add_seed(
            sess,
            "system_design.gamma",
            skill_tags=["redis"],
            seed_priority=10,
            variant_priority=10,
            variant_id="system_design.gamma.opening",
        )
        sess.commit()

        result = select_question_candidates(
            sess,
            dimension="system_design",
            job_level="senior",
            target_skills=["redis"],
            probe_intent="opening",
            top_k=3,
        )

    assert [candidate.seed_id for candidate in result.candidates] == [
        "system_design.alpha",
        "system_design.beta",
        "system_design.gamma",
    ]
    assert [candidate.variant_id for candidate in result.candidates] == [
        "system_design.alpha.alt_opening",
        "system_design.beta.opening",
        "system_design.gamma.opening",
    ]
    assert [candidate.rank for candidate in result.candidates] == [1, 2, 3]


def test_selector_adds_reward_shadow_rank_without_changing_candidate_order() -> None:
    session_local = _session_factory()
    with session_local() as sess:
        metadata_top = _add_seed(
            sess,
            "system_design.cache",
            seed_priority=20,
            variant_priority=20,
            variant_id="system_design.cache.opening",
        )
        reward_top = _add_seed(
            sess,
            "system_design.capacity",
            seed_priority=19,
            variant_priority=20,
            variant_id="system_design.capacity.opening",
        )
        sess.add_all(
            [
                QuestionUsageStats(
                    id="stats-cache",
                    variant_id=metadata_top,
                    question_selector_mode="structured_primary",
                    uses=3,
                    injected_uses=3,
                    rewarded_uses=3,
                    avg_score=6.0,
                    pass_rate=0.33,
                    avg_immediate_reward=0.2,
                ),
                QuestionUsageStats(
                    id="stats-capacity",
                    variant_id=reward_top,
                    question_selector_mode="structured_primary",
                    uses=20,
                    injected_uses=20,
                    rewarded_uses=20,
                    avg_score=9.0,
                    pass_rate=1.0,
                    avg_immediate_reward=0.95,
                ),
            ]
        )
        sess.commit()

        result = select_question_candidates(
            sess,
            dimension="system_design",
            job_level="senior",
            probe_intent="opening",
            question_selector_mode="structured_primary",
            top_k=2,
        )

    assert [candidate.variant_id for candidate in result.candidates] == [
        metadata_top,
        reward_top,
    ]
    artifacts = result.as_artifacts()
    by_variant = {item["variant_id"]: item for item in artifacts}
    assert by_variant[metadata_top]["reward_shadow_rank"] == 2
    assert by_variant[metadata_top]["reward_shadow_rank_changed"] is True
    assert by_variant[reward_top]["reward_shadow_rank"] == 1
    assert by_variant[reward_top]["usage_stats"]["rewarded_uses"] == 20
    assert by_variant[reward_top]["reward_shadow_reason"]["sample_confidence"] == 1.0


def test_selector_context_reward_override_reorders_seed_representatives_when_gate_passes() -> None:
    session_local = _session_factory()
    context_key = "internet_tech:java_backend:senior:system_design"
    with session_local() as sess:
        metadata_top = _add_seed(
            sess,
            "system_design.metadata_top",
            seed_priority=100,
            variant_priority=0,
            variant_id="system_design.metadata_top.opening",
        )
        reward_top = _add_seed(
            sess,
            "system_design.reward_top",
            seed_priority=90,
            variant_priority=0,
            variant_id="system_design.reward_top.opening",
        )
        filler_variants = [
            _add_seed(
                sess,
                f"system_design.filler_{idx}",
                seed_priority=80 - idx,
                variant_priority=0,
                variant_id=f"system_design.filler_{idx}.opening",
            )
            for idx in range(3)
        ]
        sess.add(
            QuestionRewardRollout(
                id=f"context:{context_key}",
                scope="context",
                scope_key=context_key,
                mode="reward",
                reason="pilot context",
            )
        )
        stats = [
            QuestionUsageStats(
                id="stats-metadata-top",
                variant_id=metadata_top,
                question_selector_mode="structured_primary",
                uses=20,
                injected_uses=20,
                rewarded_uses=20,
                avg_score=5.0,
                pass_rate=0.2,
                avg_immediate_reward=0.1,
            ),
            QuestionUsageStats(
                id="stats-reward-top",
                variant_id=reward_top,
                question_selector_mode="structured_shadow",
                uses=20,
                injected_uses=20,
                rewarded_uses=20,
                avg_score=9.0,
                pass_rate=1.0,
                avg_immediate_reward=1.0,
            ),
        ]
        stats.extend(
            QuestionUsageStats(
                id=f"stats-filler-{idx}",
                variant_id=variant_id,
                question_selector_mode="structured_primary",
                uses=20,
                injected_uses=20,
                rewarded_uses=20,
                avg_score=6.0,
                pass_rate=0.4,
                avg_immediate_reward=0.2,
            )
            for idx, variant_id in enumerate(filler_variants)
        )
        sess.add_all(stats)
        sess.commit()

        result = select_question_candidates(
            sess,
            dimension="system_design",
            job_level="senior",
            direction_tags=["internet_tech"],
            role_tags=["java_backend"],
            probe_intent="opening",
            question_selector_mode="structured_shadow",
            top_k=5,
        )

    assert result.candidates[0].variant_id == reward_top
    assert result.candidates[1].variant_id == metadata_top
    assert result.candidates[0].reward_shadow_reason["live_order"] == "reward"
    assert result.candidates[0].reward_shadow_reason["context_rollout_mode"] == "reward"


def test_selector_seed_reward_override_reorders_variants_inside_seed_when_gate_passes() -> None:
    session_local = _session_factory()
    with session_local() as sess:
        metadata_variant = _add_seed(
            sess,
            "system_design.multi_variant",
            seed_priority=100,
            variant_priority=20,
            variant_id="system_design.multi_variant.metadata",
        )
        reward_variant = "system_design.multi_variant.reward"
        sess.add(
            QuestionVariant(
                id=reward_variant,
                seed_id="system_design.multi_variant",
                version=1,
                intent="opening",
                difficulty="standard",
                scenario_brief="reward variant",
                question_stem="reward question",
                prompt_template="reward prompt",
                scenario_skill_tags=[],
                resume_anchor_hints=[],
                failure_categories=[],
                rubric_additions=[],
                expected_signals=[],
                anti_patterns=[],
                good_answer_hints=[],
                role_tags=["java_backend"],
                priority=10,
                status="active",
            )
        )
        sess.add_all(
            [
                QuestionRewardRollout(
                    id="seed:system_design.multi_variant",
                    scope="seed",
                    scope_key="system_design.multi_variant",
                    mode="reward",
                    reason="pilot seed",
                ),
                QuestionUsageStats(
                    id="stats-metadata-variant",
                    variant_id=metadata_variant,
                    question_selector_mode="structured_primary",
                    uses=20,
                    injected_uses=20,
                    rewarded_uses=20,
                    avg_score=5.0,
                    pass_rate=0.2,
                    avg_immediate_reward=0.1,
                ),
                QuestionUsageStats(
                    id="stats-reward-variant",
                    variant_id=reward_variant,
                    question_selector_mode="structured_primary",
                    uses=20,
                    injected_uses=20,
                    rewarded_uses=20,
                    avg_score=9.0,
                    pass_rate=1.0,
                    avg_immediate_reward=1.0,
                ),
            ]
        )
        sess.commit()

        result = select_question_candidates(
            sess,
            dimension="system_design",
            job_level="senior",
            direction_tags=["internet_tech"],
            role_tags=["java_backend"],
            probe_intent="opening",
            top_k=1,
        )

    assert result.candidates[0].variant_id == reward_variant
    assert result.candidates[0].reward_shadow_reason["seed_rollout_mode"] == "reward"
    assert result.candidates[0].reward_shadow_reason["seed_live_order"] == "reward"


def test_selector_reward_override_falls_back_to_metadata_when_context_gate_fails() -> None:
    session_local = _session_factory()
    context_key = "internet_tech:java_backend:senior:system_design"
    with session_local() as sess:
        metadata_top = _add_seed(
            sess,
            "system_design.metadata_small_pool",
            seed_priority=100,
            variant_priority=0,
            variant_id="system_design.metadata_small_pool.opening",
        )
        reward_top = _add_seed(
            sess,
            "system_design.reward_small_pool",
            seed_priority=90,
            variant_priority=0,
            variant_id="system_design.reward_small_pool.opening",
        )
        sess.add_all(
            [
                QuestionRewardRollout(
                    id=f"context:{context_key}",
                    scope="context",
                    scope_key=context_key,
                    mode="reward",
                    reason="pilot context",
                ),
                QuestionUsageStats(
                    id="stats-small-metadata",
                    variant_id=metadata_top,
                    question_selector_mode="structured_primary",
                    uses=3,
                    injected_uses=3,
                    rewarded_uses=3,
                    avg_score=5.0,
                    pass_rate=0.2,
                    avg_immediate_reward=0.1,
                ),
                QuestionUsageStats(
                    id="stats-small-reward",
                    variant_id=reward_top,
                    question_selector_mode="structured_primary",
                    uses=3,
                    injected_uses=3,
                    rewarded_uses=3,
                    avg_score=9.0,
                    pass_rate=1.0,
                    avg_immediate_reward=1.0,
                ),
            ]
        )
        sess.commit()

        result = select_question_candidates(
            sess,
            dimension="system_design",
            job_level="senior",
            direction_tags=["internet_tech"],
            role_tags=["java_backend"],
            probe_intent="opening",
            top_k=2,
        )

    assert [candidate.variant_id for candidate in result.candidates] == [
        metadata_top,
        reward_top,
    ]
    assert result.candidates[0].reward_shadow_reason["live_order"] == "metadata_fallback"
    assert "candidate_pool_below_min" in result.candidates[0].reward_shadow_reason["gate_reasons"]
    assert "reward_samples_below_min" in result.candidates[0].reward_shadow_reason["gate_reasons"]


def test_selector_ranking_uses_tags_failures_resume_intent_difficulty_and_priority() -> None:
    session_local = _session_factory()
    with session_local() as sess:
        weaker = _add_seed(
            sess,
            "system_design.generic",
            skill_tags=["http"],
            seed_priority=40,
            variant_priority=10,
        )
        stronger = _add_seed(
            sess,
            "system_design.cache",
            skill_tags=["redis", "cache"],
            failure_categories=["missing_metrics"],
            resume_anchor_hints=["redis"],
            seed_priority=12,
            variant_priority=8,
        )
        sess.commit()

        result = select_question_candidates(
            sess,
            dimension="system_design",
            job_level="senior",
            target_skills=["Redis"],
            failure_categories=["missing metrics"],
            resume_anchor_text="候选人简历里写了 Redis 缓存治理经验。",
            probe_intent="opening",
            difficulty="standard",
            top_k=3,
        )

    assert [candidate.variant_id for candidate in result.candidates] == [stronger, weaker]
    top = result.candidates[0]
    assert top.rank == 1
    assert top.match_score > result.candidates[1].match_score
    assert "target_skill:redis" in top.match_reasons
    assert "scenario_skill:redis" in top.match_reasons
    assert "failure_category:missing_metrics" in top.match_reasons
    assert "resume_anchor:redis" in top.match_reasons
    assert "intent:opening" in top.match_reasons
    assert "difficulty:standard" in top.match_reasons


def test_selector_fit_profile_boosts_project_and_job_skill_fit() -> None:
    session_local = _session_factory()
    with session_local() as sess:
        generic = _add_seed(
            sess,
            "system_design.generic",
            skill_tags=["http"],
            seed_priority=45,
            variant_priority=10,
        )
        fitted = _add_seed(
            sess,
            "system_design.cache",
            skill_tags=["redis", "cache"],
            resume_anchor_hints=["redis", "inventory_service"],
            seed_priority=12,
            variant_priority=8,
        )
        sess.commit()

        profile = build_question_fit_profile(
            candidate={
                "resume_parsed": {
                    "projects": [
                        {
                            "name": "Inventory Service",
                            "tech_stack": ["Redis"],
                            "summary": "Cache-based stock reads.",
                        }
                    ]
                }
            },
            self_intro_profile={},
            job_spec={"required_skills": ["Redis", "Observability"]},
            target_skills=[],
            resume_anchor={
                "project_name": "Inventory Service",
                "tech_stack": ["Redis"],
            },
            pending_contract_hints=None,
            dimension="system_design",
            probe_intent="opening",
        )

        result = select_question_candidates(
            sess,
            dimension="system_design",
            job_level="senior",
            probe_intent="opening",
            fit_profile=profile,
            top_k=3,
        )

    assert [candidate.variant_id for candidate in result.candidates] == [fitted, generic]
    top = result.candidates[0]
    assert "candidate_project_fit:redis" in top.match_reasons
    assert "job_skill_fit:redis" in top.match_reasons
    assert top.fit_score > 0
    assert top.anchor_confidence == "high"


def test_selector_applies_light_generic_penalty_without_overriding_exact_fit() -> None:
    session_local = _session_factory()
    with session_local() as sess:
        generic = _add_seed(
            sess,
            "system_design.generic",
            skill_tags=[],
            seed_priority=50,
            variant_priority=0,
        )
        fitted = _add_seed(
            sess,
            "system_design.redis",
            skill_tags=["redis"],
            seed_priority=45,
            variant_priority=0,
        )
        sess.commit()

        empty_profile = build_question_fit_profile(
            candidate={"resume_parsed": {}},
            self_intro_profile={},
            job_spec={},
            target_skills=[],
            resume_anchor=None,
            pending_contract_hints=None,
            dimension="system_design",
            probe_intent="opening",
        )
        fitted_profile = build_question_fit_profile(
            candidate={"resume_parsed": {"projects": [{"name": "Cache", "tech_stack": ["Redis"]}]}},
            self_intro_profile={},
            job_spec={"required_skills": ["Redis"]},
            target_skills=["Redis"],
            resume_anchor={"project_name": "Cache", "tech_stack": ["Redis"]},
            pending_contract_hints=None,
            dimension="system_design",
            probe_intent="opening",
        )

        generic_result = select_question_candidates(
            sess,
            dimension="system_design",
            job_level="senior",
            probe_intent="opening",
            fit_profile=empty_profile,
            top_k=3,
        )
        fitted_result = select_question_candidates(
            sess,
            dimension="system_design",
            job_level="senior",
            probe_intent="opening",
            fit_profile=fitted_profile,
            top_k=3,
        )

    assert generic_result.candidates[0].variant_id == generic
    assert "generic_penalty:-4" in generic_result.candidates[0].match_reasons
    assert fitted_result.candidates[0].variant_id == fitted


def test_selector_prefers_matching_role_and_excludes_mismatched_when_role_pack_exists() -> None:
    session_local = _session_factory()
    with session_local() as sess:
        java = _add_seed(
            sess,
            "system_design.java_cache",
            role_tags=["java_backend"],
            skill_tags=["redis"],
            seed_priority=80,
            variant_priority=10,
        )
        frontend = _add_seed(
            sess,
            "system_design.frontend_perf",
            role_tags=["frontend_web"],
            skill_tags=["react", "performance"],
            seed_priority=20,
            variant_priority=10,
        )
        generic = _add_seed(
            sess,
            "system_design.generic_tradeoff",
            role_tags=["general"],
            skill_tags=["tradeoff"],
            seed_priority=15,
            variant_priority=5,
        )
        sess.commit()

        result = select_question_candidates(
            sess,
            dimension="system_design",
            job_level="senior",
            target_skills=["react"],
            direction_tags=["internet_tech"],
            role_tags=["frontend_web"],
            probe_intent="opening",
            top_k=3,
        )

    assert [candidate.variant_id for candidate in result.candidates] == [
        frontend,
        generic,
    ]
    assert java not in [candidate.variant_id for candidate in result.candidates]
    assert "role_tag:frontend_web" in result.candidates[0].match_reasons


def test_selector_falls_back_to_current_ranking_when_role_pack_is_missing() -> None:
    session_local = _session_factory()
    with session_local() as sess:
        java = _add_seed(
            sess,
            "system_design.java_cache",
            role_tags=["java_backend"],
            skill_tags=["redis"],
            seed_priority=40,
            variant_priority=10,
        )
        sess.commit()

        result = select_question_candidates(
            sess,
            dimension="system_design",
            job_level="senior",
            role_tags=["sre"],
            probe_intent="opening",
            top_k=3,
        )

    assert [candidate.variant_id for candidate in result.candidates] == [java]
    assert "role_fallback:no_matching_role_pack" in result.candidates[0].match_reasons


def test_selector_opening_deduplicates_seed_but_followup_reuses_different_variant() -> None:
    session_local = _session_factory()
    with session_local() as sess:
        opening = _add_seed(
            sess,
            "system_design.cache",
            skill_tags=["redis"],
            intent="opening",
            variant_id="system_design.cache.opening",
        )
        followup = _add_seed(
            sess,
            "system_design.queue",
            skill_tags=["queue"],
            intent="opening",
            variant_id="system_design.queue.opening",
        )
        sess.add(
            QuestionVariant(
                id="system_design.cache.followup",
                seed_id="system_design.cache",
                version=1,
                intent="followup",
                difficulty="standard",
                scenario_brief="followup scenario",
                question_stem="followup question",
                prompt_template="followup prompt",
                scenario_skill_tags=["redis"],
                resume_anchor_hints=["redis"],
                failure_categories=["missing_metrics"],
                rubric_additions=["addition"],
                expected_signals=["signal"],
                anti_patterns=["anti"],
                good_answer_hints=["hint"],
                role_tags=["java_backend"],
                priority=30,
                status="active",
            )
        )
        sess.commit()

        qa_history = [
            {
                "selection_artifacts": {
                    "question_items": [
                        {"seed_id": "system_design.cache", "variant_id": opening}
                    ]
                }
            }
        ]

        opening_result = select_question_candidates(
            sess,
            dimension="system_design",
            job_level="senior",
            probe_intent="opening",
            qa_history=qa_history,
        )
        followup_result = select_question_candidates(
            sess,
            dimension="system_design",
            job_level="senior",
            probe_intent="followup",
            qa_history=qa_history,
        )

    assert [candidate.variant_id for candidate in opening_result.candidates] == [followup]
    assert followup_result.candidates[0].seed_id == "system_design.cache"
    assert followup_result.candidates[0].variant_id == "system_design.cache.followup"


def test_selector_history_dedupe_ignores_non_injected_shadow_candidates() -> None:
    session_local = _session_factory()
    with session_local() as sess:
        injected = _add_seed(
            sess,
            "system_design.cache",
            skill_tags=["redis"],
            intent="opening",
            seed_priority=100,
            variant_priority=10,
            variant_id="system_design.cache.opening",
        )
        shadow = _add_seed(
            sess,
            "system_design.queue",
            skill_tags=["queue"],
            intent="opening",
            seed_priority=90,
            variant_priority=10,
            variant_id="system_design.queue.opening",
        )
        fallback = _add_seed(
            sess,
            "system_design.slo",
            skill_tags=["slo"],
            intent="opening",
            seed_priority=80,
            variant_priority=10,
            variant_id="system_design.slo.opening",
        )
        sess.commit()

        result = select_question_candidates(
            sess,
            dimension="system_design",
            job_level="senior",
            probe_intent="opening",
            qa_history=[
                {
                    "selection_artifacts": {
                        "question_items": [
                            {
                                "seed_id": "system_design.cache",
                                "variant_id": injected,
                                "rank": 1,
                                "injected": True,
                            },
                            {
                                "seed_id": "system_design.queue",
                                "variant_id": shadow,
                                "rank": 2,
                                "injected": False,
                            },
                        ]
                    }
                }
            ],
            top_k=3,
        )

    variant_ids = [candidate.variant_id for candidate in result.candidates]
    assert injected not in variant_ids
    assert variant_ids == [shadow, fallback]


def test_history_selection_artifacts_keep_only_injected_rank_one_refs() -> None:
    artifacts = question_selector.build_question_history_selection_artifacts(
        {
            "selection_artifacts": {
                "rag": {"doc_refs": [{"source": "kb.md"}]},
                "question_items": [
                    {
                        "seed_id": "system_design.cache",
                        "variant_id": "system_design.cache.opening",
                        "rank": 1,
                        "injected": True,
                        "scenario_brief": "do not persist",
                        "match_reasons": ["priority:100"],
                    },
                    {
                        "seed_id": "system_design.queue",
                        "variant_id": "system_design.queue.opening",
                        "rank": 2,
                        "injected": False,
                    },
                ],
            }
        }
    )

    assert artifacts == {
        "question_items": [
            {
                "seed_id": "system_design.cache",
                "variant_id": "system_design.cache.opening",
                "rank": 1,
                "injected": True,
            }
        ]
    }
    assert "rag" not in artifacts
    assert "scenario_brief" not in artifacts["question_items"][0]
    assert "match_reasons" not in artifacts["question_items"][0]


def test_bundled_java_backend_junior_mainline_dimensions_return_structured_candidates() -> None:
    seed_dir = Path(__file__).resolve().parents[2] / "knowledge" / "question_seeds"
    mainline_dimensions = [
        "technical_depth",
        "system_design",
        "problem_solving",
        "coding_quality",
        "project_experience",
        "communication",
    ]

    session_local = _session_factory()
    with session_local() as sess:
        import_question_seed_dir(seed_dir, session=sess)

        results = {
            dimension: select_question_candidates(
                sess,
                dimension=dimension,
                job_level="junior",
                target_skills=["java", "spring", "mysql", "redis"],
                direction_tags=["internet_tech"],
                role_tags=["java_backend"],
                probe_intent="followup",
                top_k=3,
            )
            for dimension in mainline_dimensions
        }

    for dimension, result in results.items():
        assert len(result.candidates) == 3, dimension
        assert all(candidate.dimension == dimension for candidate in result.candidates)
        assert all("java_backend" in candidate.role_tags for candidate in result.candidates)
        assert all(candidate.dimension != "backend_systems" for candidate in result.candidates)
        assert "role_tag:java_backend" in result.candidates[0].match_reasons
        assert "direction_tag:internet_tech" in result.candidates[0].match_reasons


def test_bundled_java_ai_project_experience_prefers_ai_workflow_seed() -> None:
    seed_dir = Path(__file__).resolve().parents[2] / "knowledge" / "question_seeds"
    fit_profile = QuestionFitProfile(
        dimension="project_experience",
        turn_intent="recovery",
        direction_tags=["internet_tech"],
        role_tags=["java_backend"],
        candidate_projects=[{"name": "AI集成与应用能力"}],
        candidate_skills=[
            "java",
            "spring",
            "springboot",
            "springai",
            "langchainj",
            "rag",
            "ai",
            "workflow",
        ],
        job_core_skills=[
            "java",
            "spring_ai",
            "langchainj",
            "rag",
            "function_calling",
        ],
        target_skills=["langchainj", "spring_ai"],
        failure_categories=["unclear_architecture"],
        anchor_confidence="high",
        generic_risk="medium",
        resume_anchor_terms=["ai", "rag", "langchainj", "springai", "workflow"],
    )

    session_local = _session_factory()
    with session_local() as sess:
        import_question_seed_dir(seed_dir, session=sess)

        result = select_question_candidates(
            sess,
            dimension="project_experience",
            job_level="junior",
            target_skills=["langchainj", "spring-ai"],
            failure_categories=["unclear_architecture"],
            direction_tags=["internet_tech"],
            role_tags=["java_backend"],
            resume_anchor_text=(
                "AI集成与应用能力 LangChainJ Spring-AI RAG function calling "
                "Java Spring workflow SpringAI"
            ),
            probe_intent="recovery",
            difficulty="deep_probe",
            fit_profile=fit_profile,
            top_k=5,
        )

    top = result.candidates[0]
    assert top.seed_id == "project_experience.java_ai_workflow_delivery"
    assert top.reviewed_acceptance_checks
    assert top.reviewed_acceptance_checks[0]["check_id"].startswith(
        "reviewed:project_experience.java_ai_workflow_delivery."
    )
    assert {
        "target_skill:langchainj",
        "target_skill:spring_ai",
    } & set(top.match_reasons)


def test_bundled_non_java_tech_roles_return_junior_mainline_candidates() -> None:
    seed_dir = Path(__file__).resolve().parents[2] / "knowledge" / "question_seeds"
    role_dimensions = {
        "frontend_web": [
            "technical_depth",
            "coding_quality",
            "problem_solving",
            "project_experience",
            "product_thinking",
            "communication",
        ],
        "sre": [
            "technical_depth",
            "system_design",
            "problem_solving",
            "project_experience",
            "communication",
        ],
        "ai_fullstack": [
            "technical_depth",
            "system_design",
            "product_thinking",
            "project_experience",
            "problem_solving",
            "communication",
        ],
        "ai_agent": [
            "technical_depth",
            "system_design",
            "problem_solving",
            "product_thinking",
            "communication",
        ],
        "mobile": [
            "technical_depth",
            "problem_solving",
            "coding_quality",
            "project_experience",
            "communication",
        ],
        "ai_algorithm": [
            "technical_depth",
            "problem_solving",
            "project_experience",
            "product_thinking",
            "communication",
        ],
    }

    session_local = _session_factory()
    with session_local() as sess:
        import_question_seed_dir(seed_dir, session=sess)
        results = {
            (role, dimension): select_question_candidates(
                sess,
                dimension=dimension,
                job_level="junior",
                direction_tags=["internet_tech"],
                role_tags=[role],
                probe_intent="followup",
                top_k=3,
            )
            for role, dimensions in role_dimensions.items()
            for dimension in dimensions
        }

    for (role, dimension), result in results.items():
        assert result.candidates, f"{role}:{dimension}"
        assert all(candidate.dimension == dimension for candidate in result.candidates)
        assert all(role in candidate.role_tags for candidate in result.candidates)
        assert f"role_tag:{role}" in result.candidates[0].match_reasons
        assert "direction_tag:internet_tech" in result.candidates[0].match_reasons


def test_bundled_business_roles_return_junior_mainline_candidates() -> None:
    seed_dir = Path(__file__).resolve().parents[2] / "knowledge" / "question_seeds"
    role_dimensions = {
        "product_manager": [
            "user_insight",
            "requirement_analysis",
            "prioritization",
            "metrics_thinking",
            "stakeholder_management",
        ],
        "operations": [
            "user_growth",
            "content_operations",
            "data_analysis",
            "campaign_execution",
            "process_optimization",
        ],
        "sales_business": [
            "customer_discovery",
            "solution_matching",
            "objection_handling",
            "negotiation",
            "pipeline_management",
        ],
        "marketing_brand": [
            "market_insight",
            "brand_strategy",
            "campaign_planning",
            "channel_growth",
            "content_creativity",
        ],
        "hr_function": [
            "talent_acquisition",
            "employee_relations",
            "organization_development",
            "policy_compliance",
            "service_orientation",
        ],
        "customer_success": [
            "customer_empathy",
            "issue_diagnosis",
            "solution_delivery",
            "escalation_management",
            "retention_growth",
        ],
        "general_management": [
            "goal_setting",
            "team_leadership",
            "decision_making",
            "execution_management",
            "cross_functional_alignment",
        ],
    }

    session_local = _session_factory()
    with session_local() as sess:
        import_question_seed_dir(seed_dir, session=sess)
        results = {
            (role, dimension): select_question_candidates(
                sess,
                dimension=dimension,
                job_level="junior",
                direction_tags=["business"],
                role_tags=[role],
                probe_intent="followup",
                top_k=3,
            )
            for role, dimensions in role_dimensions.items()
            for dimension in dimensions
        }

    for (role, dimension), result in results.items():
        assert result.candidates, f"{role}:{dimension}"
        assert all(candidate.dimension == dimension for candidate in result.candidates)
        assert all(role in candidate.role_tags for candidate in result.candidates)
        assert f"role_tag:{role}" in result.candidates[0].match_reasons
        assert "direction_tag:business" in result.candidates[0].match_reasons
