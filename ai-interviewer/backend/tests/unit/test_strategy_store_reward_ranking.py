from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.memory import strategy_store as ss
from app.models.base import Base
from app.models.strategy_memory import StrategyMemory, StrategyMemoryStats


def _strategy(strategy_id: str, slug: str) -> StrategyMemory:
    return StrategyMemory(
        id=strategy_id,
        slug=slug,
        name=slug.replace("_", " ").title(),
        description="Candidate strategy.",
        source="seed",
        dimensions=["system_design"],
        job_levels=["senior"],
        body_markdown=f"{slug} body.",
        status="active",
        priority=0,
        confidence=0.4,
        support_count=10,
    )


def _stats(
    *,
    strategy_id: str,
    context_key: str,
    avg_reward: float,
    uses: int = 40,
    overrule_rate: float = 0.0,
) -> StrategyMemoryStats:
    return StrategyMemoryStats(
        id=f"stats-{strategy_id}-{context_key}".replace(":", "-"),
        strategy_id=strategy_id,
        context_key=context_key,
        uses=uses,
        avg_blended_reward=avg_reward,
        overrule_rate=overrule_rate,
    )


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
                StrategyMemoryStats(
                    id="stats-context-low",
                    strategy_id="seed:aaa_low_reward",
                    context_key="java_backend:senior:system_design",
                    uses=40,
                    avg_blended_reward=0.95,
                    overrule_rate=0.0,
                ),
                StrategyMemoryStats(
                    id="stats-context-high",
                    strategy_id="seed:zzz_high_reward",
                    context_key="java_backend:senior:system_design",
                    uses=40,
                    avg_blended_reward=0.1,
                    overrule_rate=0.5,
                ),
            ]
        )
        sess.commit()

    @contextmanager
    def get_session():
        with Session() as sess:
            yield sess

    return get_session


def _db_session_context_many_candidates(
    *,
    context_key: str = "java_backend:senior:system_design",
    stats_uses: int = 40,
    stats_overrule_rate: float = 0.0,
    include_exact_stats: bool = True,
    include_fallback_stats: bool = False,
):
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)

    strategy_ids = [
        ("seed:aaa_low_reward", "aaa_low_reward"),
        ("seed:bbb_mid_reward", "bbb_mid_reward"),
        ("seed:ccc_neutral_reward", "ccc_neutral_reward"),
        ("seed:ddd_other_reward", "ddd_other_reward"),
        ("seed:zzz_high_reward", "zzz_high_reward"),
    ]
    with Session() as sess:
        sess.add_all([
            _strategy(strategy_id, slug)
            for strategy_id, slug in strategy_ids
        ])
        if include_exact_stats:
            sess.add_all(
                [
                    _stats(
                        strategy_id="seed:aaa_low_reward",
                        context_key=context_key,
                        avg_reward=0.1,
                        uses=stats_uses,
                        overrule_rate=stats_overrule_rate,
                    ),
                    _stats(
                        strategy_id="seed:bbb_mid_reward",
                        context_key=context_key,
                        avg_reward=0.2,
                        uses=stats_uses,
                        overrule_rate=stats_overrule_rate,
                    ),
                    _stats(
                        strategy_id="seed:ccc_neutral_reward",
                        context_key=context_key,
                        avg_reward=0.3,
                        uses=stats_uses,
                        overrule_rate=stats_overrule_rate,
                    ),
                    _stats(
                        strategy_id="seed:ddd_other_reward",
                        context_key=context_key,
                        avg_reward=0.4,
                        uses=stats_uses,
                        overrule_rate=stats_overrule_rate,
                    ),
                    _stats(
                        strategy_id="seed:zzz_high_reward",
                        context_key=context_key,
                        avg_reward=0.95,
                        uses=stats_uses,
                        overrule_rate=stats_overrule_rate,
                    ),
                ]
            )
        if include_fallback_stats:
            sess.add(
                _stats(
                    strategy_id="seed:zzz_high_reward",
                    context_key="senior:system_design",
                    avg_reward=0.95,
                )
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
    assert entries[1].ranking_reason["stats_context_key"] == "__global__"
    assert entries[1].ranking_reason["stats_scope"] == "global"
    assert entries[1].ranking_reason["scope_weight"] == 0.15


def test_reward_mode_falls_back_to_metadata_when_only_global_stats(monkeypatch) -> None:
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
        "seed:aaa_low_reward",
        "seed:zzz_high_reward",
    ]
    assert entries[0].ranking_reason["live_order"] == "metadata_fallback"
    assert "global_prior_only" in entries[1].ranking_reason["gate_reasons"]


def test_reward_shadow_prefers_exact_context_stats_without_changing_order(
    monkeypatch,
) -> None:
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
        policy_context_keys=[
            "java_backend:senior:system_design",
            "senior:system_design",
        ],
        limit=2,
    )

    assert [entry.id for entry in entries] == [
        "seed:aaa_low_reward",
        "seed:zzz_high_reward",
    ]
    assert entries[0].shadow_rank == 1
    assert entries[0].ranking_reason["stats_context_key"] == (
        "java_backend:senior:system_design"
    )
    assert entries[0].ranking_reason["stats_scope"] == "exact"
    assert entries[0].ranking_reason["scope_weight"] == 1.0
    assert entries[0].ranking_reason["avg_blended_reward"] == 0.95
    assert entries[1].shadow_rank == 2


def test_reward_mode_uses_exact_context_stats_when_gate_passes(monkeypatch) -> None:
    monkeypatch.setattr(
        ss,
        "get_settings",
        lambda: SimpleNamespace(
            strategy_memory_backend="db",
            strategy_memory_ranking_mode="reward",
        ),
    )
    monkeypatch.setattr(ss, "get_session", _db_session_context_many_candidates())

    entries = ss.retrieve_strategies(
        dimension="system_design",
        job_level="senior",
        policy_context_keys=[
            "java_backend:senior:system_design",
            "senior:system_design",
        ],
        limit=2,
    )

    assert [entry.id for entry in entries] == [
        "seed:zzz_high_reward",
        "seed:ddd_other_reward",
    ]
    assert entries[0].ranking_reason["stats_scope"] == "exact"
    assert entries[0].ranking_reason["live_order"] == "reward"
    assert entries[0].ranking_reason["gate_status"] == "eligible"


def test_reward_mode_falls_back_when_exact_context_samples_are_low(monkeypatch) -> None:
    monkeypatch.setattr(
        ss,
        "get_settings",
        lambda: SimpleNamespace(
            strategy_memory_backend="db",
            strategy_memory_ranking_mode="reward",
        ),
    )
    monkeypatch.setattr(
        ss,
        "get_session",
        _db_session_context_many_candidates(stats_uses=5),
    )

    entries = ss.retrieve_strategies(
        dimension="system_design",
        job_level="senior",
        policy_context_keys=[
            "java_backend:senior:system_design",
            "senior:system_design",
        ],
        limit=2,
    )

    assert [entry.id for entry in entries] == [
        "seed:aaa_low_reward",
        "seed:bbb_mid_reward",
    ]
    metadata_second = next(
        entry for entry in entries if entry.id == "seed:bbb_mid_reward"
    )
    assert metadata_second.ranking_reason["live_order"] == "metadata_fallback"
    assert metadata_second.ranking_reason["sample_confidence"] == 0.25

    all_entries = ss.retrieve_strategies(
        dimension="system_design",
        job_level="senior",
        policy_context_keys=[
            "java_backend:senior:system_design",
            "senior:system_design",
        ],
        limit=5,
    )
    zzz = next(entry for entry in all_entries if entry.id == "seed:zzz_high_reward")
    assert zzz.ranking_reason["sample_confidence"] == 0.25
    assert "reward_samples_below_min" in zzz.ranking_reason["gate_reasons"]


def test_reward_mode_falls_back_when_overrule_rate_is_high(monkeypatch) -> None:
    monkeypatch.setattr(
        ss,
        "get_settings",
        lambda: SimpleNamespace(
            strategy_memory_backend="db",
            strategy_memory_ranking_mode="reward",
        ),
    )
    monkeypatch.setattr(
        ss,
        "get_session",
        _db_session_context_many_candidates(stats_overrule_rate=0.5),
    )

    entries = ss.retrieve_strategies(
        dimension="system_design",
        job_level="senior",
        policy_context_keys=[
            "java_backend:senior:system_design",
            "senior:system_design",
        ],
        limit=5,
    )

    assert [entry.id for entry in entries[:2]] == [
        "seed:aaa_low_reward",
        "seed:bbb_mid_reward",
    ]
    zzz = next(entry for entry in entries if entry.id == "seed:zzz_high_reward")
    assert zzz.ranking_reason["live_order"] == "metadata_fallback"
    assert "overrule_rate_high" in zzz.ranking_reason["gate_reasons"]


def test_reward_shadow_uses_weaker_weight_for_fallback_context_stats(monkeypatch) -> None:
    monkeypatch.setattr(
        ss,
        "get_settings",
        lambda: SimpleNamespace(
            strategy_memory_backend="db",
            strategy_memory_ranking_mode="reward_shadow",
        ),
    )
    monkeypatch.setattr(
        ss,
        "get_session",
        _db_session_context_many_candidates(
            include_exact_stats=False,
            include_fallback_stats=True,
        ),
    )

    entries = ss.retrieve_strategies(
        dimension="system_design",
        job_level="senior",
        policy_context_keys=[
            "java_backend:senior:system_design",
            "senior:system_design",
        ],
        limit=5,
    )

    zzz = next(entry for entry in entries if entry.id == "seed:zzz_high_reward")
    assert zzz.ranking_reason["stats_scope"] == "fallback"
    assert zzz.ranking_reason["scope_weight"] == 0.5
    assert zzz.ranking_reason["reward_bonus"] < 0.5
