"""Short-lived setup resume parse artifacts for node-scoped vectorization."""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class ResumeParseArtifact(Base):
    """Redacted resume text bridge between setup parsing and workflow nodes."""

    __tablename__ = "resume_parse_artifacts"

    artifact_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    redacted_text: Mapped[str] = mapped_column(Text, default="")
    parsed: Mapped[dict] = mapped_column(JSON, default=dict)
    filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    text_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        index=True,
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        index=True,
    )
    consumed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
