"""Durable strategy-learning facts and Thompson posterior aggregates."""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.schema import UniqueConstraint

from .base import Base


class InterviewTurn(Base):
    """One durable, sanitized interview turn used by experience extraction."""

    __tablename__ = "interview_turns"
    __table_args__ = (
        UniqueConstraint("session_id", "turn_idx", name="uq_interview_turn_session_turn"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(64), index=True)
    turn_idx: Mapped[int] = mapped_column(Integer, index=True)
    trace_id: Mapped[str | None] = mapped_column(String(64), index=True)

    dimension: Mapped[str] = mapped_column(String(64), default="unknown", index=True)
    job_level: Mapped[str | None] = mapped_column(String(32), index=True)
    question: Mapped[str] = mapped_column(Text, default="")
    answer: Mapped[str] = mapped_column(Text, default="")
    resume_anchor_key: Mapped[str | None] = mapped_column(String(160), index=True)
    resume_anchor_label: Mapped[str | None] = mapped_column(String(160))
    resume_project_id: Mapped[str | None] = mapped_column(String(64), index=True)
    selected_action: Mapped[str | None] = mapped_column(String(64), index=True)
    policy_context_keys: Mapped[list] = mapped_column(JSON, default=list)
    selection_artifacts: Mapped[dict] = mapped_column(JSON, default=dict)

    evaluation: Mapped[dict] = mapped_column(JSON, default=dict)
    failure_categories: Mapped[list] = mapped_column(JSON, default=list)
    score: Mapped[float | None] = mapped_column(Float)
    passed: Mapped[bool | None] = mapped_column(Boolean)

    verification: Mapped[dict] = mapped_column(JSON, default=dict)
    verifier_triggered: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    verifier_forced_refine: Mapped[bool] = mapped_column(Boolean, default=False)
    verifier_abstained: Mapped[bool] = mapped_column(Boolean, default=False)
    verifier_verdict: Mapped[str | None] = mapped_column(String(32), index=True)

    immediate_reward: Mapped[float | None] = mapped_column(Float)
    delayed_reward: Mapped[float | None] = mapped_column(Float)

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


class BanditPosterior(Base):
    """Aggregated Thompson posterior for a ``context_key`` / ``action_id`` arm."""

    __tablename__ = "bandit_posteriors"
    __table_args__ = (
        UniqueConstraint(
            "context_key",
            "action_id",
            name="uq_bandit_posterior_context_action",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    context_key: Mapped[str] = mapped_column(String(128), index=True)
    action_id: Mapped[str] = mapped_column(String(64), index=True)

    alpha: Mapped[float] = mapped_column(Float, default=1.0)
    beta: Mapped[float] = mapped_column(Float, default=1.0)
    observation_count: Mapped[int] = mapped_column(Integer, default=0, index=True)
    immediate_update_count: Mapped[int] = mapped_column(Integer, default=0)
    delayed_update_count: Mapped[int] = mapped_column(Integer, default=0)

    last_reward: Mapped[float | None] = mapped_column(Float)
    last_reward_kind: Mapped[str | None] = mapped_column(String(16), index=True)
    last_session_id: Mapped[str | None] = mapped_column(String(64), index=True)
    last_turn_idx: Mapped[int | None] = mapped_column(Integer)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        index=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        index=True,
    )
