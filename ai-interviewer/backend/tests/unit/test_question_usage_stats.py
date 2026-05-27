from __future__ import annotations

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
from app.models.question_bank import QuestionUsage, QuestionUsageStats
from app.services.question_usage_stats import refresh_question_usage_stats


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
            score=score,
            passed=passed,
            immediate_reward=reward,
        )
    )


def test_refresh_question_usage_stats_counts_candidates_but_rewards_injected_rows() -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as sess:
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
    SessionLocal = _session_factory()
    with SessionLocal() as sess:
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


def test_refresh_question_usage_stats_removes_stale_rows() -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as sess:
        _add_usage(sess, usage_id="one")
        refresh_question_usage_stats(session=sess)
        sess.query(QuestionUsage).delete()

        result = refresh_question_usage_stats(session=sess)
        sess.commit()

        rows = list(sess.scalars(select(QuestionUsageStats)))

    assert result.refreshed == 0
    assert result.deleted == 1
    assert rows == []
