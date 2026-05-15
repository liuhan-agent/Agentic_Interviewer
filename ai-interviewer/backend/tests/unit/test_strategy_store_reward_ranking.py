from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.memory import strategy_store as ss
from app.models.base import Base
from app.models.strategy_memory import StrategyMemory, StrategyMemoryStats


def _db_session_context():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)

    with Session() as sess:
        sess.add_all(
            [
                StrategyMemory(
                    id="seed:aaa_low_reward",
                    slug="aaa_low_reward",
                    name="Low Reward",
                    description="Metadata-first row.",
                    source="seed",
                    dimensions=["system_design"],
                    job_levels=["senior"],
                    body_markdown="Low reward body.",
                    status="active",
                    priority=0,
                    confidence=0.4,
                    support_count=10,
                ),
                StrategyMemory(
                    id="seed:zzz_high_reward",
                    slug="zzz_high_reward",
                    name="High Reward",
                    description="Reward should rank this first only in reward mode.",
                    source="seed",
                    dimensions=["system_design"],
                    job_levels=["senior"],
                    body_markdown="High reward body.",
                    status="active",
                    priority=0,
                    confidence=0.4,
                    support_count=10,
                ),
                StrategyMemoryStats(
                    id="stats-low",
                    strategy_id="seed:aaa_low_reward",
                    context_key="__global__",
                    uses=30,
                    avg_blended_reward=0.2,
                    overrule_rate=0.5,
                ),
                StrategyMemoryStats(
                    id="stats-high",
                    strategy_id="seed:zzz_high_reward",
                    context_key="__global__",
                    uses=30,
                    avg_blended_reward=0.9,
                    overrule_rate=0.0,
                ),
            ]
        )
        sess.commit()

    @contextmanager
    def get_session():
        with Session() as sess:
            yield sess

    return get_session


def test_reward_shadow_calculates_rank_without_changing_metadata_order(monkeypatch) -> None:
    monkeypatch.setattr(
        ss,
        "get_settings",
        lambda: SimpleNamespace(
            strategy_memory_backend="db",
            strategy_memory_ranking_mode="reward_shadow",
        ),
    )
    monkeypatch.setattr(ss, "get_session", _db_session_context())

    entries = ss.retrieve_strategies(
        dimension="system_design",
        job_level="senior",
        limit=2,
    )

    assert [entry.id for entry in entries] == [
        "seed:aaa_low_reward",
        "seed:zzz_high_reward",
    ]
    assert entries[0].shadow_rank == 2
    assert entries[1].shadow_rank == 1
    assert entries[1].ranking_reason["avg_blended_reward"] == 0.9


def test_reward_mode_uses_stats_order(monkeypatch) -> None:
    monkeypatch.setattr(
        ss,
        "get_settings",
        lambda: SimpleNamespace(
            strategy_memory_backend="db",
            strategy_memory_ranking_mode="reward",
        ),
    )
    monkeypatch.setattr(ss, "get_session", _db_session_context())

    entries = ss.retrieve_strategies(
        dimension="system_design",
        job_level="senior",
        limit=2,
    )

    assert [entry.id for entry in entries] == [
        "seed:zzz_high_reward",
        "seed:aaa_low_reward",
    ]
