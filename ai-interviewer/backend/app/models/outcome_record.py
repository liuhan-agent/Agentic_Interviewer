"""Real-world outcome collected weeks/months after the interview.

In production this gets pulled from an ATS/HRIS via a scheduled job.
For MVP the demo simulates outcomes manually.
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

    notes: Mapped[str | None] = mapped_column(String(1024))
    collected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
