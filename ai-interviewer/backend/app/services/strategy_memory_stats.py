"""Aggregate strategy-memory usage rows into reward-health stats."""
from __future__ import annotations

import hashlib
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.strategy_memory import StrategyMemoryStats, StrategyMemoryUsage

GLOBAL_CONTEXT_KEY = "__global__"


@dataclass(frozen=True)
class StrategyMemoryStatsResult:
    refreshed: int = 0
    deleted: int = 0


def refresh_strategy_memory_stats(*, session: Session) -> StrategyMemoryStatsResult:
    """Refresh materialized strategy stats from usage facts.

    The refresh is idempotent: all stats rows are keyed by
    ``strategy_id + context_key`` and stale rows are removed when their
    source usages disappear.
    """

    session.flush()
    usages = list(session.scalars(select(StrategyMemoryUsage)))
    groups: dict[tuple[str, str], list[StrategyMemoryUsage]] = defaultdict(list)
    for usage in usages:
        context_key = str(usage.context_key or "").strip()
        if context_key and context_key != GLOBAL_CONTEXT_KEY:
            groups[(usage.strategy_id, context_key)].append(usage)
        groups[(usage.strategy_id, GLOBAL_CONTEXT_KEY)].append(usage)

    seen_ids: set[str] = set()
    for (strategy_id, context_key), rows in groups.items():
        stat_id = _stats_id(strategy_id, context_key)
        seen_ids.add(stat_id)
        row = session.get(StrategyMemoryStats, stat_id)
        if row is None:
            row = StrategyMemoryStats(
                id=stat_id,
                strategy_id=strategy_id,
                context_key=context_key,
            )
            session.add(row)
        _apply_stats(row, rows)

    deleted = 0
    for stale in session.scalars(select(StrategyMemoryStats)):
        if stale.id not in seen_ids:
            session.delete(stale)
            deleted += 1

    if groups or deleted:
        session.flush()
    return StrategyMemoryStatsResult(refreshed=len(seen_ids), deleted=deleted)


def _apply_stats(row: StrategyMemoryStats, usages: list[StrategyMemoryUsage]) -> None:
    row.uses = len(usages)
    row.avg_score = _avg([usage.score for usage in usages])
    row.pass_rate = _rate([usage.passed for usage in usages])
    row.avg_immediate_reward = _avg([usage.immediate_reward for usage in usages])
    row.avg_delayed_reward = _avg([usage.delayed_reward for usage in usages])
    row.avg_blended_reward = _avg([
        _blended_reward(usage)
        for usage in usages
    ])
    row.overrule_rate = _rate([usage.verifier_overruled for usage in usages])
    row.helpful_avg = _avg([usage.helpful_score for usage in usages])
    row.last_used_at = max(
        (usage.created_at for usage in usages if usage.created_at is not None),
        default=None,
    )
    row.updated_at = datetime.now(UTC)


def _blended_reward(usage: StrategyMemoryUsage) -> float | None:
    if usage.delayed_reward is not None:
        return usage.delayed_reward
    return usage.immediate_reward


def _avg(values: list[float | None]) -> float | None:
    numeric = [float(value) for value in values if value is not None]
    if not numeric:
        return None
    return sum(numeric) / len(numeric)


def _rate(values: list[bool | None]) -> float | None:
    observed = [bool(value) for value in values if value is not None]
    if not observed:
        return None
    return sum(1 for value in observed if value) / len(observed)


def _stats_id(strategy_id: str, context_key: str) -> str:
    digest = hashlib.sha1(
        f"{strategy_id}|{context_key}".encode("utf-8"),
        usedforsecurity=False,
    ).hexdigest()
    return f"strategy-stats:{digest[:32]}"
