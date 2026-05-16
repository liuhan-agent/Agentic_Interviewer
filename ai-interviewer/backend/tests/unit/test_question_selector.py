from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
from app.models.question_bank import QuestionSeed, QuestionVariant
from app.services.question_fit_profile import build_question_fit_profile
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
    sess.add(
        QuestionVariant(
            id=variant_id,
            seed_id=seed_id,
            version=1,
            intent=intent,
            difficulty=difficulty,
            scenario_brief=f"scenario for {variant_id}",
            question_stem=f"question for {variant_id}",
            prompt_template=f"prompt for {variant_id}",
            scenario_skill_tags=skill_tags or [],
            resume_anchor_hints=resume_anchor_hints or [],
            failure_categories=failure_categories or [],
            rubric_additions=["addition"],
            expected_signals=["signal"],
            anti_patterns=["anti"],
            good_answer_hints=["hint"],
            role_tags=variant_role_tags or role_tags or ["java_backend"],
            priority=variant_priority,
            status=variant_status,
        )
    )
    return variant_id


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


def test_selector_breaks_ties_deterministically_by_seed_and_variant_id() -> None:
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
        "system_design.alpha.opening",
        "system_design.beta.opening",
    ]
    assert [candidate.rank for candidate in result.candidates] == [1, 2, 3]


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
