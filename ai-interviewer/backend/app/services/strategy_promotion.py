"""Promote aggregated strategy signals into active strategy memories."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from statistics import mean

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ml.rl.action_space import canonical_action_id
from app.models.strategy_memory import StrategyMemory, StrategyMemoryStats, StrategySignal

LOW_CONFIDENCE_MIN_SESSIONS = 30
LOW_CONFIDENCE_MIN_REWARD = 0.68
LOW_CONFIDENCE_MIN_SCORE = 7.0
LOW_CONFIDENCE_MIN_SCORE_DELTA = 3.0
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
    def avg_score_delta(self) -> float:
        values = [
            signal.score_delta
            for signal in self.signals
            if signal.score_delta is not None
        ]
        return float(mean(values)) if values else 0.0

    @property
    def signal_type(self) -> str:
        if not self.signals:
            return ""
        return str(self.signals[0].signal_type or "")

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
    if group.group_key.startswith("qa:"):
        return _stage_for_qa_pattern(group)
    if group.group_key.startswith("bandit:"):
        return _stage_for_bandit_insight(group)
    return _stage_for_legacy_signal(group)


def _stage_for_qa_pattern(group: _SignalGroup) -> str | None:
    if group.signal_type not in {"score_recovery", "hint_effective"}:
        return None

    if group.distinct_sessions >= STABLE_MIN_SESSIONS:
        if (
            _qa_evidence_passes(group)
            and group.overrule_rate <= STABLE_MAX_OVERRULE_RATE
        ):
            return "stable"

    if group.distinct_sessions < LOW_CONFIDENCE_MIN_SESSIONS:
        return None
    if group.overrule_rate > LOW_CONFIDENCE_MAX_OVERRULE_RATE:
        return None
    if not _qa_evidence_passes(group):
        return None
    return "low_confidence"


def _qa_evidence_passes(group: _SignalGroup) -> bool:
    if group.avg_score_after < LOW_CONFIDENCE_MIN_SCORE:
        return False
    if group.signal_type == "score_recovery":
        return group.avg_score_delta >= LOW_CONFIDENCE_MIN_SCORE_DELTA
    if group.signal_type == "hint_effective":
        return True
    return False


def _stage_for_bandit_insight(group: _SignalGroup) -> str | None:
    if group.signal_type != "high_reward_arm":
        return None

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
    if group.overrule_rate > LOW_CONFIDENCE_MAX_OVERRULE_RATE:
        return None
    return "low_confidence"


def _stage_for_legacy_signal(group: _SignalGroup) -> str | None:
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
    recommended_action = canonical_action_id(first.action_id)
    support = group.distinct_sessions
    confidence = _confidence_for_stage(stage, group)
    return StrategyMemory(
        id=_memory_id(group.group_key),
        slug=_slug(group.group_key),
        name=_memory_name(first),
        description=_memory_description(group),
        display_name_zh=_memory_display_name_zh(first, signal_type=group.signal_type),
        display_description_zh=_memory_display_description_zh(group, stage=stage),
        source="promoted_signal",
        memory_key=f"promoted:{group.group_key}",
        dimensions=[first.dimension],
        job_levels=[first.job_level] if first.job_level else [],
        failure_categories=_merged_failure_categories(group.signals),
        recommended_action=recommended_action,
        recommended_plan_template=recommended_action or first.plan_template,
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
    action = canonical_action_id(signal.action_id) or signal.action_id or "strategy"
    dimension = signal.dimension or "general"
    return f"Auto: {action} for {dimension}"


def _memory_description(group: _SignalGroup) -> str:
    support = group.distinct_sessions
    if group.group_key.startswith("qa:"):
        if group.signal_type == "hint_effective":
            return (
                f"Promoted from {support} sessions; avg hint score "
                f"{group.avg_score_after:.2f}, overrule rate "
                f"{group.overrule_rate:.0%}."
            )
        return (
            f"Promoted from {support} sessions; avg post-signal score "
            f"{group.avg_score_after:.2f}, avg score delta "
            f"{group.avg_score_delta:.2f}, overrule rate "
            f"{group.overrule_rate:.0%}."
        )
    return (
        f"Promoted from {support} sessions; avg reward "
        f"{group.avg_reward:.2f}, overrule rate {group.overrule_rate:.0%}."
    )


def _memory_display_name_zh(
    signal: StrategySignal,
    *,
    signal_type: str = "",
) -> str:
    action = canonical_action_id(signal.action_id) or signal.action_id or "strategy"
    dimension = _display_dimension_zh(signal.dimension)
    action_label = _display_action_zh(action, raw_action=signal.action_id)
    if signal_type == "hint_effective":
        return f"{dimension}：提示有效"
    if signal.dimension == "communication" and action in {
        "plan_deep_probe",
        "plan_hint",
    }:
        return f"沟通恢复：{action_label}"
    return f"{dimension}：{action_label}"


def _memory_display_description_zh(group: _SignalGroup, *, stage: str) -> str:
    stage_label = _display_stage_zh(stage)
    support = group.distinct_sessions
    if group.signal_type == "hint_effective":
        evidence = f"平均 hint 后得分 {group.avg_score_after:.2f}"
    elif group.group_key.startswith("qa:"):
        evidence = f"平均后验分 {group.avg_score_after:.2f}"
    else:
        evidence = f"平均 reward {group.avg_reward:.2f}"
    return (
        f"从 {support} 场面试中观察到该策略有效"
        f"（{stage_label}，{evidence}）。"
    )


def _display_dimension_zh(value: str | None) -> str:
    labels = {
        "communication": "沟通",
        "system_design": "系统设计",
        "technical_depth": "技术深度",
        "problem_solving": "问题解决",
        "project_experience": "项目经验",
        "coding_quality": "代码质量",
        "product_sense": "产品理解",
    }
    key = str(value or "").strip()
    return labels.get(key, key.replace("_", " ") or "通用策略")


def _display_action_zh(action: str, *, raw_action: str | None = None) -> str:
    raw = str(raw_action or "")
    if raw == "give_hint":
        return "提示有效"
    labels = {
        "plan_deep_probe": "深挖追问",
        "plan_hint": "提示引导",
        "plan_switch": "切换维度",
        "plan_adaptive": "自适应追问",
    }
    return labels.get(action, action.replace("_", " "))


def _display_stage_zh(stage: str) -> str:
    labels = {
        "low_confidence": "低置信",
        "stable": "稳定",
        "seed": "种子策略",
    }
    return labels.get(stage, stage.replace("_", " "))


def _memory_body(group: _SignalGroup, *, stage: str) -> str:
    if group.group_key.startswith("qa:"):
        return _qa_memory_body(group, stage=stage)
    if group.group_key.startswith("bandit:"):
        return _bandit_memory_body(group, stage=stage)
    return _legacy_memory_body(group, stage=stage)


def _qa_memory_body(group: _SignalGroup, *, stage: str) -> str:
    first = group.signals[0]
    action = canonical_action_id(first.action_id) or first.action_id or "unknown"
    failure_categories = _merged_failure_categories(group.signals)
    score_evidence = (
        f"- 平均 hint 后得分：{group.avg_score_after:.2f}"
        if group.signal_type == "hint_effective"
        else f"- 平均分数提升：{group.avg_score_delta:.2f}"
    )
    return "\n".join(
        [
            "## 适用场景",
            f"- 维度：{_code_value(first.dimension)}",
            f"- 级别：{_code_value(first.job_level)}",
            f"- 失败类型：{_code_list(failure_categories)}",
            f"- 信号类型：{_code_value(group.signal_type)}",
            "",
            "## 推荐动作",
            f"- action：{_code_value(action)}",
            f"- plan_template：{_code_value(action or first.plan_template)}",
            f"- probe_intent：{_code_value(first.probe_intent)}",
            "",
            "## 使用方式",
            "- 同维度、同级别、相似失败类型下，优先考虑该推荐动作。",
            "- 如果当前上下文不相近，保持原有出题策略，不强行套用。",
            "",
            "## 证据",
            f"- 支持 session：{group.distinct_sessions}",
            f"- 平均后验分：{group.avg_score_after:.2f}",
            score_evidence,
            f"- Verifier 否决率：{group.overrule_rate:.0%}",
            f"- 晋升阶段：{_code_value(stage)}",
            "",
            "## 使用边界",
            "- 只在相近上下文使用，不把单条策略泛化到无关维度或级别。",
            "- 后续 reward 或 Verifier 否决率变差时，应降权、禁用或重新观察。",
        ]
    )


def _bandit_memory_body(group: _SignalGroup, *, stage: str) -> str:
    first = group.signals[0]
    action = canonical_action_id(first.action_id) or first.action_id or "unknown"
    return "\n".join(
        [
            "## 适用场景",
            f"- 维度：{_code_value(first.dimension)}",
            f"- 级别：{_code_value(first.job_level)}",
            f"- group_key：{_code_value(group.group_key)}",
            f"- 信号类型：{_code_value(group.signal_type)}",
            "",
            "## 推荐动作",
            f"- action：{_code_value(action)}",
            f"- plan_template：{_code_value(action or first.plan_template)}",
            f"- probe_intent：{_code_value(first.probe_intent)}",
            "",
            "## 使用方式",
            "- 同维度、同级别、相似上下文下，优先考虑该推荐动作。",
            "- 如果当前上下文不相近，保持原有出题策略，不强行套用。",
            "",
            "## 证据",
            f"- 支持 session：{group.distinct_sessions}",
            f"- 平均 reward：{group.avg_reward:.2f}",
            f"- Verifier 否决率：{group.overrule_rate:.0%}",
            f"- 晋升阶段：{_code_value(stage)}",
            "",
            "## 使用边界",
            "- 只在相近上下文使用，不把单条策略泛化到无关维度或级别。",
            "- 后续 reward 或 Verifier 否决率变差时，应降权、禁用或重新观察。",
        ]
    )


def _legacy_memory_body(group: _SignalGroup, *, stage: str) -> str:
    first = group.signals[0]
    action = canonical_action_id(first.action_id) or first.action_id or "unknown"
    failure_categories = _merged_failure_categories(group.signals)
    return "\n".join(
        [
            "## 适用场景",
            f"- 维度：{_code_value(first.dimension)}",
            f"- 级别：{_code_value(first.job_level)}",
            f"- 失败类型：{_code_list(failure_categories)}",
            f"- 信号类型：{_code_value(group.signal_type)}",
            "",
            "## 推荐动作",
            f"- action：{_code_value(action)}",
            f"- plan_template：{_code_value(action or first.plan_template)}",
            f"- probe_intent：{_code_value(first.probe_intent)}",
            "",
            "## 使用方式",
            "- 同维度、同级别、相似失败类型下，优先考虑该推荐动作。",
            "- 如果当前上下文不相近，保持原有出题策略，不强行套用。",
            "",
            "## 证据",
            f"- 支持 session：{group.distinct_sessions}",
            f"- 平均 reward：{group.avg_reward:.2f}",
            f"- 平均后验分：{group.avg_score_after:.2f}",
            f"- Verifier 否决率：{group.overrule_rate:.0%}",
            f"- 晋升阶段：{_code_value(stage)}",
            "",
            "## 使用边界",
            "- 只在相近上下文使用，不把单条策略泛化到无关维度或级别。",
            "- 后续 reward 或 Verifier 否决率变差时，应降权、禁用或重新观察。",
        ]
    )


def _code_value(value: object) -> str:
    text = str(value or "").strip()
    return f"`{text}`" if text else "`无`"


def _code_list(values: list[str]) -> str:
    cleaned = [str(value or "").strip() for value in values if str(value or "").strip()]
    if not cleaned:
        return "`无`"
    return "、".join(f"`{value}`" for value in cleaned)


def _confidence_for_stage(stage: str, group: _SignalGroup) -> float:
    if stage == "stable":
        return 0.75
    if group.group_key.startswith("qa:"):
        return 0.35
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
    if group.group_key.startswith("qa:"):
        payload = (
            f"{group.group_key}|{group.distinct_sessions}|"
            f"{group.avg_score_after:.4f}|{group.avg_score_delta:.4f}|"
            f"{group.overrule_rate:.4f}"
        )
    else:
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
