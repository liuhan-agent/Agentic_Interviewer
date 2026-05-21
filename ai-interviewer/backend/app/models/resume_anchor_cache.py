"""Reusable resume anchor vector cache for copy-on-bind session RAG."""
from __future__ import annotations

from datetime import UTC, datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, BigInteger, DateTime, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.settings import get_settings

from .base import Base

_EMBEDDING_DIM = int(get_settings().resume_rag_embedding_dimension or 1536)


class ResumeAnchorCacheChunk(Base):
    """One redacted, embedded resume anchor reusable across sessions."""

    __tablename__ = "resume_anchor_cache_chunks"
    __table_args__ = (
        Index(
            "ix_resume_anchor_cache_lookup",
            "cache_key",
            "embedding_model_version",
            "chunk_index",
            unique=True,
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    cache_key: Mapped[str] = mapped_column(String(96), index=True)
    embedding_model_version: Mapped[str] = mapped_column(String(96), index=True)
    chunk_index: Mapped[int] = mapped_column(Integer, default=0)
    tier: Mapped[str] = mapped_column(String(32), index=True)
    section_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    heading: Mapped[str | None] = mapped_column(String(256), nullable=True)
    project_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    text: Mapped[str] = mapped_column(Text)
    tech_keywords: Mapped[list] = mapped_column(JSON, default=list)
    dimensions_hint: Mapped[list] = mapped_column(JSON, default=list)
    chunker_mode: Mapped[str] = mapped_column(String(8), index=True)
    embedding: Mapped[list[float]] = mapped_column(Vector(_EMBEDDING_DIM))
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        index=True,
    )
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )
    hit_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        index=True,
    )
