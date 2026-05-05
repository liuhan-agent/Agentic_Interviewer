"""Human review annotations on generation trace rows."""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class TraceAnnotation(Base):
    """One annotation per (trace_id, turn_idx, annotation_type) triple.

    Stored separately from ``generation_traces`` so the main interview
    pipeline is never blocked by annotation reads/writes.  The
    ``trainset_builder`` can join on ``trace_id + turn_idx`` to filter
    flagged samples before export.
    """

    __tablename__ = "trace_annotations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trace_id: Mapped[str] = mapped_column(String(64), index=True)
    session_id: Mapped[str] = mapped_column(String(64), index=True)
    turn_idx: Mapped[int] = mapped_column(Integer)
    generation_trace_id: Mapped[int | None] = mapped_column(Integer, index=True)
    node: Mapped[str | None] = mapped_column(String(64), index=True)

    annotation_type: Mapped[str] = mapped_column(String(32), index=True)
    verdict: Mapped[str] = mapped_column(String(32), index=True)
    notes: Mapped[str | None] = mapped_column(Text)
    reviewer: Mapped[str | None] = mapped_column(String(64))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        index=True,
    )
