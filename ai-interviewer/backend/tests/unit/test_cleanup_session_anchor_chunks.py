from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.resume_parse_artifact import ResumeParseArtifact
from app.models.session_anchor import SessionAnchorChunk
from app.scripts.cleanup_session_anchor_chunks import run_cleanup
from app.services.resume_embedding import current_embedding_model_version


def _db():
    engine = create_engine(
        "sqlite://",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SessionAnchorChunk.__table__.create(engine)
    ResumeParseArtifact.__table__.create(engine)
    return sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)


def _chunk(*, session_id: str, expires_at: datetime) -> SessionAnchorChunk:
    return SessionAnchorChunk(
        session_id=session_id,
        source_type="resume",
        source_revision_id=f"rev_{session_id}",
        source_artifact_id=f"artifact_{session_id}",
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
        embedding_model_version=current_embedding_model_version(),
        embedding=[0.1] * 1536,
        expires_at=expires_at,
    )


def _artifact(*, artifact_id: str, expires_at: datetime) -> ResumeParseArtifact:
    return ResumeParseArtifact(
        artifact_id=artifact_id,
        redacted_text=f"{artifact_id} resume",
        parsed={},
        filename=None,
        text_sha256=artifact_id,
        created_at=datetime.now(UTC),
        expires_at=expires_at,
    )


def test_cleanup_session_anchor_chunks_deletes_expired_only() -> None:
    session_local = _db()
    now = datetime.now(UTC)
    with session_local() as db_session:
        db_session.add_all(
            [
                _chunk(session_id="expired", expires_at=now - timedelta(days=1)),
                _chunk(session_id="fresh", expires_at=now + timedelta(days=1)),
            ]
        )
        db_session.commit()

        report = run_cleanup(db_session=db_session, now=now)
        remaining = db_session.scalars(select(SessionAnchorChunk)).all()

    assert report["session_anchor_chunks_deleted"] == 1
    assert {row.session_id for row in remaining} == {"fresh"}


def test_cleanup_session_anchor_chunks_also_deletes_expired_parse_artifacts() -> None:
    session_local = _db()
    now = datetime.now(UTC)
    with session_local() as db_session:
        db_session.add_all(
            [
                _artifact(
                    artifact_id="expired_artifact",
                    expires_at=now - timedelta(seconds=1),
                ),
                _artifact(
                    artifact_id="fresh_artifact",
                    expires_at=now + timedelta(seconds=1),
                ),
            ]
        )
        db_session.commit()

        report = run_cleanup(db_session=db_session, now=now)

        assert db_session.get(ResumeParseArtifact, "expired_artifact") is None
        assert db_session.get(ResumeParseArtifact, "fresh_artifact") is not None

    assert report["resume_parse_artifacts_deleted"] == 1
    assert report["total_deleted"] == 1
