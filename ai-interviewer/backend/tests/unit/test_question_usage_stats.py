from __future__ import annotations

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
from app.models.question_bank import (
    QuestionRewardRollout,
    QuestionSeed,
    QuestionUsage,
    QuestionUsageStats,
    QuestionVariant,
)
from app.services.question_usage_stats import (
    build_question_reward_readiness,
    refresh_question_usage_stats,
)


def _session_factory():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)


def _add_usage(
    sess,
    *,
    usage_id: str,
    variant_id: str = "system_design.cache.opening",
    mode: str = "structured_primary",
    injected: bool = True,
    score: float | None = 8.0,
    passed: bool | None = True,
    reward: float | None = 0.7,
    context_key: str | None = None,
    direction_tag: str | None = None,
    role_tag: str | None = None,
    job_level: str | None = None,
    dimension: str | None = None,
) -> None:
    sess.add(
        QuestionUsage(
            id=usage_id,
            session_id=f"sess-{usage_id}",
            turn_idx=1,
            trace_id=f"trace-{usage_id}",
            seed_id="system_design.cache",
            variant_id=variant_id,
            seed_version=1,
            variant_version=1,
            rank=1,
            match_score=42.0,
            match_reasons=["priority:42"],
            injected=injected,
            question_selector_mode=mode,
            question_context_key=context_key,
            direction_tag=direction_tag,
            role_tag=role_tag,
            job_level=job_level,
            dimension=dimension,
            score=score,
            passed=passed,
            immediate_reward=reward,
        )
    )


def _add_variant(
    sess,
    *,
    seed_id: str,
    variant_id: str,
    seed_priority: int,
    variant_priority: int = 0,
) -> None:
    sess.add(
        QuestionSeed(
            id=seed_id,
            version=1,
            title=seed_id,
            dimension="system_design",
            job_levels=["junior"],
            skill_tags=[],
            direction_tags=[],
            role_tags=[],
            rubric={},
            priority=seed_priority,
            status="active",
            source="test",
            scope="global",
            language="zh-CN",
        )
    )
    sess.add(
        QuestionVariant(
            id=variant_id,
            seed_id=seed_id,
            version=1,
            intent="opening",
            difficulty="standard",
            scenario_brief="",
            question_stem="",
            prompt_template="",
            scenario_skill_tags=[],
            resume_anchor_hints=[],
            failure_categories=[],
            rubric_additions=[],
            expected_signals=[],
            anti_patterns=[],
            good_answer_hints=[],
            role_tags=[],
            priority=variant_priority,
            status="active",
        )
    )


def test_refresh_question_usage_stats_counts_candidates_but_rewards_injected_rows() -> None:
    session_local = _session_factory()
    with session_local() as sess:
        _add_usage(sess, usage_id="injected-good", reward=0.8, score=9.0, passed=True)
        _add_usage(sess, usage_id="injected-weak", reward=0.2, score=5.0, passed=False)
        _add_usage(
            sess,
            usage_id="shadow-candidate",
            injected=False,
            reward=0.95,
            score=10.0,
            passed=True,
        )

        result = refresh_question_usage_stats(session=sess)
        second = refresh_question_usage_stats(session=sess)
        sess.commit()

        row = sess.scalar(select(QuestionUsageStats))

    assert result.refreshed == 1
    assert second.refreshed == 1
    assert row is not None
    assert row.variant_id == "system_design.cache.opening"
    assert row.question_selector_mode == "structured_primary"
    assert row.uses == 3
    assert row.injected_uses == 2
    assert row.rewarded_uses == 2
    assert row.avg_score == pytest.approx(7.0)
    assert row.pass_rate == pytest.approx(0.5)
    assert row.avg_immediate_reward == pytest.approx(0.5)
    assert row.last_used_at is not None


def test_refresh_question_usage_stats_partitions_by_variant_and_mode() -> None:
    session_local = _session_factory()
    with session_local() as sess:
        _add_usage(sess, usage_id="primary", variant_id="system_design.cache.opening")
        _add_usage(
            sess,
            usage_id="shadow",
            variant_id="system_design.cache.opening",
            mode="structured_shadow",
        )
        _add_usage(
            sess,
            usage_id="other",
            variant_id="system_design.queue.opening",
        )

        result = refresh_question_usage_stats(session=sess)
        sess.commit()

        rows = list(
            sess.scalars(
                select(QuestionUsageStats).order_by(
                    QuestionUsageStats.variant_id,
                    QuestionUsageStats.question_selector_mode,
                )
            )
        )

    assert result.refreshed == 3
    assert {
        (row.variant_id, row.question_selector_mode)
        for row in rows
    } == {
        ("system_design.cache.opening", "structured_primary"),
        ("system_design.cache.opening", "structured_shadow"),
        ("system_design.queue.opening", "structured_primary"),
    }


def test_refresh_question_usage_stats_adds_context_and_global_rollups() -> None:
    session_local = _session_factory()
    exact_context = "internet_tech:java_backend:junior:system_design"
    other_context = "business:product_manager:junior:system_design"
    with session_local() as sess:
        _add_usage(
            sess,
            usage_id="exact-strong",
            context_key=exact_context,
            reward=0.9,
            score=9.0,
            passed=True,
        )
        _add_usage(
            sess,
            usage_id="exact-weak",
            context_key=exact_context,
            reward=0.3,
            score=5.0,
            passed=False,
        )
        _add_usage(
            sess,
            usage_id="other-context",
            context_key=other_context,
            reward=0.6,
            score=7.0,
            passed=True,
        )

        result = refresh_question_usage_stats(session=sess)
        sess.commit()

        rows = {
            row.question_context_key: row
            for row in sess.scalars(select(QuestionUsageStats))
        }

    assert result.refreshed == 3
    assert set(rows) == {"__global__", exact_context, other_context}
    assert rows["__global__"].uses == 3
    assert rows["__global__"].rewarded_uses == 3
    assert rows["__global__"].avg_immediate_reward == pytest.approx(0.6)
    assert rows[exact_context].uses == 2
    assert rows[exact_context].rewarded_uses == 2
    assert rows[exact_context].avg_score == pytest.approx(7.0)
    assert rows[exact_context].pass_rate == pytest.approx(0.5)
    assert rows[other_context].uses == 1


def test_refresh_question_usage_stats_removes_stale_rows() -> None:
    session_local = _session_factory()
    with session_local() as sess:
        _add_usage(sess, usage_id="one")
        refresh_question_usage_stats(session=sess)
        sess.query(QuestionUsage).delete()

        result = refresh_question_usage_stats(session=sess)
        sess.commit()

        rows = list(sess.scalars(select(QuestionUsageStats)))

    assert result.refreshed == 0
    assert result.deleted == 1
    assert rows == []


def test_build_question_reward_readiness_unifies_selector_modes_for_shadow_top_k() -> None:
    session_local = _session_factory()
    low_variant = "system_design.metadata.low_reward"
    high_variant = "system_design.reward.high_reward"
    with session_local() as sess:
        _add_variant(
            sess,
            seed_id="system_design.metadata",
            variant_id=low_variant,
            seed_priority=100,
        )
        _add_variant(
            sess,
            seed_id="system_design.reward",
            variant_id=high_variant,
            seed_priority=90,
        )
        _add_usage(
            sess,
            usage_id="low-shadow",
            variant_id=low_variant,
            mode="structured_shadow",
            reward=0.1,
        )
        _add_usage(
            sess,
            usage_id="low-primary-unrewarded",
            variant_id=low_variant,
            mode="structured_primary",
            reward=None,
            score=None,
            passed=None,
        )
        for idx in range(20):
            _add_usage(
                sess,
                usage_id=f"high-{idx}",
                variant_id=high_variant,
                mode="structured_shadow" if idx % 2 else "structured_primary",
                reward=1.0,
                score=9.0,
                passed=True,
            )

        payload = build_question_reward_readiness(session=sess)

    assert payload["metadata_top_variant_ids"][0] == low_variant
    assert payload["reward_top_variant_ids"][0] == high_variant
    assert payload["rank_changed"] is True
    assert payload["reward_ranking_mode"] == "reward_shadow"
    assert payload["modes"] == []
    variants = {row["variant_id"]: row for row in payload["variants"]}
    assert variants[low_variant]["uses"] == 2
    assert variants[low_variant]["rewarded_uses"] == 1
    assert variants[low_variant]["observed_selector_modes"] == [
        "structured_primary",
        "structured_shadow",
    ]
    assert variants[high_variant]["uses"] == 20
    assert variants[high_variant]["rewarded_uses"] == 20


def test_build_question_reward_readiness_reports_needs_samples_after_pool_is_large_enough() -> None:
    session_local = _session_factory()
    with session_local() as sess:
        for idx in range(5):
            seed_id = f"system_design.seed_{idx}"
            variant_id = f"{seed_id}.variant"
            _add_variant(
                sess,
                seed_id=seed_id,
                variant_id=variant_id,
                seed_priority=50 - idx,
            )
            _add_usage(
                sess,
                usage_id=f"usage-{idx}",
                variant_id=variant_id,
                mode="structured_shadow",
                reward=0.4,
            )

        payload = build_question_reward_readiness(session=sess)

    assert payload["candidate_count"] == 5
    assert payload["rewarded_usage_count"] == 5
    assert payload["readiness"] == "needs_samples"
    assert payload["reasons"] == ["reward_samples_below_min"]


def test_build_question_reward_readiness_adds_context_and_seed_rollout_groups() -> None:
    session_local = _session_factory()
    context_key = "internet_tech:java_backend:junior:system_design"
    low_variant = "system_design.metadata.low_reward"
    high_variant = "system_design.reward.high_reward"
    with session_local() as sess:
        _add_variant(
            sess,
            seed_id="system_design.metadata",
            variant_id=low_variant,
            seed_priority=100,
        )
        _add_variant(
            sess,
            seed_id="system_design.reward",
            variant_id=high_variant,
            seed_priority=90,
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
                QuestionRewardRollout(
                    id="seed:system_design.reward",
                    scope="seed",
                    scope_key="system_design.reward",
                    mode="reward",
                    reason="pilot seed",
                ),
            ]
        )
        _add_usage(
            sess,
            usage_id="historical-no-context",
            variant_id=low_variant,
            mode="structured_primary",
            reward=0.1,
        )
        for idx in range(20):
            _add_usage(
                sess,
                usage_id=f"context-high-{idx}",
                variant_id=high_variant,
                mode="structured_shadow" if idx % 2 else "structured_primary",
                reward=1.0,
                context_key=context_key,
                direction_tag="internet_tech",
                role_tag="java_backend",
                job_level="junior",
                dimension="system_design",
            )

        payload = build_question_reward_readiness(session=sess)

    contexts = {row["context_key"]: row for row in payload["contexts"]}
    assert contexts[context_key]["rollout"]["mode"] == "reward"
    assert contexts[context_key]["rollout"]["source"] == "override"
    assert contexts[context_key]["usage_count"] == 20
    assert contexts[context_key]["metadata_top_variant_ids"] == [high_variant]
    assert all(
        row["context_key"] != ""
        for row in payload["contexts"]
    )

    seeds = {row["seed_id"]: row for row in payload["seeds"]}
    assert seeds["system_design.reward"]["rollout"]["mode"] == "reward"
    assert seeds["system_design.reward"]["rollout"]["reason"] == "pilot seed"
    assert seeds["system_design.reward"]["usage_count"] == 20
    assert seeds["system_design.metadata"]["usage_count"] == 1
