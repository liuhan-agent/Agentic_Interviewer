"""Real-world outcome collected weeks/months after the interview.

Two sources feed this table:

- ``ats_sync`` (B-end): pulled from an ATS/HRIS via a scheduled job.
- ``user_feedback`` (C-end): submitted by the candidate on the report
  page via ``POST /api/v1/interview/sessions/{id}/feedback``.

Both sources flow into the same ``outcome_reward_bridge.backfill_once``
pipeline so the Thompson Sampling bandit sees a unified delayed reward
signal regardless of origin.
"""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, Float, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class OutcomeRecord(Base):
    __tablename__ = "outcome_records"

    session_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    outcome: Mapped[str] = mapped_column(String(32))
    """hired | rejected | withdrew | ghosted"""
    performance_score: Mapped[float | None] = mapped_column(Float)
    """Optional post-hire performance rating in [0, 1]."""

    source: Mapped[str] = mapped_column(String(32), default="ats_sync")
    """Origin of this record: ``ats_sync`` or ``user_feedback``."""

    helpful_score: Mapped[float | None] = mapped_column(Float)
    """C-end user's subjective helpfulness rating in [1, 5].

    Only populated when ``source == "user_feedback"``. Normalised to
    [0, 1] by the reward bridge before blending with the category
    weight.
    """

    notes: Mapped[str | None] = mapped_column(String(1024))
    collected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
