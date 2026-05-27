"""Reward-ranking readiness diagnostics for strategy memories."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from math import log as math_log
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.strategy_memory import (
    StrategyMemory,
    StrategyMemoryStats,
    StrategyMemoryUsage,
)

MIN_CANDIDATES = 5
MIN_REWARDED_USAGES = 20
MIN_DISTINCT_SESSIONS = 10
MAX_OVERRULE_RATE = 0.25
TOP_K = 3


@dataclass(frozen=True)
class _ContextParts:
    direction: str | None
    job_level: str | None
    dimension: str


def build_strategy_reward_readiness(*, session: Session) -> dict[str, Any]:
    """Return context-level readiness for enabling reward-ranked retrieval.

    This is an observability surface only. It evaluates whether the current
    ``reward_shadow`` data is mature enough to consider switching a context to
    real reward ranking; it never mutates strategies or ranking mode.
    """

    strategies = list(
        session.scalars(
            select(StrategyMemory)
            .where(StrategyMemory.status == "active")
            .order_by(StrategyMemory.slug.asc())
        )
    )
    stats_rows = list(session.scalars(select(StrategyMemoryStats)))
    usage_rows = list(session.scalars(select(StrategyMemoryUsage)))
    stats_by_context_strategy = {
        (row.context_key, row.strategy_id): row
        for row in stats_rows
    }
    usages_by_context: dict[str, list[StrategyMemoryUsage]] = defaultdict(list)
    for usage in usage_rows:
        context_key = str(usage.context_key or "").strip()
        if context_key and context_key != "__global__":
            usages_by_context[context_key].append(usage)

    context_keys = sorted(
        {
            row.context_key
            for row in stats_rows
            if row.context_key and row.context_key != "__global__"
        }
        | set(usages_by_context)
    )
    contexts = [
        _context_payload(
            context_key,
            strategies=strategies,
            stats_by_context_strategy=stats_by_context_strategy,
            usages=usages_by_context.get(context_key, []),
        )
        for context_key in context_keys
    ]
    summary = _summary_payload(contexts)
    return {
        "thresholds": {
            "min_candidates": MIN_CANDIDATES,
            "min_rewarded_usages": MIN_REWARDED_USAGES,
            "min_distinct_sessions": MIN_DISTINCT_SESSIONS,
            "max_overrule_rate": MAX_OVERRULE_RATE,
            "top_k": TOP_K,
        },
        "summary": summary,
        "contexts": contexts,
    }


def _context_payload(
    context_key: str,
    *,
    strategies: list[StrategyMemory],
    stats_by_context_strategy: dict[tuple[str, str], StrategyMemoryStats],
    usages: list[StrategyMemoryUsage],
) -> dict[str, Any]:
    parts = _parse_context_key(context_key)
    candidates = [
        strategy
        for strategy in strategies
        if _strategy_matches_context(strategy, parts)
    ]
    metadata_ranked = sorted(
        candidates,
        key=lambda strategy: (
            -_metadata_score(strategy, parts),
            str(strategy.id or ""),
        ),
    )
    reward_ranked = sorted(
        candidates,
        key=lambda strategy: (
            -_reward_score(
                strategy,
                parts,
                stats_by_context_strategy.get((context_key, strategy.id)),
            ),
            str(strategy.id or ""),
        ),
    )
    metadata_top_ids = [str(strategy.id) for strategy in metadata_ranked[:TOP_K]]
    reward_top_ids = [str(strategy.id) for strategy in reward_ranked[:TOP_K]]
    rank_changed = metadata_top_ids != reward_top_ids
    rewarded_usage_count = sum(
        1
        for usage in usages
        if usage.immediate_reward is not None or usage.delayed_reward is not None
    )
    distinct_sessions = len(
        {
            str(usage.session_id or "").strip()
            for usage in usages
            if str(usage.session_id or "").strip()
        }
    )
    avg_blended_reward = _avg([_blended_reward(usage) for usage in usages])
    overrule_rate = _rate([usage.verifier_overruled for usage in usages])
    readiness, reasons = _readiness(
        candidate_count=len(candidates),
        rewarded_usage_count=rewarded_usage_count,
        distinct_sessions=distinct_sessions,
        overrule_rate=overrule_rate,
        rank_changed=rank_changed,
    )
    return {
        "context_key": context_key,
        "direction": parts.direction,
        "job_level": parts.job_level,
        "dimension": parts.dimension,
        "candidate_count": len(candidates),
        "usage_count": len(usages),
        "rewarded_usage_count": rewarded_usage_count,
        "distinct_sessions": distinct_sessions,
        "avg_blended_reward": avg_blended_reward,
        "overrule_rate": overrule_rate,
        "metadata_top_strategy_ids": metadata_top_ids,
        "reward_top_strategy_ids": reward_top_ids,
        "rank_changed": rank_changed,
        "readiness": readiness,
        "reasons": reasons,
    }


def _readiness(
    *,
    candidate_count: int,
    rewarded_usage_count: int,
    distinct_sessions: int,
    overrule_rate: float | None,
    rank_changed: bool,
) -> tuple[str, list[str]]:
    reasons: list[str] = []
    if candidate_count < MIN_CANDIDATES:
        reasons.append("candidate_pool_below_min")
        return "needs_candidates", reasons
    if rewarded_usage_count < MIN_REWARDED_USAGES:
        reasons.append("reward_samples_below_min")
    if distinct_sessions < MIN_DISTINCT_SESSIONS:
        reasons.append("session_coverage_below_min")
    if reasons:
        return "needs_samples", reasons
    if float(overrule_rate or 0.0) > MAX_OVERRULE_RATE:
        return "blocked_by_overrule", ["overrule_rate_high"]
    if rank_changed:
        return "ready", ["reward_shadow_rank_changed"]
    return "shadow_only", ["reward_shadow_rank_same"]


def _summary_payload(contexts: list[dict[str, Any]]) -> dict[str, Any]:
    counts: dict[str, int] = defaultdict(int)
    for context in contexts:
        counts[str(context.get("readiness") or "unknown")] += 1
    return {
        "total_contexts": len(contexts),
        "ready_contexts": counts["ready"],
        "shadow_only_contexts": counts["shadow_only"],
        "needs_candidate_contexts": counts["needs_candidates"],
        "needs_sample_contexts": counts["needs_samples"],
        "blocked_contexts": counts["blocked_by_overrule"],
    }


def _parse_context_key(context_key: str) -> _ContextParts:
    parts = [part.strip() for part in str(context_key or "").split(":") if part.strip()]
    if len(parts) >= 3:
        return _ContextParts(
            direction=":".join(parts[:-2]),
            job_level=parts[-2],
            dimension=parts[-1],
        )
    if len(parts) == 2:
        return _ContextParts(direction=None, job_level=parts[0], dimension=parts[1])
    return _ContextParts(direction=None, job_level=None, dimension=context_key)


def _strategy_matches_context(strategy: StrategyMemory, parts: _ContextParts) -> bool:
    dimensions = {str(value) for value in (strategy.dimensions or []) if str(value)}
    if dimensions and parts.dimension not in dimensions:
        return False
    levels = {str(value) for value in (strategy.job_levels or []) if str(value)}
    if levels and parts.job_level not in levels:
        return False
    return True


def _metadata_score(strategy: StrategyMemory, parts: _ContextParts) -> float:
    score = float(strategy.priority or 0)
    dimensions = {str(value) for value in (strategy.dimensions or []) if str(value)}
    score += 2.0 if parts.dimension in dimensions else 1.0
    levels = {str(value) for value in (strategy.job_levels or []) if str(value)}
    if levels and parts.job_level in levels:
        score += 1.0
    return score


def _reward_score(
    strategy: StrategyMemory,
    parts: _ContextParts,
    stats: StrategyMemoryStats | None,
) -> float:
    score = _metadata_score(strategy, parts)
    if stats is None:
        return score
    avg_reward = float(stats.avg_blended_reward or 0.0)
    uses = max(0, int(stats.uses or 0))
    overrule_rate = float(stats.overrule_rate or 0.0)
    return score + (avg_reward * 0.5) + (math_log(uses + 1) * 0.1) - (overrule_rate * 0.5)


def _blended_reward(usage: StrategyMemoryUsage) -> float | None:
    if usage.delayed_reward is not None:
        return float(usage.delayed_reward)
    if usage.immediate_reward is not None:
        return float(usage.immediate_reward)
    return None


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
