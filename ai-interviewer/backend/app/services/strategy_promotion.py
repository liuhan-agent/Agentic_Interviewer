"""Promote aggregated strategy signals into active strategy memories."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from statistics import mean

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.strategy_memory import StrategyMemory, StrategyMemoryStats, StrategySignal

LOW_CONFIDENCE_MIN_SESSIONS = 30
LOW_CONFIDENCE_MIN_REWARD = 0.68
LOW_CONFIDENCE_MIN_SCORE = 7.0
LOW_CONFIDENCE_MAX_OVERRULE_RATE = 0.20

STABLE_MIN_SESSIONS = 100
STABLE_MIN_REWARD = 0.72
STABLE_MAX_OVERRULE_RATE = 0.15


@dataclass(frozen=True)
class StrategyPromotionResult:
    promoted: int = 0
    unchanged: int = 0
    skipped: int = 0
    disabled: int = 0
    stabilized: int = 0


@dataclass(frozen=True)
class _SignalGroup:
    group_key: str
    signals: list[StrategySignal]

    @property
    def distinct_sessions(self) -> int:
        return len({signal.session_id for signal in self.signals})

    @property
    def avg_reward(self) -> float:
        values = [
            signal.immediate_reward
            for signal in self.signals
            if signal.immediate_reward is not None
        ]
        return float(mean(values)) if values else 0.0

    @property
    def avg_score_after(self) -> float:
        values = [
            signal.score_after
            for signal in self.signals
            if signal.score_after is not None
        ]
        return float(mean(values)) if values else 0.0

    @property
    def overrule_rate(self) -> float:
        if not self.signals:
            return 0.0
        overruled = sum(1 for signal in self.signals if signal.verifier_overruled)
        return overruled / len(self.signals)


def promote_strategy_signals(*, session: Session) -> StrategyPromotionResult:
    """Promote supported signal groups into active strategy memories."""

    session.flush()
    groups = _load_signal_groups(session)
    promoted = unchanged = skipped = 0

    for group in groups:
        stage = _promotion_stage(group)
        if stage is None:
            skipped += 1
            continue

        memory_id = _memory_id(group.group_key)
        existing = session.get(StrategyMemory, memory_id)
        if existing is not None:
            unchanged += 1
            _mark_group_promoted(group)
            continue

        session.add(_memory_from_group(group, stage=stage))
        _mark_group_promoted(group)
        promoted += 1

    if promoted:
        session.flush()
    return StrategyPromotionResult(
        promoted=promoted,
        unchanged=unchanged,
        skipped=skipped,
    )


def apply_strategy_quality_transitions(*, session: Session) -> StrategyPromotionResult:
    """Disable weak active strategies and mark strong ones as stable."""

    session.flush()
    disabled = stabilized = unchanged = skipped = 0
    stats_rows = list(
        session.scalars(
            select(StrategyMemoryStats)
            .where(StrategyMemoryStats.context_key == "__global__")
            .order_by(StrategyMemoryStats.strategy_id.asc())
        )
    )
    for stats in stats_rows:
        memory = session.get(StrategyMemory, stats.strategy_id)
        if memory is None or memory.status != "active":
            skipped += 1
            continue
        uses = int(stats.uses or 0)
        avg_reward = float(stats.avg_blended_reward or 0.0)
        overrule_rate = float(stats.overrule_rate or 0.0)

        if uses >= 30 and (avg_reward < 0.55 or overrule_rate > 0.35):
            memory.status = "disabled"
            memory.confidence = min(float(memory.confidence or 0.0), 0.2)
            memory.quality_reason = _quality_reason(
                "disabled",
                uses=uses,
                avg_reward=avg_reward,
                overrule_rate=overrule_rate,
            )
            disabled += 1
            continue

        if (
            uses >= STABLE_MIN_SESSIONS
            and avg_reward >= STABLE_MIN_REWARD
            and overrule_rate <= STABLE_MAX_OVERRULE_RATE
            and memory.promotion_stage != "stable"
        ):
            memory.promotion_stage = "stable"
            memory.confidence = max(float(memory.confidence or 0.0), 0.75)
            memory.quality_reason = _quality_reason(
                "stable",
                uses=uses,
                avg_reward=avg_reward,
                overrule_rate=overrule_rate,
            )
            stabilized += 1
            continue

        unchanged += 1

    if disabled or stabilized:
        session.flush()
    return StrategyPromotionResult(
        unchanged=unchanged,
        skipped=skipped,
        disabled=disabled,
        stabilized=stabilized,
    )


def _load_signal_groups(session: Session) -> list[_SignalGroup]:
    signals = list(
        session.scalars(
            select(StrategySignal)
            .where(StrategySignal.status.in_(["observed", "grouped", "promoted"]))
            .order_by(StrategySignal.group_key.asc(), StrategySignal.created_at.asc())
        )
    )
    grouped: dict[str, list[StrategySignal]] = {}
    for signal in signals:
        grouped.setdefault(signal.group_key, []).append(signal)
    return [
        _SignalGroup(group_key=group_key, signals=items)
        for group_key, items in sorted(grouped.items())
    ]


def _promotion_stage(group: _SignalGroup) -> str | None:
    if group.distinct_sessions >= STABLE_MIN_SESSIONS:
        if (
            group.avg_reward >= STABLE_MIN_REWARD
            and group.overrule_rate <= STABLE_MAX_OVERRULE_RATE
        ):
            return "stable"

    if group.distinct_sessions < LOW_CONFIDENCE_MIN_SESSIONS:
        return None
    if group.avg_reward < LOW_CONFIDENCE_MIN_REWARD:
        return None
    if group.avg_score_after < LOW_CONFIDENCE_MIN_SCORE:
        return None
    if group.overrule_rate > LOW_CONFIDENCE_MAX_OVERRULE_RATE:
        return None
    return "low_confidence"


def _memory_from_group(group: _SignalGroup, *, stage: str) -> StrategyMemory:
    first = group.signals[0]
    support = group.distinct_sessions
    confidence = _confidence_for_stage(stage, group)
    return StrategyMemory(
        id=_memory_id(group.group_key),
        slug=_slug(group.group_key),
        name=_memory_name(first),
        description=(
            f"Promoted from {support} sessions; avg reward "
            f"{group.avg_reward:.2f}, overrule rate {group.overrule_rate:.0%}."
        ),
        source="promoted_signal",
        memory_key=f"promoted:{group.group_key}",
        dimensions=[first.dimension],
        job_levels=[first.job_level] if first.job_level else [],
        failure_categories=_merged_failure_categories(group.signals),
        recommended_action=first.action_id,
        recommended_plan_template=first.plan_template,
        recommended_probe_intent=first.probe_intent,
        body_markdown=_memory_body(group, stage=stage),
        status="active",
        confidence=confidence,
        support_count=support,
        promotion_stage=stage,
        version=1,
        content_hash=_content_hash(group),
    )


def _memory_name(signal: StrategySignal) -> str:
    action = signal.action_id or "strategy"
    dimension = signal.dimension or "general"
    return f"Auto: {action} for {dimension}"


def _memory_body(group: _SignalGroup, *, stage: str) -> str:
    first = group.signals[0]
    return "\n".join(
        [
            f"Promoted from {group.distinct_sessions} sessions.",
            "",
            "How to apply:",
            f"- In `{first.dimension}` for `{first.job_level}` candidates, consider `{first.action_id}`.",
            f"- Average immediate reward: {group.avg_reward:.2f}.",
            f"- Average post-signal score: {group.avg_score_after:.2f}.",
            f"- Verifier overrule rate: {group.overrule_rate:.0%}.",
            f"- Promotion stage: `{stage}`.",
        ]
    )


def _confidence_for_stage(stage: str, group: _SignalGroup) -> float:
    if stage == "stable":
        return 0.75
    bonus = min(0.20, max(0.0, group.avg_reward - LOW_CONFIDENCE_MIN_REWARD))
    return round(0.35 + bonus, 3)


def _mark_group_promoted(group: _SignalGroup) -> None:
    for signal in group.signals:
        signal.status = "promoted"


def _merged_failure_categories(signals: list[StrategySignal]) -> list[str]:
    out: list[str] = []
    for signal in signals:
        for item in signal.failure_categories or []:
            text = str(item).strip()
            if text and text not in out:
                out.append(text)
    return out


def _memory_id(group_key: str) -> str:
    digest = hashlib.sha1(group_key.encode("utf-8"), usedforsecurity=False).hexdigest()
    return f"promoted:{digest[:24]}"


def _slug(group_key: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", group_key.lower()).strip("_")
    return f"promoted_{slug[:80]}"


def _content_hash(group: _SignalGroup) -> str:
    payload = (
        f"{group.group_key}|{group.distinct_sessions}|"
        f"{group.avg_reward:.4f}|{group.overrule_rate:.4f}"
    )
    digest = hashlib.sha1(payload.encode("utf-8"), usedforsecurity=False).hexdigest()
    return f"sha1:{digest}"


def _quality_reason(
    status: str,
    *,
    uses: int,
    avg_reward: float,
    overrule_rate: float,
) -> str:
    return (
        f"{status}: uses={uses}, "
        f"avg_blended_reward={avg_reward:.2f}, "
        f"overrule_rate={overrule_rate:.2f}"
    )
