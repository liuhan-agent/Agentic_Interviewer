"""Session-scoped semantic anchor chunks for candidate-specific RAG."""
from __future__ import annotations

from datetime import UTC, datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import BigInteger, DateTime, Index, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.settings import get_settings

from .base import Base

_EMBEDDING_DIM = int(get_settings().resume_rag_embedding_dimension or 1536)


class SessionAnchorChunk(Base):
    """One redacted candidate-anchor chunk embedded for one interview session."""

    __tablename__ = "session_anchor_chunks"
    __table_args__ = (
        Index(
            "ix_session_anchor_chunks_lookup",
            "session_id",
            "source_type",
            "source_revision_id",
            "embedding_model_version",
            "tier",
        ),
    )

    P0_SOURCE_TYPES = ("resume", "self_intro")
    FUTURE_SOURCE_TYPES = ("adhoc_claim",)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(96), index=True)
    source_type: Mapped[str] = mapped_column(String(32), index=True)
    source_revision_id: Mapped[str] = mapped_column(String(96), index=True)
    source_artifact_id: Mapped[str | None] = mapped_column(
        String(96),
        index=True,
        nullable=True,
    )
    source_turn_id: Mapped[int | None] = mapped_column(
        Integer,
        index=True,
        nullable=True,
    )
    chunk_index: Mapped[int] = mapped_column(Integer, default=0)
    tier: Mapped[str] = mapped_column(String(32), index=True)
    section_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    heading: Mapped[str | None] = mapped_column(String(256), nullable=True)
    project_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    text: Mapped[str] = mapped_column(Text)
    tech_keywords: Mapped[list] = mapped_column(JSON, default=list)
    dimensions_hint: Mapped[list] = mapped_column(JSON, default=list)
    chunker_mode: Mapped[str] = mapped_column(String(8), index=True)
    embedding_model_version: Mapped[str] = mapped_column(String(96), index=True)
    embedding: Mapped[list[float]] = mapped_column(Vector(_EMBEDDING_DIM))
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        index=True,
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        index=True,
    )
