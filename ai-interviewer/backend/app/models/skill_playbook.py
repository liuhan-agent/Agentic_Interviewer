"""Structured interviewer playbook persistence models."""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class SkillPlaybookCard(Base):
    """Hand-authored interviewer playbook card prepared for DB-backed runtime."""

    __tablename__ = "skill_playbook_cards"

    id: Mapped[str] = mapped_column(String(160), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(String(512), default="")
    display_name_zh: Mapped[str] = mapped_column(String(200), default="")
    display_description_zh: Mapped[str] = mapped_column(String(512), default="")
    body_markdown: Mapped[str] = mapped_column(Text, default="")

    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    priority: Mapped[int] = mapped_column(Integer, default=0, index=True)
    direction_tags: Mapped[list] = mapped_column(JSON, default=list)
    role_tags: Mapped[list] = mapped_column(JSON, default=list)
    dimensions: Mapped[list] = mapped_column(JSON, default=list)
    job_levels: Mapped[list] = mapped_column(JSON, default=list)
    probe_intents: Mapped[list] = mapped_column(JSON, default=list)
    failure_categories: Mapped[list] = mapped_column(JSON, default=list)
    generator_moves: Mapped[list] = mapped_column(JSON, default=list)
    watch_for: Mapped[list] = mapped_column(JSON, default=list)
    avoid: Mapped[list] = mapped_column(JSON, default=list)
    evaluator_rubric_hints: Mapped[list] = mapped_column(JSON, default=list)
    positive_signals: Mapped[list] = mapped_column(JSON, default=list)
    negative_signals: Mapped[list] = mapped_column(JSON, default=list)
    score_bias_rules: Mapped[list] = mapped_column(JSON, default=list)
    evaluator_visibility: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    source: Mapped[str] = mapped_column(
        String(64),
        default="manual_markdown",
        index=True,
    )
    version: Mapped[int] = mapped_column(Integer, default=1)
    content_hash: Mapped[str | None] = mapped_column(String(128), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        index=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )


class SkillUsage(Base):
    """Per-turn skill playbook usage with reward attribution fields."""

    __tablename__ = "skill_usages"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    skill_id: Mapped[str] = mapped_column(String(160), index=True)
    session_id: Mapped[str] = mapped_column(String(64), index=True)
    turn_idx: Mapped[int] = mapped_column(Integer, index=True)
    trace_id: Mapped[str | None] = mapped_column(String(64), index=True)

    skill_context_key: Mapped[str] = mapped_column(String(160), index=True)
    role: Mapped[str] = mapped_column(String(64), index=True)
    job_level: Mapped[str] = mapped_column(String(32), index=True)
    dimension: Mapped[str] = mapped_column(String(64), index=True)
    probe_intent: Mapped[str | None] = mapped_column(String(64), index=True)

    rank: Mapped[int] = mapped_column(Integer, index=True)
    match_score: Mapped[float] = mapped_column(Float, default=0.0)
    match_reasons: Mapped[list] = mapped_column(JSON, default=list)
    injected: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    evaluator_visibility: Mapped[bool] = mapped_column(Boolean, default=False)

    score: Mapped[float | None] = mapped_column(Float)
    passed: Mapped[bool | None] = mapped_column(Boolean)
    immediate_reward: Mapped[float | None] = mapped_column(Float)
    verifier_overruled: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        index=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )


class SkillUsageStats(Base):
    """Aggregated reward-shadow health for skill playbook cards."""

    __tablename__ = "skill_usage_stats"

    id: Mapped[str] = mapped_column(String(160), primary_key=True)
    skill_id: Mapped[str] = mapped_column(String(160), index=True)
    skill_context_key: Mapped[str] = mapped_column(String(160), index=True)
    role: Mapped[str] = mapped_column(String(64), index=True)
    job_level: Mapped[str] = mapped_column(String(32), index=True)
    dimension: Mapped[str] = mapped_column(String(64), index=True)
    probe_intent: Mapped[str | None] = mapped_column(String(64), index=True)

    uses: Mapped[int] = mapped_column(Integer, default=0)
    injected_uses: Mapped[int] = mapped_column(Integer, default=0)
    rewarded_uses: Mapped[int] = mapped_column(Integer, default=0)
    avg_score: Mapped[float | None] = mapped_column(Float)
    pass_rate: Mapped[float | None] = mapped_column(Float)
    avg_immediate_reward: Mapped[float | None] = mapped_column(Float)
    avg_blended_reward: Mapped[float | None] = mapped_column(Float)
    overrule_rate: Mapped[float | None] = mapped_column(Float)

    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )


class SkillRewardRollout(Base):
    """Per-context rollout override for live skill reward ranking."""

    __tablename__ = "skill_reward_rollouts"

    context_key: Mapped[str] = mapped_column(String(160), primary_key=True)
    mode: Mapped[str] = mapped_column(String(32), default="reward_shadow", index=True)
    reason: Mapped[str] = mapped_column(String(512), default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )
