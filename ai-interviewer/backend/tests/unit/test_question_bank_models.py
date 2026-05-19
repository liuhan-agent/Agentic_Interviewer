from __future__ import annotations

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
from app.models.question_bank import (
    QuestionRerankUsage,
    QuestionReview,
    QuestionSeed,
    QuestionUsage,
    QuestionVariant,
)


def _session_factory():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)


def test_question_seed_variant_and_usage_round_trip() -> None:
    session_local = _session_factory()
    with session_local() as sess:
        sess.add(
            QuestionSeed(
                id="system_design.cache_consistency",
                version=1,
                title="缓存一致性",
                dimension="system_design",
                job_levels=["mid", "senior"],
                skill_tags=["cache", "consistency"],
                direction_tags=["internet_tech"],
                role_tags=["java_backend"],
                rubric={"must_cover": ["失效策略", "一致性权衡"]},
                priority=20,
                status="active",
                source="manual_yaml",
                scope="global",
                org_id=None,
                job_template_id=None,
                language="zh-CN",
            )
        )
        sess.add(
            QuestionVariant(
                id="system_design.cache_consistency.flash_sale_inventory",
                seed_id="system_design.cache_consistency",
                version=1,
                intent="opening",
                difficulty="standard",
                scenario_brief="秒杀库存读多写少，库存缓存和数据库可能短暂不一致。",
                question_stem="请设计库存缓存与扣减一致性方案。",
                prompt_template="围绕候选人的缓存经验生成一道系统设计题。",
                scenario_skill_tags=["redis", "inventory"],
                resume_anchor_hints=["redis", "缓存"],
                failure_categories=["missing_tradeoff", "missing_metrics"],
                rubric_additions=["说明缓存失效窗口"],
                expected_signals=["能区分强一致与最终一致"],
                anti_patterns=["只说加锁，不讨论吞吐"],
                good_answer_hints=["给出降级和补偿路径"],
                role_tags=["java_backend"],
                priority=10,
                status="active",
            )
        )
        sess.add(
            QuestionUsage(
                id="usage-1",
                session_id="sess-1",
                turn_idx=2,
                trace_id="trace-1",
                seed_id="system_design.cache_consistency",
                variant_id="system_design.cache_consistency.flash_sale_inventory",
                seed_version=1,
                variant_version=1,
                rank=1,
                match_score=42.5,
                match_reasons=["priority:20", "target_skill:redis"],
                injected=True,
                question_selector_mode="structured_primary",
                score=8.0,
                passed=True,
                immediate_reward=0.7,
            )
        )
        sess.add(
            QuestionRerankUsage(
                id="rerank-1",
                session_id="sess-1",
                turn_idx=2,
                trace_id="trace-1",
                dimension="system_design",
                probe_intent="opening",
                question_selector_mode="structured_shadow",
                rule_top_seed_id="system_design.cache_consistency",
                rule_top_variant_id="system_design.cache_consistency.flash_sale_inventory",
                llm_top_seed_id="system_design.cache_consistency",
                llm_top_variant_id="system_design.cache_consistency.failover",
                candidate_variant_ids=[
                    "system_design.cache_consistency.flash_sale_inventory",
                    "system_design.cache_consistency.failover",
                ],
                ranked_variant_ids=[
                    "system_design.cache_consistency.failover",
                    "system_design.cache_consistency.flash_sale_inventory",
                ],
                fit_scores={"system_design.cache_consistency.failover": 0.91},
                anchor_choice="Flash Sale Inventory",
                reasons=["more project aligned"],
                confidence=0.8,
                model="shadow-model",
                latency_ms=123,
                status="ok",
                error=None,
            )
        )
        sess.add(
            QuestionReview(
                id="review-1",
                session_id="sess-1",
                turn_idx=2,
                trace_id="trace-1",
                question_rerank_usage_id="rerank-1",
                rule_variant_id="system_design.cache_consistency.flash_sale_inventory",
                llm_variant_id="system_design.cache_consistency.failover",
                winner="llm",
                reasons=["more specific"],
                notes="LLM shadow matched the project angle.",
                reviewer="admin",
                context_summary={
                    "dimension": "system_design",
                    "candidate": "senior backend",
                },
            )
        )
        sess.commit()

        seed = sess.scalar(select(QuestionSeed))
        variant = sess.scalar(select(QuestionVariant))
        usage = sess.scalar(select(QuestionUsage))
        rerank = sess.scalar(select(QuestionRerankUsage))
        review = sess.scalar(select(QuestionReview))

    assert seed is not None
    assert seed.dimension == "system_design"
    assert seed.job_levels == ["mid", "senior"]
    assert seed.skill_tags == ["cache", "consistency"]
    assert seed.direction_tags == ["internet_tech"]
    assert seed.role_tags == ["java_backend"]
    assert seed.rubric["must_cover"] == ["失效策略", "一致性权衡"]
    assert seed.scope == "global"
    assert seed.language == "zh-CN"

    assert variant is not None
    assert variant.seed_id == "system_design.cache_consistency"
    assert variant.intent == "opening"
    assert variant.difficulty == "standard"
    assert variant.scenario_skill_tags == ["redis", "inventory"]
    assert variant.role_tags == ["java_backend"]
    assert variant.expected_signals == ["能区分强一致与最终一致"]

    assert usage is not None
    assert usage.rank == 1
    assert usage.match_score == 42.5
    assert usage.match_reasons == ["priority:20", "target_skill:redis"]
    assert usage.injected is True
    assert usage.score == 8.0
    assert usage.passed is True
    assert usage.immediate_reward == 0.7

    assert rerank is not None
    assert rerank.rule_top_variant_id == (
        "system_design.cache_consistency.flash_sale_inventory"
    )
    assert rerank.llm_top_variant_id == "system_design.cache_consistency.failover"
    assert rerank.fit_scores["system_design.cache_consistency.failover"] == 0.91
    assert rerank.status == "ok"

    assert review is not None
    assert review.winner == "llm"
    assert review.reasons == ["more specific"]
    assert review.context_summary["dimension"] == "system_design"
