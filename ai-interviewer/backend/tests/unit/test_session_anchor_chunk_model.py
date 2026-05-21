from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.orm import Session

from app.core.settings import get_settings
from app.models.base import Base, _tables_for_create_all
from app.models.resume_anchor_cache import ResumeAnchorCacheChunk
from app.models.session_anchor import SessionAnchorChunk


def _sample_chunk(**overrides) -> SessionAnchorChunk:
    data = {
        "session_id": "sess_a",
        "source_type": "resume",
        "source_revision_id": "rev_1",
        "source_artifact_id": "artifact_1",
        "source_turn_id": None,
        "chunk_index": 0,
        "tier": "highlight",
        "section_name": "project_experience",
        "heading": "Data query optimization",
        "project_name": "Smart Care Platform",
        "text": "Realtime data by iotId lands in Redis Hash, then HMGET batches fill back.",
        "tech_keywords": ["Redis", "HMGET", "MyBatis-Plus"],
        "dimensions_hint": ["system_design", "technical_depth"],
        "chunker_mode": "A",
        "embedding_model_version": "text-embedding-3-small@v1",
        "embedding": [0.1] * int(get_settings().resume_rag_embedding_dimension or 1536),
        "expires_at": datetime.now(UTC) + timedelta(hours=24),
    }
    data.update(overrides)
    return SessionAnchorChunk(**data)


def test_session_anchor_chunk_embedding_dim_matches_settings() -> None:
    expected = int(get_settings().resume_rag_embedding_dimension or 1536)
    assert SessionAnchorChunk.__table__.c.embedding.type.dim == expected


def test_session_anchor_chunk_model_exposes_source_and_revision_filters() -> None:
    columns = SessionAnchorChunk.__table__.c

    assert columns.session_id.index is True
    assert columns.source_type.index is True
    assert columns.source_revision_id.index is True
    assert columns.embedding_model_version.index is True
    assert columns.source_cache_key.index is True
    assert {"resume", "self_intro"}.issubset(
        set(SessionAnchorChunk.P0_SOURCE_TYPES)
    )


def test_resume_anchor_cache_chunk_model_exposes_cache_lookup_columns() -> None:
    columns = ResumeAnchorCacheChunk.__table__.c

    assert columns.cache_key.index is True
    assert columns.embedding_model_version.index is True
    assert columns.expires_at.index is True
    assert columns.embedding.type.dim == int(
        get_settings().resume_rag_embedding_dimension or 1536
    )


def test_sqlite_init_db_table_filter_skips_session_anchor_chunks() -> None:
    engine = create_engine("sqlite://", future=True)

    tables = _tables_for_create_all(engine)

    assert SessionAnchorChunk.__table__ not in tables
    assert ResumeAnchorCacheChunk.__table__ not in tables
    assert "session_anchor_chunks" in Base.metadata.tables
    assert "resume_anchor_cache_chunks" in Base.metadata.tables


def test_session_anchor_chunk_round_trip_with_pgvector() -> None:
    url = os.environ.get("TEST_PGVECTOR_DATABASE_URL")
    if not url:
        pytest.skip("set TEST_PGVECTOR_DATABASE_URL to run pgvector round-trip")

    engine = create_engine(url, future=True)
    try:
        with engine.begin() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            conn.execute(text("DROP TABLE IF EXISTS session_anchor_chunks"))
        Base.metadata.create_all(engine, tables=[SessionAnchorChunk.__table__])
        with Session(engine) as session:
            session.add(_sample_chunk())
            session.commit()
            row = session.scalar(
                select(SessionAnchorChunk).where(
                    SessionAnchorChunk.session_id == "sess_a"
                )
            )
        assert row is not None
        assert row.tier == "highlight"
        assert row.source_type == "resume"
        assert row.embedding[0] == pytest.approx(0.1)
        assert "session_anchor_chunks" in inspect(engine).get_table_names()
    finally:
        with engine.begin() as conn:
            conn.execute(text("DROP TABLE IF EXISTS session_anchor_chunks"))
        engine.dispose()
