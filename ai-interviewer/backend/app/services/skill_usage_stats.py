"""Aggregate skill playbook usage rows into reward-shadow diagnostics."""
from __future__ import annotations

import hashlib
import math
import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.skill_playbook import (
    SkillPlaybookCard,
    SkillRewardRollout,
    SkillUsage,
    SkillUsageStats,
)

MIN_REWARDED_USES = 20
HIGH_REWARD_THRESHOLD = 0.75
TOP_K = 3
REWARD_SHADOW_BONUS_WEIGHT = 20.0
MIN_REWARD_CANDIDATE_COUNT = 5
MAX_OVERRULE_RATE = 0.25
SKILL_REWARD_ROLLOUT_MODES = {"metadata", "reward_shadow", "reward"}
DEFAULT_SKILL_REWARD_ROLLOUT_MODE = "reward_shadow"


@dataclass(frozen=True)
class SkillUsageStatsResult:
    refreshed: int = 0
    deleted: int = 0


def skill_usage_context_key(
    *,
    role: str | None,
    job_level: str | None,
    dimension: str | None,
    probe_intent: str | None,
) -> str:
    """Return the stable reward-shadow context key for skill usage."""

    return ":".join(
        [
            _slugify(role) or "general",
            _slugify(job_level) or "mid",
            _slugify(dimension) or "general",
            _slugify(probe_intent) or "none",
        ]
    )


def refresh_skill_usage_stats(*, session: Session) -> SkillUsageStatsResult:
    """Refresh materialized skill usage stats from usage facts."""

    session.flush()
    usages = list(session.scalars(select(SkillUsage)))
    groups: dict[tuple[str, str], list[SkillUsage]] = defaultdict(list)
    for usage in usages:
        skill_id = str(usage.skill_id or "").strip()
        context_key = str(usage.skill_context_key or "").strip()
        if not skill_id or not context_key:
            continue
        groups[(skill_id, context_key)].append(usage)

    seen_ids: set[str] = set()
    for (skill_id, context_key), rows in groups.items():
        stat_id = _stats_id(skill_id, context_key)
        seen_ids.add(stat_id)
        row = session.get(SkillUsageStats, stat_id)
        if row is None:
            first = rows[0]
            row = SkillUsageStats(
                id=stat_id,
                skill_id=skill_id,
                skill_context_key=context_key,
                role=str(first.role or "general"),
                job_level=str(first.job_level or "mid"),
                dimension=str(first.dimension or "general"),
                probe_intent=str(first.probe_intent or "none"),
            )
            session.add(row)
        _apply_stats(row, rows)

    deleted = 0
    for stale in session.scalars(select(SkillUsageStats)):
        if stale.id not in seen_ids:
            session.delete(stale)
            deleted += 1

    if groups or deleted:
        session.flush()
    return SkillUsageStatsResult(refreshed=len(seen_ids), deleted=deleted)


def build_skill_reward_readiness(*, session: Session) -> dict[str, Any]:
    """Return shadow-only readiness diagnostics for skill reward ranking."""

    stats_rows = list(session.scalars(select(SkillUsageStats)))
    cards = {
        row.id: row
        for row in session.scalars(
            select(SkillPlaybookCard).where(SkillPlaybookCard.status != "archived")
        )
    }
    rollouts = {
        row.context_key: row
        for row in session.scalars(select(SkillRewardRollout))
    }
    if not stats_rows:
        return {
            "thresholds": _thresholds(),
            "reward_ranking_mode": DEFAULT_SKILL_REWARD_ROLLOUT_MODE,
            "candidate_count": 0,
            "usage_count": 0,
            "rewarded_usage_count": 0,
            "summary": {
                **_summary_payload([], contexts=[]),
                "total_skills": len(cards),
            },
            "contexts": [],
            "skills": [],
        }

    skill_payloads = [
        _skill_readiness_payload(row, cards.get(row.skill_id))
        for row in stats_rows
    ]
    contexts = _context_payloads(
        skill_payloads,
        cards=list(cards.values()),
        rollouts=rollouts,
    )
    return {
        "thresholds": _thresholds(),
        "reward_ranking_mode": DEFAULT_SKILL_REWARD_ROLLOUT_MODE,
        "candidate_count": sum(int(row.get("candidate_count") or 0) for row in contexts),
        "usage_count": sum(int(row.uses or 0) for row in stats_rows),
        "rewarded_usage_count": sum(int(row.rewarded_uses or 0) for row in stats_rows),
        "summary": {
            **_summary_payload(skill_payloads, contexts=contexts),
            "total_skills": len(cards),
        },
        "contexts": contexts,
        "skills": sorted(
            skill_payloads,
            key=lambda item: (
                str(item.get("skill_context_key") or ""),
                str(item.get("skill_id") or ""),
            ),
        ),
    }


def _apply_stats(row: SkillUsageStats, usages: list[SkillUsage]) -> None:
    rewarded = [
        usage
        for usage in usages
        if bool(usage.injected) and usage.immediate_reward is not None
    ]
    scored = [usage for usage in rewarded if usage.score is not None]
    passed = [usage.passed for usage in rewarded if usage.passed is not None]
    overruled = [bool(usage.verifier_overruled) for usage in rewarded]

    first = usages[0]
    row.role = str(first.role or "general")
    row.job_level = str(first.job_level or "mid")
    row.dimension = str(first.dimension or "general")
    row.probe_intent = str(first.probe_intent or "none")
    row.uses = len(usages)
    row.injected_uses = sum(1 for usage in usages if bool(usage.injected))
    row.rewarded_uses = len(rewarded)
    row.avg_score = _avg([usage.score for usage in scored])
    row.pass_rate = _rate(passed)
    row.avg_immediate_reward = _avg([usage.immediate_reward for usage in rewarded])
    row.avg_blended_reward = row.avg_immediate_reward
    row.overrule_rate = _rate(overruled)
    row.last_used_at = max(
        (usage.created_at for usage in usages if usage.created_at is not None),
        default=None,
    )


def _thresholds() -> dict[str, Any]:
    return {
        "min_rewarded_uses": MIN_REWARDED_USES,
        "high_reward_threshold": HIGH_REWARD_THRESHOLD,
        "top_k": TOP_K,
        "min_candidate_count": MIN_REWARD_CANDIDATE_COUNT,
        "max_overrule_rate": MAX_OVERRULE_RATE,
    }


def _skill_readiness_payload(
    row: SkillUsageStats,
    card: SkillPlaybookCard | None,
) -> dict[str, Any]:
    sample_confidence = min(1.0, int(row.rewarded_uses or 0) / MIN_REWARDED_USES)
    avg_reward = row.avg_blended_reward
    metadata_score = float(int(getattr(card, "priority", 0) or 0))
    reward_bonus = (
        float(avg_reward or 0.0)
        * REWARD_SHADOW_BONUS_WEIGHT
        * sample_confidence
    )
    usage_bonus = math.log(int(row.uses or 0) + 1) * 0.1 * sample_confidence
    reward_shadow_score = metadata_score + reward_bonus + usage_bonus
    reasons: list[str] = []
    if int(row.rewarded_uses or 0) < MIN_REWARDED_USES:
        reasons.append("reward_samples_below_min")
    if (avg_reward or 0.0) >= HIGH_REWARD_THRESHOLD and reasons:
        reasons.append("high_reward_low_sample")
    readiness = "ready" if not reasons else "shadow_only"
    return {
        "skill_id": row.skill_id,
        "name": getattr(card, "name", None),
        "display_name_zh": getattr(card, "display_name_zh", None),
        "skill_context_key": row.skill_context_key,
        "role": row.role,
        "job_level": row.job_level,
        "dimension": row.dimension,
        "probe_intent": row.probe_intent,
        "uses": row.uses,
        "injected_uses": row.injected_uses,
        "rewarded_uses": row.rewarded_uses,
        "avg_score": row.avg_score,
        "pass_rate": row.pass_rate,
        "avg_immediate_reward": row.avg_immediate_reward,
        "avg_blended_reward": row.avg_blended_reward,
        "overrule_rate": row.overrule_rate,
        "metadata_score": metadata_score,
        "reward_shadow_score": reward_shadow_score,
        "sample_confidence": sample_confidence,
        "readiness": readiness,
        "reasons": reasons,
    }


def _context_payloads(
    skills: list[dict[str, Any]],
    *,
    cards: list[SkillPlaybookCard],
    rollouts: dict[str, SkillRewardRollout],
) -> list[dict[str, Any]]:
    by_context: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for skill in skills:
        by_context[str(skill.get("skill_context_key") or "")].append(skill)

    contexts: list[dict[str, Any]] = []
    for context_key, rows in sorted(by_context.items()):
        first = rows[0]
        stats_by_skill = {
            str(row.get("skill_id") or ""): row
            for row in rows
            if row.get("skill_id")
        }
        candidates = _candidate_payloads_for_context(
            cards,
            role=str(first.get("role") or ""),
            job_level=str(first.get("job_level") or ""),
            dimension=str(first.get("dimension") or ""),
            probe_intent=str(first.get("probe_intent") or ""),
            stats_by_skill=stats_by_skill,
        )
        if not candidates:
            candidates = rows
        metadata_ranked = sorted(
            candidates,
            key=lambda item: (
                -float(item.get("metadata_score") or 0.0),
                str(item.get("skill_id") or ""),
            ),
        )
        reward_ranked = sorted(
            candidates,
            key=lambda item: (
                -float(item.get("reward_shadow_score") or 0.0),
                str(item.get("skill_id") or ""),
            ),
        )
        metadata_top = [
            str(item.get("skill_id") or "")
            for item in metadata_ranked[:TOP_K]
        ]
        reward_top = [
            str(item.get("skill_id") or "")
            for item in reward_ranked[:TOP_K]
        ]
        rank_changed = metadata_top != reward_top
        rewarded_usage_count = sum(
            int(item.get("rewarded_uses") or 0)
            for item in candidates
        )
        gate_reasons = _context_gate_reasons(
            candidate_count=len(candidates),
            rewarded_usage_count=rewarded_usage_count,
            rank_changed=rank_changed,
            candidates=candidates,
        )
        rollout = rollouts.get(context_key)
        contexts.append({
            "skill_context_key": context_key,
            "candidate_count": len(candidates),
            "usage_count": sum(int(item.get("uses") or 0) for item in candidates),
            "rewarded_usage_count": rewarded_usage_count,
            "metadata_top_skill_ids": metadata_top,
            "reward_top_skill_ids": reward_top,
            "rank_changed": rank_changed,
            "readiness": _context_readiness(gate_reasons, rank_changed),
            "reasons": gate_reasons,
            "rollout": _rollout_payload(rollout, context_key=context_key),
        })
    return contexts


def _candidate_payloads_for_context(
    cards: list[SkillPlaybookCard],
    *,
    role: str,
    job_level: str,
    dimension: str,
    probe_intent: str,
    stats_by_skill: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for card in cards:
        metadata_score = _metadata_score_for_context(
            card,
            role=role,
            job_level=job_level,
            dimension=dimension,
            probe_intent=probe_intent,
        )
        if metadata_score is None:
            continue
        stats = stats_by_skill.get(card.id)
        reward_shadow_score = (
            _skill_reward_shadow_score(metadata_score, stats)
            if stats is not None
            else metadata_score
        )
        candidates.append({
            "skill_id": card.id,
            "name": card.name,
            "display_name_zh": card.display_name_zh,
            "skill_context_key": stats.get("skill_context_key") if stats else "",
            "role": role,
            "job_level": job_level,
            "dimension": dimension,
            "probe_intent": probe_intent,
            "uses": int(stats.get("uses") or 0) if stats else 0,
            "injected_uses": int(stats.get("injected_uses") or 0) if stats else 0,
            "rewarded_uses": int(stats.get("rewarded_uses") or 0) if stats else 0,
            "avg_score": stats.get("avg_score") if stats else None,
            "pass_rate": stats.get("pass_rate") if stats else None,
            "avg_immediate_reward": stats.get("avg_immediate_reward") if stats else None,
            "avg_blended_reward": stats.get("avg_blended_reward") if stats else None,
            "overrule_rate": stats.get("overrule_rate") if stats else None,
            "metadata_score": metadata_score,
            "reward_shadow_score": reward_shadow_score,
            "sample_confidence": (
                min(1.0, int(stats.get("rewarded_uses") or 0) / MIN_REWARDED_USES)
                if stats
                else 0.0
            ),
            "readiness": stats.get("readiness") if stats else "shadow_only",
            "reasons": stats.get("reasons") if stats else ["missing_reward_stats"],
        })
    return candidates


def _metadata_score_for_context(
    card: SkillPlaybookCard,
    *,
    role: str,
    job_level: str,
    dimension: str,
    probe_intent: str,
) -> float | None:
    if card.status != "active":
        return None
    dimensions = set(_slug_list(card.dimensions))
    job_levels = set(_slug_list(card.job_levels))
    roles = set(_slug_list(card.role_tags))
    probes = set(_slug_list(card.probe_intents))
    role_slug = _slugify(role)
    level_slug = _slugify(job_level)
    dim_slug = _slugify(dimension)
    probe_slug = _slugify(probe_intent)
    if dimensions and dim_slug not in dimensions:
        return None
    if job_levels and level_slug not in job_levels:
        return None
    if roles and "general" not in roles and role_slug not in roles:
        return None
    score = float(card.priority or 0)
    score += 20.0 if dimensions else 1.0
    score += 8.0 if job_levels else 1.0
    if roles and role_slug in roles:
        score += 20.0
    if probe_slug and probe_slug in probes:
        score += 8.0
    return score


def _skill_reward_shadow_score(
    metadata_score: float,
    stats: dict[str, Any],
) -> float:
    confidence = min(1.0, int(stats.get("rewarded_uses") or 0) / MIN_REWARDED_USES)
    reward_bonus = (
        float(stats.get("avg_blended_reward") or 0.0)
        * REWARD_SHADOW_BONUS_WEIGHT
        * confidence
    )
    usage_bonus = math.log(int(stats.get("uses") or 0) + 1) * 0.1 * confidence
    return metadata_score + reward_bonus + usage_bonus


def _context_gate_reasons(
    *,
    candidate_count: int,
    rewarded_usage_count: int,
    rank_changed: bool,
    candidates: list[dict[str, Any]],
) -> list[str]:
    reasons: list[str] = []
    if candidate_count < MIN_REWARD_CANDIDATE_COUNT:
        reasons.append("candidate_pool_below_min")
    if candidate_count < 2:
        reasons.append("single_skill_no_rank_effect")
    if rewarded_usage_count < MIN_REWARDED_USES:
        reasons.append("reward_samples_below_min")
    if any(
        item.get("overrule_rate") is not None
        and float(item.get("overrule_rate") or 0.0) > MAX_OVERRULE_RATE
        for item in candidates
    ):
        reasons.append("overrule_rate_high")
    reasons.append(
        "reward_shadow_rank_changed"
        if rank_changed
        else "reward_shadow_rank_same"
    )
    return reasons


def _context_readiness(reasons: list[str], rank_changed: bool) -> str:
    blocking = {
        "candidate_pool_below_min",
        "single_skill_no_rank_effect",
        "reward_samples_below_min",
        "overrule_rate_high",
    }
    if any(reason in blocking for reason in reasons):
        return "needs_samples"
    return "ready" if rank_changed else "shadow_only"


def _rollout_payload(
    row: SkillRewardRollout | None,
    *,
    context_key: str,
) -> dict[str, Any]:
    if row is None:
        return {
            "context_key": context_key,
            "mode": DEFAULT_SKILL_REWARD_ROLLOUT_MODE,
            "reason": "",
            "source": "default",
        }
    return {
        "context_key": row.context_key,
        "mode": row.mode,
        "reason": row.reason,
        "source": "override",
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _summary_payload(
    skills: list[dict[str, Any]],
    *,
    contexts: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "skills_with_stats": len({row.get("skill_id") for row in skills}),
        "low_sample_contexts": len(
            {
                row.get("skill_context_key")
                for row in skills
                if "reward_samples_below_min" in set(row.get("reasons") or [])
            }
        ),
        "shadow_changed_contexts": sum(
            1 for row in contexts if bool(row.get("rank_changed"))
        ),
        "high_reward_low_sample_skills": sum(
            1
            for row in skills
            if "high_reward_low_sample" in set(row.get("reasons") or [])
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


def _stats_id(skill_id: str, context_key: str) -> str:
    digest = hashlib.sha1(
        f"{skill_id}|{context_key}".encode("utf-8"),
        usedforsecurity=False,
    ).hexdigest()
    return f"skill-usage-stats:{digest[:32]}"


def _slugify(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[^\w]+", "_", text, flags=re.UNICODE)
    text = re.sub(r"_+", "_", text)
    return text.strip("_")


def _slug_list(values: Any) -> list[str]:
    if values is None:
        return []
    raw = values if isinstance(values, list) else [values]
    out: list[str] = []
    seen: set[str] = set()
    for value in raw:
        slug = _slugify(value)
        if slug and slug not in seen:
            out.append(slug)
            seen.add(slug)
    return out
