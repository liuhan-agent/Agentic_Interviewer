"""Strategy memory models.

These tables back the production strategy-memory runtime. Markdown seed
files can still be imported into ``strategy_memories``, but the running
application should attribute usage and rewards through these tables.
"""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class StrategyMemory(Base):
    """A strategy that can be retrieved and injected into Generator prompts."""

    __tablename__ = "strategy_memories"

    id: Mapped[str] = mapped_column(String(96), primary_key=True)
    slug: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(String(512), default="")
    source: Mapped[str] = mapped_column(String(32), default="seed", index=True)
    memory_key: Mapped[str | None] = mapped_column(String(256), unique=True, index=True)

    dimensions: Mapped[list] = mapped_column(JSON, default=list)
    job_levels: Mapped[list] = mapped_column(JSON, default=list)
    failure_categories: Mapped[list] = mapped_column(JSON, default=list)

    recommended_action: Mapped[str | None] = mapped_column(String(64))
    recommended_plan_template: Mapped[str | None] = mapped_column(String(64))
    recommended_probe_intent: Mapped[str | None] = mapped_column(String(64))

    body_markdown: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    priority: Mapped[int] = mapped_column(Integer, default=0)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    support_count: Mapped[int] = mapped_column(Integer, default=0)
    promotion_stage: Mapped[str] = mapped_column(String(32), default="seed", index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    content_hash: Mapped[str | None] = mapped_column(String(128), index=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )


class StrategySignal(Base):
    """A raw observation that may later be promoted into a strategy."""

    __tablename__ = "strategy_signals"

    id: Mapped[str] = mapped_column(String(96), primary_key=True)
    signal_key: Mapped[str] = mapped_column(String(256), unique=True, index=True)
    group_key: Mapped[str] = mapped_column(String(256), index=True)

    session_id: Mapped[str] = mapped_column(String(64), index=True)
    turn_idx: Mapped[int] = mapped_column(Integer)
    dimension: Mapped[str] = mapped_column(String(64), index=True)
    job_level: Mapped[str | None] = mapped_column(String(32), index=True)
    action_id: Mapped[str | None] = mapped_column(String(64), index=True)
    plan_template: Mapped[str | None] = mapped_column(String(64))
    probe_intent: Mapped[str | None] = mapped_column(String(64))
    failure_categories: Mapped[list] = mapped_column(JSON, default=list)

    score_before: Mapped[float | None] = mapped_column(Float)
    score_after: Mapped[float | None] = mapped_column(Float)
    score_delta: Mapped[float | None] = mapped_column(Float)
    immediate_reward: Mapped[float | None] = mapped_column(Float)
    verifier_overruled: Mapped[bool] = mapped_column(Boolean, default=False)

    signal_type: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32), default="observed", index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        index=True,
    )


class StrategyMemoryUsage(Base):
    """Per-turn strategy usage with reward attribution fields."""

    __tablename__ = "strategy_memory_usages"

    id: Mapped[str] = mapped_column(String(96), primary_key=True)
    strategy_id: Mapped[str] = mapped_column(String(96), index=True)
    session_id: Mapped[str] = mapped_column(String(64), index=True)
    turn_idx: Mapped[int] = mapped_column(Integer, index=True)
    trace_id: Mapped[str | None] = mapped_column(String(64), index=True)

    context_key: Mapped[str | None] = mapped_column(String(128), index=True)
    action_id: Mapped[str | None] = mapped_column(String(64), index=True)
    plan_template: Mapped[str | None] = mapped_column(String(64))
    question_id: Mapped[str | None] = mapped_column(String(128), index=True)
    question_text_hash: Mapped[str | None] = mapped_column(String(128), index=True)

    score: Mapped[float | None] = mapped_column(Float)
    passed: Mapped[bool | None] = mapped_column(Boolean)
    immediate_reward: Mapped[float | None] = mapped_column(Float)
    delayed_reward: Mapped[float | None] = mapped_column(Float)
    verifier_overruled: Mapped[bool] = mapped_column(Boolean, default=False)
    helpful_score: Mapped[float | None] = mapped_column(Float)

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
