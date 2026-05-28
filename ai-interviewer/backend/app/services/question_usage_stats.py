"""Aggregate question-bank usage rows into reward-shadow stats."""
from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from math import log as math_log
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.settings import get_settings
from app.models.question_bank import (
    QuestionRewardRollout,
    QuestionSeed,
    QuestionUsage,
    QuestionUsageStats,
    QuestionVariant,
)

MIN_REWARDED_USES = 20
MIN_CANDIDATES = 5
HIGH_REWARD_THRESHOLD = 0.75
TOP_K = 3
REWARD_SHADOW_BONUS_WEIGHT = 20.0
REWARD_RANKING_MODE = "reward_shadow"
QUESTION_REWARD_ROLLOUT_MODES = {"metadata", "reward_shadow", "reward"}
DEFAULT_ROLLOUT_MODE = "reward_shadow"
CONTEXT_SCOPE = "context"
SEED_SCOPE = "seed"


@dataclass(frozen=True)
class QuestionUsageStatsResult:
    refreshed: int = 0
    deleted: int = 0


def build_question_reward_context_key(
    *,
    direction_tags: list[str] | tuple[str, ...] | None = None,
    role_tags: list[str] | tuple[str, ...] | None = None,
    job_level: str | None = None,
    dimension: str | None = None,
) -> str:
    """Return the stable context key used by question reward rollout."""

    direction = _first_slug(direction_tags) or "unknown_direction"
    role = _first_slug(role_tags) or "unknown_role"
    level = _slugify(job_level) or "unknown_level"
    dim = _slugify(dimension) or "unknown_dimension"
    return f"{direction}:{role}:{level}:{dim}"


def question_reward_rollout_id(*, scope: str, scope_key: str) -> str:
    return f"{_clean_scope(scope)}:{str(scope_key or '').strip()}"


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

    session.flush()
    usage_rows = list(session.scalars(select(QuestionUsage)))
    if not usage_rows:
        return {
            "thresholds": _thresholds(),
            **_empty_readiness_payload(),
            "modes": [],
            "variants": [],
        }
    variant_ids = {
        str(row.variant_id or "").strip()
        for row in usage_rows
        if str(row.variant_id or "").strip()
    }
    joined_rows = (
        session.execute(
            select(QuestionSeed, QuestionVariant)
            .join(QuestionVariant, QuestionVariant.seed_id == QuestionSeed.id)
            .where(QuestionVariant.id.in_(variant_ids))
            .where(QuestionSeed.status == "active")
            .where(QuestionVariant.status == "active")
        ).all()
        if variant_ids
        else []
    )
    metadata_by_variant = {
        variant.id: _variant_metadata(seed, variant)
        for seed, variant in joined_rows
    }
    active_variants_by_seed: dict[str, list[str]] = defaultdict(list)
    for seed, variant in joined_rows:
        active_variants_by_seed[seed.id].append(variant.id)
    rows_by_variant: dict[str, list[QuestionUsage]] = defaultdict(list)
    for row in usage_rows:
        variant_id = str(row.variant_id or "").strip()
        if variant_id in metadata_by_variant:
            rows_by_variant[variant_id].append(row)

    variant_payloads = [
        _variant_readiness_payload(
            variant_id,
            rows,
            metadata_by_variant[variant_id],
        )
        for variant_id, rows in rows_by_variant.items()
    ]
    metadata_top = _top_variant_ids(variant_payloads, score_key="metadata_score")
    reward_top = _top_variant_ids(variant_payloads, score_key="reward_shadow_score")
    rank_changed = metadata_top != reward_top
    usage_count = sum(int(row.get("uses") or 0) for row in variant_payloads)
    rewarded_usage_count = sum(
        int(row.get("rewarded_uses") or 0)
        for row in variant_payloads
    )
    readiness, reasons = _readiness(
        candidate_count=len(variant_payloads),
        rewarded_usage_count=rewarded_usage_count,
        rank_changed=rank_changed,
    )
    rollouts = _rollouts_by_scope(session)
    contexts = _context_readiness_payloads(
        usage_rows,
        metadata_by_variant=metadata_by_variant,
        rollouts=rollouts,
    )
    seeds = _seed_readiness_payloads(
        usage_rows,
        metadata_by_variant=metadata_by_variant,
        active_variants_by_seed=active_variants_by_seed,
        rollouts=rollouts,
    )
    return {
        "thresholds": _thresholds(),
        "summary": _summary_payload(
            variant_payloads,
            candidate_count=len(variant_payloads),
            usage_count=usage_count,
            rewarded_usage_count=rewarded_usage_count,
            rank_changed=rank_changed,
            readiness=readiness,
        ),
        "selector_rollout_mode": _selector_rollout_mode(),
        "reward_ranking_mode": REWARD_RANKING_MODE,
        "candidate_count": len(variant_payloads),
        "usage_count": usage_count,
        "rewarded_usage_count": rewarded_usage_count,
        "metadata_top_variant_ids": metadata_top,
        "reward_top_variant_ids": reward_top,
        "rank_changed": rank_changed,
        "readiness": readiness,
        "reasons": reasons,
        "modes": [],
        "contexts": contexts,
        "seeds": seeds,
        "variants": sorted(
            variant_payloads,
            key=lambda item: (
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
        "min_candidates": MIN_CANDIDATES,
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
    variant_id: str,
    rows: list[QuestionUsage],
    metadata: dict[str, Any] | None,
) -> dict[str, Any]:
    rewarded = [
        row for row in rows
        if row.immediate_reward is not None
    ]
    scored = [row for row in rewarded if row.score is not None]
    passed = [row.passed for row in rewarded if row.passed is not None]
    rewarded_uses = len(rewarded)
    uses = len(rows)
    sample_confidence = min(1.0, rewarded_uses / MIN_REWARDED_USES)
    avg_reward = _avg([row.immediate_reward for row in rewarded])
    base_score = float((metadata or {}).get("metadata_score") or 0.0)
    reward_bonus = (
        float(avg_reward or 0.0)
        * REWARD_SHADOW_BONUS_WEIGHT
        * sample_confidence
    )
    usage_bonus = math_log(uses + 1) * 0.1 * sample_confidence
    reward_shadow_score = base_score + reward_bonus + usage_bonus
    reasons: list[str] = []
    if rewarded_uses < MIN_REWARDED_USES:
        reasons.append("reward_samples_below_min")
    if (avg_reward or 0.0) >= HIGH_REWARD_THRESHOLD and reasons:
        reasons.append("high_reward_low_sample")
    readiness = "ready" if not reasons else "shadow_only"
    observed_modes = sorted(
        {
            str(row.question_selector_mode or "").strip()
            for row in rows
            if str(row.question_selector_mode or "").strip()
        }
    )
    return {
        "variant_id": variant_id,
        "seed_id": (metadata or {}).get("seed_id"),
        "title": (metadata or {}).get("title"),
        "dimension": (metadata or {}).get("dimension"),
        "observed_selector_modes": observed_modes,
        "question_selector_mode": (
            observed_modes[0] if len(observed_modes) == 1 else "mixed"
        ),
        "uses": uses,
        "injected_uses": sum(1 for row in rows if bool(row.injected)),
        "rewarded_uses": rewarded_uses,
        "avg_score": _avg([row.score for row in scored]),
        "pass_rate": _rate(passed),
        "avg_immediate_reward": avg_reward,
        "metadata_score": base_score,
        "reward_shadow_score": reward_shadow_score,
        "sample_confidence": sample_confidence,
        "readiness": readiness,
        "reasons": reasons,
    }


def _context_readiness_payloads(
    usage_rows: list[QuestionUsage],
    *,
    metadata_by_variant: dict[str, dict[str, Any]],
    rollouts: dict[tuple[str, str], QuestionRewardRollout],
) -> list[dict[str, Any]]:
    rows_by_context: dict[str, dict[str, list[QuestionUsage]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for row in usage_rows:
        context_key = str(getattr(row, "question_context_key", "") or "").strip()
        variant_id = str(row.variant_id or "").strip()
        if not context_key or variant_id not in metadata_by_variant:
            continue
        rows_by_context[context_key][variant_id].append(row)

    payloads: list[dict[str, Any]] = []
    for context_key, rows_by_variant in rows_by_context.items():
        variants = [
            _variant_readiness_payload(
                variant_id,
                rows,
                metadata_by_variant.get(variant_id),
            )
            for variant_id, rows in rows_by_variant.items()
        ]
        payload = _readiness_group_payload(
            scope=CONTEXT_SCOPE,
            scope_key=context_key,
            variants=variants,
            rollout=_rollout_payload(
                rollouts,
                scope=CONTEXT_SCOPE,
                scope_key=context_key,
            ),
        )
        payload["context_key"] = context_key
        payloads.append(payload)
    return sorted(payloads, key=lambda item: str(item.get("context_key") or ""))


def _seed_readiness_payloads(
    usage_rows: list[QuestionUsage],
    *,
    metadata_by_variant: dict[str, dict[str, Any]],
    active_variants_by_seed: dict[str, list[str]],
    rollouts: dict[tuple[str, str], QuestionRewardRollout],
) -> list[dict[str, Any]]:
    rows_by_seed_variant: dict[str, dict[str, list[QuestionUsage]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for row in usage_rows:
        variant_id = str(row.variant_id or "").strip()
        metadata = metadata_by_variant.get(variant_id)
        if not metadata:
            continue
        seed_id = str(metadata.get("seed_id") or row.seed_id or "").strip()
        if not seed_id:
            continue
        rows_by_seed_variant[seed_id][variant_id].append(row)

    seed_ids = set(active_variants_by_seed) | set(rows_by_seed_variant)
    payloads: list[dict[str, Any]] = []
    for seed_id in seed_ids:
        variant_ids = sorted(set(active_variants_by_seed.get(seed_id, [])))
        rows_by_variant = rows_by_seed_variant.get(seed_id, {})
        variants = [
            _variant_readiness_payload(
                variant_id,
                rows_by_variant.get(variant_id, []),
                metadata_by_variant.get(variant_id),
            )
            for variant_id in variant_ids
            if variant_id in metadata_by_variant
        ]
        payload = _readiness_group_payload(
            scope=SEED_SCOPE,
            scope_key=seed_id,
            variants=variants,
            rollout=_rollout_payload(
                rollouts,
                scope=SEED_SCOPE,
                scope_key=seed_id,
            ),
        )
        payload["seed_id"] = seed_id
        payload["active_variant_count"] = len(variant_ids)
        payloads.append(payload)
    return sorted(payloads, key=lambda item: str(item.get("seed_id") or ""))


def _readiness_group_payload(
    *,
    scope: str,
    scope_key: str,
    variants: list[dict[str, Any]],
    rollout: dict[str, Any],
) -> dict[str, Any]:
    metadata_top = _top_variant_ids(variants, score_key="metadata_score")
    reward_top = _top_variant_ids(variants, score_key="reward_shadow_score")
    rank_changed = metadata_top != reward_top
    usage_count = sum(int(row.get("uses") or 0) for row in variants)
    rewarded_usage_count = sum(int(row.get("rewarded_uses") or 0) for row in variants)
    readiness, reasons = _readiness(
        candidate_count=len(variants),
        rewarded_usage_count=rewarded_usage_count,
        rank_changed=rank_changed,
    )
    return {
        "scope": scope,
        "scope_key": scope_key,
        "rollout": rollout,
        "candidate_count": len(variants),
        "usage_count": usage_count,
        "rewarded_usage_count": rewarded_usage_count,
        "metadata_top_variant_ids": metadata_top,
        "reward_top_variant_ids": reward_top,
        "rank_changed": rank_changed,
        "readiness": readiness,
        "reasons": reasons,
        "variants": sorted(
            variants,
            key=lambda item: str(item.get("variant_id") or ""),
        ),
    }


def _rollouts_by_scope(
    session: Session,
) -> dict[tuple[str, str], QuestionRewardRollout]:
    rows = list(session.scalars(select(QuestionRewardRollout)))
    return {
        (str(row.scope or "").strip(), str(row.scope_key or "").strip()): row
        for row in rows
    }


def _rollout_payload(
    rollouts: dict[tuple[str, str], QuestionRewardRollout],
    *,
    scope: str,
    scope_key: str,
) -> dict[str, Any]:
    row = rollouts.get((scope, scope_key))
    if row is None:
        return {
            "scope": scope,
            "scope_key": scope_key,
            "mode": DEFAULT_ROLLOUT_MODE,
            "source": "default",
            "reason": "",
            "created_at": None,
            "updated_at": None,
        }
    return {
        "id": row.id,
        "scope": row.scope,
        "scope_key": row.scope_key,
        "mode": row.mode,
        "source": "override",
        "reason": row.reason,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _top_variant_ids(
    variants: list[dict[str, Any]],
    *,
    score_key: str,
) -> list[str]:
    ranked = sorted(
        variants,
        key=lambda item: (
            -float(item.get(score_key) or 0.0),
            str(item.get("variant_id") or ""),
        ),
    )
    return [
        str(item.get("variant_id") or "")
        for item in ranked[:TOP_K]
    ]


def _readiness(
    *,
    candidate_count: int,
    rewarded_usage_count: int,
    rank_changed: bool,
) -> tuple[str, list[str]]:
    if candidate_count < MIN_CANDIDATES:
        return "needs_candidates", ["candidate_pool_below_min"]
    if rewarded_usage_count < MIN_REWARDED_USES:
        return "needs_samples", ["reward_samples_below_min"]
    if rank_changed:
        return "ready", ["reward_shadow_rank_changed"]
    return "shadow_only", ["reward_shadow_rank_same"]


def _summary_payload(
    variants: list[dict[str, Any]],
    *,
    candidate_count: int | None = None,
    usage_count: int | None = None,
    rewarded_usage_count: int | None = None,
    rank_changed: bool = False,
    readiness: str | None = None,
) -> dict[str, Any]:
    return {
        "candidate_count": len(variants) if candidate_count is None else candidate_count,
        "usage_count": sum(
            int(row.get("uses") or 0) for row in variants
        ) if usage_count is None else usage_count,
        "rewarded_usage_count": sum(
            int(row.get("rewarded_uses") or 0) for row in variants
        ) if rewarded_usage_count is None else rewarded_usage_count,
        "rank_changed": rank_changed,
        "readiness": readiness or "needs_candidates",
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
        "shadow_changed_modes": 1 if rank_changed else 0,
    }


def _empty_readiness_payload() -> dict[str, Any]:
    selector_mode = _selector_rollout_mode()
    return {
        "summary": _summary_payload([]),
        "selector_rollout_mode": selector_mode,
        "reward_ranking_mode": REWARD_RANKING_MODE,
        "candidate_count": 0,
        "usage_count": 0,
        "rewarded_usage_count": 0,
        "metadata_top_variant_ids": [],
        "reward_top_variant_ids": [],
        "rank_changed": False,
        "readiness": "needs_candidates",
        "reasons": ["candidate_pool_below_min"],
        "contexts": [],
        "seeds": [],
    }


def _selector_rollout_mode() -> str:
    return str(
        getattr(get_settings(), "question_selector_mode", "structured_primary")
    )


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


def _first_slug(values: list[str] | tuple[str, ...] | None) -> str:
    for value in values or []:
        slug = _slugify(value)
        if slug:
            return slug
    return ""


def _slugify(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[^\w]+", "_", text, flags=re.UNICODE)
    text = re.sub(r"_+", "_", text)
    return text.strip("_")


def _clean_scope(scope: str) -> str:
    clean = str(scope or "").strip().lower()
    if clean not in {CONTEXT_SCOPE, SEED_SCOPE}:
        return clean
    return clean
