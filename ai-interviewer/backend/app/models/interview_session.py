"""One row per interview session (container for traces + outcome).

The ``current_question``, ``turn_idx``, and ``asked_turn`` columns
were added for durable HITL: they let the session manager restore
in-flight interviews after a process restart by reading the
persisted interrupt state from Postgres instead of keeping it only
in the in-memory ``SessionHandle``.
"""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import JSON, Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class InterviewSession(Base):
    __tablename__ = "interview_sessions"

    session_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    trace_id: Mapped[str] = mapped_column(String(64), index=True)
    session_token_hash: Mapped[str | None] = mapped_column(String(128))
    candidate_name: Mapped[str | None] = mapped_column(String(128))
    job_title: Mapped[str | None] = mapped_column(String(128))
    job_level: Mapped[str | None] = mapped_column(String(32), index=True)
    mode: Mapped[str] = mapped_column(String(32), default="mixed")
    enable_video_analysis: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(32), default="running", index=True)
    final_report: Mapped[dict | None] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(Text)
    error_kind: Mapped[str | None] = mapped_column(String(32))
    retryable: Mapped[bool] = mapped_column(Boolean, default=False)

    current_question: Mapped[dict | None] = mapped_column(JSON)
    llm_config_meta: Mapped[dict | None] = mapped_column(JSON)
    setup_snapshot: Mapped[dict | None] = mapped_column(JSON)
    session_token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    recovery_token_hash: Mapped[str | None] = mapped_column(String(128), index=True)
    recovery_token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    recovery_token_revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    turn_idx: Mapped[int] = mapped_column(Integer, default=0)
    asked_turn: Mapped[int] = mapped_column(Integer, default=-1)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )
