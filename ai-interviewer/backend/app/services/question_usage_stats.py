"""Aggregate question-bank usage rows into reward-shadow stats."""
from __future__ import annotations

import hashlib
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from math import log as math_log
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.question_bank import (
    QuestionSeed,
    QuestionUsage,
    QuestionUsageStats,
    QuestionVariant,
)

MIN_REWARDED_USES = 20
HIGH_REWARD_THRESHOLD = 0.75
TOP_K = 3
REWARD_SHADOW_BONUS_WEIGHT = 20.0


@dataclass(frozen=True)
class QuestionUsageStatsResult:
    refreshed: int = 0
    deleted: int = 0


def refresh_question_usage_stats(*, session: Session) -> QuestionUsageStatsResult:
    """Refresh materialized question usage stats from usage facts."""

    session.flush()
    usages = list(session.scalars(select(QuestionUsage)))
    groups: dict[tuple[str, str], list[QuestionUsage]] = defaultdict(list)
    for usage in usages:
        variant_id = str(usage.variant_id or "").strip()
        mode = str(usage.question_selector_mode or "").strip()
        if not variant_id or not mode:
            continue
        groups[(variant_id, mode)].append(usage)

    seen_ids: set[str] = set()
    for (variant_id, mode), rows in groups.items():
        stat_id = _stats_id(variant_id, mode)
        seen_ids.add(stat_id)
        row = session.get(QuestionUsageStats, stat_id)
        if row is None:
            row = QuestionUsageStats(
                id=stat_id,
                variant_id=variant_id,
                question_selector_mode=mode,
            )
            session.add(row)
        _apply_stats(row, rows)

    deleted = 0
    for stale in session.scalars(select(QuestionUsageStats)):
        if stale.id not in seen_ids:
            session.delete(stale)
            deleted += 1

    if groups or deleted:
        session.flush()
    return QuestionUsageStatsResult(refreshed=len(seen_ids), deleted=deleted)


def build_question_reward_readiness(*, session: Session) -> dict[str, Any]:
    """Return shadow-only readiness diagnostics for question reward ranking."""

    stats_rows = list(session.scalars(select(QuestionUsageStats)))
    if not stats_rows:
        return {
            "thresholds": _thresholds(),
            "summary": _summary_payload([]),
            "modes": [],
            "variants": [],
        }
    variant_ids = {row.variant_id for row in stats_rows if row.variant_id}
    joined_rows = (
        session.execute(
            select(QuestionSeed, QuestionVariant)
            .join(QuestionVariant, QuestionVariant.seed_id == QuestionSeed.id)
            .where(QuestionVariant.id.in_(variant_ids))
        ).all()
        if variant_ids
        else []
    )
    metadata_by_variant = {
        variant.id: _variant_metadata(seed, variant)
        for seed, variant in joined_rows
    }
    variant_payloads = [
        _variant_readiness_payload(row, metadata_by_variant.get(row.variant_id))
        for row in stats_rows
    ]
    modes = _mode_payloads(variant_payloads)
    return {
        "thresholds": _thresholds(),
        "summary": _summary_payload(variant_payloads, modes=modes),
        "modes": modes,
        "variants": sorted(
            variant_payloads,
            key=lambda item: (
                str(item.get("question_selector_mode") or ""),
                str(item.get("variant_id") or ""),
            ),
        ),
    }


def _apply_stats(row: QuestionUsageStats, usages: list[QuestionUsage]) -> None:
    rewarded = [
        usage
        for usage in usages
        if bool(usage.injected) and usage.immediate_reward is not None
    ]
    scored = [usage for usage in rewarded if usage.score is not None]
    passed = [usage.passed for usage in rewarded if usage.passed is not None]
    row.uses = len(usages)
    row.injected_uses = sum(1 for usage in usages if bool(usage.injected))
    row.rewarded_uses = len(rewarded)
    row.avg_score = _avg([usage.score for usage in scored])
    row.pass_rate = _rate(passed)
    row.avg_immediate_reward = _avg([usage.immediate_reward for usage in rewarded])
    row.last_used_at = max(
        (usage.created_at for usage in usages if usage.created_at is not None),
        default=None,
    )
    row.updated_at = datetime.now(UTC)


def _thresholds() -> dict[str, Any]:
    return {
        "min_rewarded_uses": MIN_REWARDED_USES,
        "high_reward_threshold": HIGH_REWARD_THRESHOLD,
        "top_k": TOP_K,
    }


def _variant_metadata(seed: QuestionSeed, variant: QuestionVariant) -> dict[str, Any]:
    return {
        "seed_id": seed.id,
        "title": seed.title,
        "dimension": seed.dimension,
        "seed_priority": int(seed.priority or 0),
        "variant_priority": int(variant.priority or 0),
        "metadata_score": float(int(seed.priority or 0) + int(variant.priority or 0)),
    }


def _variant_readiness_payload(
    row: QuestionUsageStats,
    metadata: dict[str, Any] | None,
) -> dict[str, Any]:
    sample_confidence = min(1.0, int(row.rewarded_uses or 0) / MIN_REWARDED_USES)
    avg_reward = row.avg_immediate_reward
    base_score = float((metadata or {}).get("metadata_score") or 0.0)
    reward_bonus = (
        float(avg_reward or 0.0)
        * REWARD_SHADOW_BONUS_WEIGHT
        * sample_confidence
    )
    usage_bonus = math_log(int(row.uses or 0) + 1) * 0.1 * sample_confidence
    reward_shadow_score = base_score + reward_bonus + usage_bonus
    reasons: list[str] = []
    if int(row.rewarded_uses or 0) < MIN_REWARDED_USES:
        reasons.append("reward_samples_below_min")
    if (avg_reward or 0.0) >= HIGH_REWARD_THRESHOLD and reasons:
        reasons.append("high_reward_low_sample")
    readiness = "ready" if not reasons else "shadow_only"
    return {
        "variant_id": row.variant_id,
        "seed_id": (metadata or {}).get("seed_id"),
        "title": (metadata or {}).get("title"),
        "dimension": (metadata or {}).get("dimension"),
        "question_selector_mode": row.question_selector_mode,
        "uses": row.uses,
        "injected_uses": row.injected_uses,
        "rewarded_uses": row.rewarded_uses,
        "avg_score": row.avg_score,
        "pass_rate": row.pass_rate,
        "avg_immediate_reward": row.avg_immediate_reward,
        "metadata_score": base_score,
        "reward_shadow_score": reward_shadow_score,
        "sample_confidence": sample_confidence,
        "readiness": readiness,
        "reasons": reasons,
    }


def _mode_payloads(variants: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_mode: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for variant in variants:
        by_mode[str(variant.get("question_selector_mode") or "")].append(variant)
    modes: list[dict[str, Any]] = []
    for mode, rows in sorted(by_mode.items()):
        metadata_ranked = sorted(
            rows,
            key=lambda item: (
                -float(item.get("metadata_score") or 0.0),
                str(item.get("variant_id") or ""),
            ),
        )
        reward_ranked = sorted(
            rows,
            key=lambda item: (
                -float(item.get("reward_shadow_score") or 0.0),
                str(item.get("variant_id") or ""),
            ),
        )
        metadata_top = [
            str(item.get("variant_id") or "")
            for item in metadata_ranked[:TOP_K]
        ]
        reward_top = [
            str(item.get("variant_id") or "")
            for item in reward_ranked[:TOP_K]
        ]
        rank_changed = metadata_top != reward_top
        reasons = ["reward_shadow_rank_changed"] if rank_changed else [
            "reward_shadow_rank_same"
        ]
        modes.append({
            "question_selector_mode": mode,
            "metadata_top_variant_ids": metadata_top,
            "reward_top_variant_ids": reward_top,
            "rank_changed": rank_changed,
            "reasons": reasons,
        })
    return modes


def _summary_payload(
    variants: list[dict[str, Any]],
    *,
    modes: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    modes = modes or []
    return {
        "total_variants": len(variants),
        "ready_variants": sum(
            1 for row in variants if row.get("readiness") == "ready"
        ),
        "low_sample_variants": sum(
            1
            for row in variants
            if "reward_samples_below_min" in set(row.get("reasons") or [])
        ),
        "high_reward_low_sample_variants": sum(
            1
            for row in variants
            if "high_reward_low_sample" in set(row.get("reasons") or [])
        ),
        "shadow_changed_modes": sum(
            1 for row in modes if bool(row.get("rank_changed"))
        ),
    }


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


def _stats_id(variant_id: str, mode: str) -> str:
    digest = hashlib.sha1(
        f"{variant_id}|{mode}".encode("utf-8"),
        usedforsecurity=False,
    ).hexdigest()
    return f"question-usage-stats:{digest[:32]}"
