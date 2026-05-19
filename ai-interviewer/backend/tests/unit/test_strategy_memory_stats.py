from __future__ import annotations

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
from app.models.strategy_memory import StrategyMemoryStats, StrategyMemoryUsage
from app.services.strategy_memory_stats import refresh_strategy_memory_stats


def _session_factory():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)


def _add_usage(
    sess,
    *,
    idx: int,
    context_key: str | None,
    score: float,
    passed: bool,
    immediate_reward: float,
    delayed_reward: float | None = None,
    overruled: bool = False,
    helpful_score: float | None = None,
) -> None:
    sess.add(
        StrategyMemoryUsage(
            id=f"usage-{idx}",
            strategy_id="seed:senior_system_design",
            session_id=f"sess-{idx}",
            turn_idx=idx,
            trace_id=f"trace-{idx}",
            context_key=context_key,
            action_id="plan_adaptive",
            plan_template="adaptive",
            score=score,
            passed=passed,
            immediate_reward=immediate_reward,
            delayed_reward=delayed_reward,
            verifier_overruled=overruled,
            helpful_score=helpful_score,
        )
    )


def test_refresh_strategy_memory_stats_aggregates_context_and_global_rows() -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as sess:
        _add_usage(
            sess,
            idx=1,
            context_key="senior:system_design",
            score=8.0,
            passed=True,
            immediate_reward=0.4,
            delayed_reward=0.9,
            helpful_score=0.8,
        )
        _add_usage(
            sess,
            idx=2,
            context_key="senior:system_design",
            score=6.0,
            passed=False,
            immediate_reward=0.3,
            overruled=True,
        )
        _add_usage(
            sess,
            idx=3,
            context_key="java_backend:senior:system_design",
            score=7.0,
            passed=True,
            immediate_reward=0.5,
            delayed_reward=0.7,
        )

        result = refresh_strategy_memory_stats(session=sess)
        second = refresh_strategy_memory_stats(session=sess)
        sess.commit()

        stats = {
            row.context_key: row
            for row in sess.scalars(select(StrategyMemoryStats)).all()
        }

    assert result.refreshed == 3
    assert second.refreshed == 3
    assert set(stats) == {
        "__global__",
        "senior:system_design",
        "java_backend:senior:system_design",
    }

    global_stats = stats["__global__"]
    assert global_stats.uses == 3
    assert global_stats.avg_score == pytest.approx(7.0)
    assert global_stats.pass_rate == pytest.approx(2 / 3)
    assert global_stats.avg_immediate_reward == pytest.approx(0.4)
    assert global_stats.avg_delayed_reward == pytest.approx(0.8)
    assert global_stats.avg_blended_reward == pytest.approx((0.9 + 0.3 + 0.7) / 3)
    assert global_stats.overrule_rate == pytest.approx(1 / 3)
    assert global_stats.helpful_avg == pytest.approx(0.8)

    context_stats = stats["senior:system_design"]
    assert context_stats.uses == 2
    assert context_stats.avg_blended_reward == pytest.approx((0.9 + 0.3) / 2)
    assert context_stats.pass_rate == pytest.approx(0.5)
    assert context_stats.overrule_rate == pytest.approx(0.5)


def test_refresh_strategy_memory_stats_removes_stale_rows_when_usages_disappear() -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as sess:
        _add_usage(
            sess,
            idx=1,
            context_key="senior:system_design",
            score=8.0,
            passed=True,
            immediate_reward=0.6,
        )
        refresh_strategy_memory_stats(session=sess)
        sess.query(StrategyMemoryUsage).delete()

        result = refresh_strategy_memory_stats(session=sess)
        sess.commit()

        rows = list(sess.scalars(select(StrategyMemoryStats)))

    assert result.refreshed == 0
    assert result.deleted == 2
    assert rows == []


def test_refresh_strategy_memory_stats_counts_missing_context_once_globally() -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as sess:
        _add_usage(
            sess,
            idx=1,
            context_key=None,
            score=8.0,
            passed=True,
            immediate_reward=0.6,
        )

        result = refresh_strategy_memory_stats(session=sess)
        sess.commit()

        rows = list(sess.scalars(select(StrategyMemoryStats)))

    assert result.refreshed == 1
    assert len(rows) == 1
    assert rows[0].context_key == "__global__"
    assert rows[0].uses == 1
    assert rows[0].avg_blended_reward == pytest.approx(0.6)
