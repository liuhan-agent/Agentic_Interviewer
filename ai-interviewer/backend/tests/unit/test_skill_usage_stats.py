from __future__ import annotations

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
from app.models.skill_playbook import (
    SkillPlaybookCard,
    SkillRewardRollout,
    SkillUsage,
    SkillUsageStats,
)
from app.services.skill_usage_stats import (
    build_skill_reward_readiness,
    refresh_skill_usage_stats,
    skill_usage_context_key,
)


def _session_factory():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)


def _add_usage(
    sess,
    *,
    usage_id: str,
    skill_id: str = "tech_debug_root_cause_probe",
    role: str = "java_backend",
    job_level: str = "junior",
    dimension: str = "problem_solving",
    probe_intent: str | None = "debugging_probe",
    score: float | None = 8.0,
    passed: bool | None = True,
    reward: float | None = 0.7,
    verifier_overruled: bool = False,
) -> None:
    context_key = skill_usage_context_key(
        role=role,
        job_level=job_level,
        dimension=dimension,
        probe_intent=probe_intent,
    )
    sess.add(
        SkillUsage(
            id=usage_id,
            skill_id=skill_id,
            session_id=f"sess-{usage_id}",
            turn_idx=1,
            trace_id=f"trace-{usage_id}",
            skill_context_key=context_key,
            role=role,
            job_level=job_level,
            dimension=dimension,
            probe_intent=probe_intent,
            rank=1,
            match_score=42.0,
            match_reasons=["priority:8", "probe_intent:debugging_probe"],
            injected=True,
            evaluator_visibility=True,
            score=score,
            passed=passed,
            immediate_reward=reward,
            verifier_overruled=verifier_overruled,
        )
    )


def _card(card_id: str, *, priority: int) -> SkillPlaybookCard:
    return SkillPlaybookCard(
        id=card_id,
        name=card_id,
        description=f"{card_id} description",
        status="active",
        priority=priority,
        role_tags=["java_backend"],
        job_levels=["junior"],
        dimensions=["problem_solving"],
        probe_intents=["debugging_probe"],
    )


def test_skill_usage_context_key_uses_role_level_dimension_and_probe_intent() -> None:
    assert (
        skill_usage_context_key(
            role="Java Backend",
            job_level="Junior",
            dimension="Problem Solving",
            probe_intent="Debugging Probe",
        )
        == "java_backend:junior:problem_solving:debugging_probe"
    )
    assert (
        skill_usage_context_key(
            role="",
            job_level=None,
            dimension=None,
            probe_intent=None,
        )
        == "general:mid:general:none"
    )


def test_refresh_skill_usage_stats_aggregates_reward_shadow_fields() -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as sess:
        _add_usage(sess, usage_id="good", reward=0.8, score=9.0, passed=True)
        _add_usage(
            sess,
            usage_id="weak",
            reward=0.2,
            score=5.0,
            passed=False,
            verifier_overruled=True,
        )
        _add_usage(sess, usage_id="pending", reward=None, score=None, passed=None)

        result = refresh_skill_usage_stats(session=sess)
        second = refresh_skill_usage_stats(session=sess)
        sess.commit()

        row = sess.scalar(select(SkillUsageStats))

    assert result.refreshed == 1
    assert second.refreshed == 1
    assert row is not None
    assert row.skill_id == "tech_debug_root_cause_probe"
    assert row.skill_context_key == "java_backend:junior:problem_solving:debugging_probe"
    assert row.role == "java_backend"
    assert row.job_level == "junior"
    assert row.dimension == "problem_solving"
    assert row.probe_intent == "debugging_probe"
    assert row.uses == 3
    assert row.injected_uses == 3
    assert row.rewarded_uses == 2
    assert row.avg_score == pytest.approx(7.0)
    assert row.pass_rate == pytest.approx(0.5)
    assert row.avg_immediate_reward == pytest.approx(0.5)
    assert row.avg_blended_reward == pytest.approx(0.5)
    assert row.overrule_rate == pytest.approx(0.5)
    assert row.last_used_at is not None


def test_refresh_skill_usage_stats_partitions_by_skill_and_context() -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as sess:
        _add_usage(sess, usage_id="one")
        _add_usage(sess, usage_id="same-skill-other-context", probe_intent="evidence_probe")
        _add_usage(sess, usage_id="other-skill", skill_id="tech_latency_probe")

        result = refresh_skill_usage_stats(session=sess)
        sess.commit()

        rows = list(
            sess.scalars(
                select(SkillUsageStats).order_by(
                    SkillUsageStats.skill_id,
                    SkillUsageStats.skill_context_key,
                )
            )
        )

    assert result.refreshed == 3
    assert {
        (row.skill_id, row.skill_context_key)
        for row in rows
    } == {
        (
            "tech_debug_root_cause_probe",
            "java_backend:junior:problem_solving:debugging_probe",
        ),
        (
            "tech_debug_root_cause_probe",
            "java_backend:junior:problem_solving:evidence_probe",
        ),
        ("tech_latency_probe", "java_backend:junior:problem_solving:debugging_probe"),
    }


def test_build_skill_reward_readiness_uses_context_rollout_and_full_candidate_pool() -> None:
    SessionLocal = _session_factory()
    context_key = skill_usage_context_key(
        role="java_backend",
        job_level="junior",
        dimension="problem_solving",
        probe_intent="debugging_probe",
    )
    with SessionLocal() as sess:
        sess.add_all([
            _card("skill_metadata", priority=10),
            _card("skill_middle", priority=5),
            _card("skill_reward", priority=1),
            SkillRewardRollout(
                context_key=context_key,
                mode="reward",
                reason="admin pilot",
            ),
        ])
        for idx in range(25):
            _add_usage(
                sess,
                usage_id=f"metadata-{idx}",
                skill_id="skill_metadata",
                reward=0.1,
            )
            _add_usage(
                sess,
                usage_id=f"middle-{idx}",
                skill_id="skill_middle",
                reward=0.2,
            )
            _add_usage(
                sess,
                usage_id=f"reward-{idx}",
                skill_id="skill_reward",
                reward=1.0,
            )
        refresh_skill_usage_stats(session=sess)
        payload = build_skill_reward_readiness(session=sess)

    assert payload["reward_ranking_mode"] == "reward_shadow"
    assert payload["candidate_count"] == 3
    assert payload["usage_count"] == 75
    assert payload["rewarded_usage_count"] == 75
    assert payload["contexts"][0]["rollout"]["mode"] == "reward"
    assert payload["contexts"][0]["rollout"]["reason"] == "admin pilot"
    assert payload["contexts"][0]["metadata_top_skill_ids"] == [
        "skill_metadata",
        "skill_middle",
        "skill_reward",
    ]
    assert payload["contexts"][0]["reward_top_skill_ids"][0] == "skill_reward"
    assert payload["contexts"][0]["candidate_count"] == 3
    assert payload["contexts"][0]["usage_count"] == 75
    assert payload["contexts"][0]["rewarded_usage_count"] == 75
    assert payload["contexts"][0]["rank_changed"] is True
