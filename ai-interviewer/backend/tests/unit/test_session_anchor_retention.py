from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.resume_anchor_cache import ResumeAnchorCacheChunk
from app.models.session_anchor import SessionAnchorChunk
from app.services.session_anchor_retention import cleanup_completed_session_anchors


def _db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    SessionAnchorChunk.__table__.create(engine)
    ResumeAnchorCacheChunk.__table__.create(engine)
    return sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)


def _session_chunk(session_id: str, cache_key: str | None) -> SessionAnchorChunk:
    return SessionAnchorChunk(
        session_id=session_id,
        source_type="resume",
        source_revision_id=f"rev_{session_id}",
        source_artifact_id=f"artifact_{session_id}",
        source_cache_key=cache_key,
        source_turn_id=None,
        chunk_index=0,
        tier="highlight",
        section_name="Projects",
        heading="Coupon consistency",
        project_name="Coupon Guard",
        text=f"{session_id} Redis chunk",
        tech_keywords=["Redis"],
        dimensions_hint=["system_design"],
        chunker_mode="A",
        embedding_model_version="qwen:text-embedding-v4:1536@v1",
        embedding=[0.1] * 1536,
        expires_at=datetime.now(UTC) + timedelta(days=8),
    )


def _cache_chunk(cache_key: str) -> ResumeAnchorCacheChunk:
    return ResumeAnchorCacheChunk(
        cache_key=cache_key,
        embedding_model_version="qwen:text-embedding-v4:1536@v1",
        chunk_index=0,
        tier="highlight",
        section_name="Projects",
        heading="Coupon consistency",
        project_name="Coupon Guard",
        text="Redis cached chunk",
        tech_keywords=["Redis"],
        dimensions_hint=["system_design"],
        chunker_mode="A",
        embedding=[0.1] * 1536,
        expires_at=datetime.now(UTC) + timedelta(days=7),
    )


def test_cleanup_completed_session_anchors_deletes_only_session_rows() -> None:
    session_local = _db()
    with session_local() as db_session:
        db_session.add_all(
            [
                _session_chunk("sess_done", "cache_a"),
                _session_chunk("sess_other", "cache_a"),
                _cache_chunk("cache_a"),
            ]
        )
        db_session.commit()

        deleted = cleanup_completed_session_anchors(
            "sess_done",
            db_session=db_session,
        )
        remaining_session_rows = db_session.scalars(select(SessionAnchorChunk)).all()
        remaining_cache_rows = db_session.scalars(select(ResumeAnchorCacheChunk)).all()

    assert deleted == 1
    assert {row.session_id for row in remaining_session_rows} == {"sess_other"}
    assert {row.cache_key for row in remaining_cache_rows} == {"cache_a"}
