from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
from app.models.strategy_memory import StrategyMemory, StrategyMemoryStats
from app.services.strategy_promotion import apply_strategy_quality_transitions


def _session_factory():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)


def _add_memory(
    sess,
    *,
    strategy_id: str,
    stage: str = "seed",
    confidence: float = 0.8,
) -> None:
    sess.add(
        StrategyMemory(
            id=strategy_id,
            slug=strategy_id.replace(":", "_"),
            name=strategy_id,
            description="Strategy",
            source="seed",
            dimensions=["system_design"],
            job_levels=["senior"],
            body_markdown="Body",
            status="active",
            promotion_stage=stage,
            confidence=confidence,
            support_count=30,
        )
    )


def _add_stats(
    sess,
    *,
    strategy_id: str,
    uses: int,
    avg_reward: float,
    overrule_rate: float,
) -> None:
    sess.add(
        StrategyMemoryStats(
            id=f"stats-{strategy_id}",
            strategy_id=strategy_id,
            context_key="__global__",
            uses=uses,
            avg_blended_reward=avg_reward,
            overrule_rate=overrule_rate,
        )
    )


def test_quality_transitions_disable_low_reward_strategy() -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as sess:
        _add_memory(sess, strategy_id="seed:weak_reward")
        _add_stats(
            sess,
            strategy_id="seed:weak_reward",
            uses=30,
            avg_reward=0.4,
            overrule_rate=0.1,
        )

        result = apply_strategy_quality_transitions(session=sess)
        memory = sess.get(StrategyMemory, "seed:weak_reward")

    assert result.disabled == 1
    assert memory is not None
    assert memory.status == "disabled"
    assert memory.quality_reason is not None
    assert "avg_blended_reward=0.40" in memory.quality_reason


def test_quality_transitions_promote_stable_strategy() -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as sess:
        _add_memory(
            sess,
            strategy_id="promoted:strong",
            stage="low_confidence",
            confidence=0.4,
        )
        _add_stats(
            sess,
            strategy_id="promoted:strong",
            uses=100,
            avg_reward=0.75,
            overrule_rate=0.1,
        )

        result = apply_strategy_quality_transitions(session=sess)
        memory = sess.get(StrategyMemory, "promoted:strong")

    assert result.stabilized == 1
    assert memory is not None
    assert memory.status == "active"
    assert memory.promotion_stage == "stable"
    assert memory.confidence >= 0.75
    assert memory.quality_reason is not None
    assert "stable" in memory.quality_reason
