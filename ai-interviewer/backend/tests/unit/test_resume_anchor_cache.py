from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.resume_anchor_cache import ResumeAnchorCacheChunk
from app.models.session_anchor import SessionAnchorChunk
from app.services.resume_anchor_cache import (
    cleanup_expired_resume_anchor_cache_chunks,
    purge_resume_anchor_cache_keys,
    resume_anchor_cache_key,
    store_resume_anchor_cache_chunks,
    try_bind_cached_resume_anchors,
)


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


def _cache_chunk(
    *,
    cache_key: str = "cache_a",
    chunk_index: int = 0,
    expires_at: datetime | None = None,
) -> ResumeAnchorCacheChunk:
    return ResumeAnchorCacheChunk(
        cache_key=cache_key,
        embedding_model_version="qwen:text-embedding-v4:1536@v1",
        chunk_index=chunk_index,
        tier="highlight",
        section_name="Projects",
        heading=f"Coupon consistency {chunk_index}",
        project_name="Coupon Guard",
        text=f"Redis Lua coupon guard {chunk_index}.",
        tech_keywords=["Redis", "Lua"],
        dimensions_hint=["system_design"],
        chunker_mode="A",
        embedding=[0.1] * 1536,
        expires_at=expires_at or datetime.now(UTC) + timedelta(days=1),
    )


def _session_chunk(
    *,
    session_id: str = "sess_a",
    revision_id: str = "rev_a",
    source_cache_key: str = "cache_a",
    chunk_index: int = 0,
) -> SessionAnchorChunk:
    return SessionAnchorChunk(
        session_id=session_id,
        source_type="resume",
        source_revision_id=revision_id,
        source_artifact_id="artifact_a",
        source_turn_id=None,
        chunk_index=chunk_index,
        tier="highlight",
        section_name="Projects",
        heading=f"Coupon consistency {chunk_index}",
        project_name="Coupon Guard",
        text=f"Redis Lua coupon guard {chunk_index}.",
        tech_keywords=["Redis", "Lua"],
        dimensions_hint=["system_design"],
        chunker_mode="A",
        embedding_model_version="qwen:text-embedding-v4:1536@v1",
        embedding=[0.2] * 1536,
        expires_at=datetime.now(UTC) + timedelta(days=1),
        source_cache_key=source_cache_key,
    )


def test_resume_anchor_cache_key_ignores_non_chunking_parse_metadata() -> None:
    parsed = {
        "summary": "Backend candidate",
        "projects": [{"name": "Coupon Guard", "tech_stack": ["Redis"]}],
        "parse_status": {"cached": False, "cache_age_ms": 0},
        "raw_text_preview": "should not affect cache",
        "resume_source_id": "artifact_a",
    }
    same = {
        **parsed,
        "parse_status": {"cached": True, "cache_age_ms": 9999},
        "raw_text_preview": "different preview",
        "resume_source_id": "artifact_b",
    }
    changed = {
        **parsed,
        "projects": [{"name": "Order Risk", "tech_stack": ["Kafka"]}],
    }

    key = resume_anchor_cache_key(
        redacted_text="Redis Lua coupon guard",
        parsed=parsed,
        embedding_model_version="qwen:text-embedding-v4:1536@v1",
    )

    assert key == resume_anchor_cache_key(
        redacted_text="Redis Lua coupon guard",
        parsed=same,
        embedding_model_version="qwen:text-embedding-v4:1536@v1",
    )
    assert key != resume_anchor_cache_key(
        redacted_text="Redis Lua coupon guard",
        parsed=changed,
        embedding_model_version="qwen:text-embedding-v4:1536@v1",
    )
    assert key != resume_anchor_cache_key(
        redacted_text="Redis Lua coupon guard",
        parsed=parsed,
        embedding_model_version="openai:text-embedding-3-small:1536@v1",
    )


def test_try_bind_cached_resume_anchors_copies_rows_to_session() -> None:
    session_local = _db()
    with session_local() as db_session:
        db_session.add_all([_cache_chunk(chunk_index=0), _cache_chunk(chunk_index=1)])
        db_session.commit()

        status = try_bind_cached_resume_anchors(
            session_id="sess_new",
            resume_revision_id="rev_new",
            source_artifact_id="artifact_new",
            cache_key="cache_a",
            embedding_model_version="qwen:text-embedding-v4:1536@v1",
            db_session=db_session,
        )
        rows = db_session.scalars(
            select(SessionAnchorChunk)
            .where(SessionAnchorChunk.session_id == "sess_new")
            .order_by(SessionAnchorChunk.chunk_index)
        ).all()
        cache_rows = db_session.scalars(select(ResumeAnchorCacheChunk)).all()

    assert status["status"] == "ready"
    assert status["cache_hit"] is True
    assert status["chunk_count"] == 2
    assert status["resume_revision_id"] == "rev_new"
    assert [row.chunk_index for row in rows] == [0, 1]
    assert {row.source_revision_id for row in rows} == {"rev_new"}
    assert {row.source_artifact_id for row in rows} == {"artifact_new"}
    assert {row.source_cache_key for row in rows} == {"cache_a"}
    assert {row.session_id for row in rows} == {"sess_new"}
    assert [row.hit_count for row in cache_rows] == [1, 1]
    assert all(row.last_used_at is not None for row in cache_rows)


def test_try_bind_cached_resume_anchors_ignores_expired_rows() -> None:
    session_local = _db()
    with session_local() as db_session:
        db_session.add(
            _cache_chunk(expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
        db_session.commit()

        status = try_bind_cached_resume_anchors(
            session_id="sess_new",
            resume_revision_id="rev_new",
            source_artifact_id="artifact_new",
            cache_key="cache_a",
            embedding_model_version="qwen:text-embedding-v4:1536@v1",
            db_session=db_session,
        )
        rows = db_session.scalars(select(SessionAnchorChunk)).all()

    assert status is None
    assert rows == []


def test_store_purge_and_cleanup_resume_anchor_cache_chunks() -> None:
    session_local = _db()
    now = datetime.now(UTC)
    with session_local() as db_session:
        db_session.add_all(
            [
                _session_chunk(source_cache_key="cache_a", chunk_index=0),
                _session_chunk(source_cache_key="cache_a", chunk_index=1),
                _cache_chunk(
                    cache_key="expired",
                    expires_at=now - timedelta(seconds=1),
                ),
            ]
        )
        db_session.commit()

        stored = store_resume_anchor_cache_chunks(
            cache_key="cache_a",
            embedding_model_version="qwen:text-embedding-v4:1536@v1",
            session_id="sess_a",
            resume_revision_id="rev_a",
            db_session=db_session,
        )
        expired_deleted = cleanup_expired_resume_anchor_cache_chunks(
            db_session=db_session,
            now=now,
        )
        purged = purge_resume_anchor_cache_keys(
            ["cache_a"],
            db_session=db_session,
        )
        remaining = db_session.scalars(select(ResumeAnchorCacheChunk)).all()

    assert stored == 2
    assert expired_deleted == 1
    assert purged == 2
    assert remaining == []
