"""Structured interviewer playbook persistence models."""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import JSON, Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class SkillPlaybookCard(Base):
    """Hand-authored interviewer playbook card prepared for DB-backed runtime."""

    __tablename__ = "skill_playbook_cards"

    id: Mapped[str] = mapped_column(String(160), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(String(512), default="")
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
