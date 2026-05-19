from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.base import Base
from app.models.resume_parse_artifact import ResumeParseArtifact
from app.services import resume_parse_artifacts as artifacts_mod
from app.services.resume_parse_artifacts import (
    cleanup_expired_resume_parse_artifacts,
    consume_resume_parse_artifact,
    create_resume_parse_artifact,
    read_resume_parse_artifact,
)


def _db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine, tables=[ResumeParseArtifact.__table__])
    session_local = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    return engine, session_local


def test_create_resume_parse_artifact_redacts_pii() -> None:
    _engine, session_local = _db()
    with session_local() as db_session:
        artifact = create_resume_parse_artifact(
            text="Alex 13800001111 alex@example.com did Redis work.",
            parsed={"summary": "Redis work"},
            filename="resume.txt",
            db_session=db_session,
        )

        assert artifact is not None
        assert "13800001111" not in artifact.redacted_text
        assert "alex@example.com" not in artifact.redacted_text
        row = db_session.get(ResumeParseArtifact, artifact.artifact_id)
        assert row is not None
        assert row.redacted_text == artifact.redacted_text
        assert row.parsed == {"summary": "Redis work"}
        assert row.filename == "resume.txt"


def test_read_resume_parse_artifact_does_not_consume() -> None:
    _engine, session_local = _db()
    with session_local() as db_session:
        artifact = create_resume_parse_artifact(
            text="Redis project",
            parsed={},
            filename=None,
            db_session=db_session,
        )

        assert artifact is not None
        assert read_resume_parse_artifact(
            artifact.artifact_id,
            db_session=db_session,
        ) is not None
        assert read_resume_parse_artifact(
            artifact.artifact_id,
            db_session=db_session,
        ) is not None


def test_consume_resume_parse_artifact_is_one_shot() -> None:
    _engine, session_local = _db()
    with session_local() as db_session:
        artifact = create_resume_parse_artifact(
            text="Redis project",
            parsed={},
            filename=None,
            db_session=db_session,
        )

        assert artifact is not None
        first = consume_resume_parse_artifact(
            artifact.artifact_id,
            db_session=db_session,
        )
        second = consume_resume_parse_artifact(
            artifact.artifact_id,
            db_session=db_session,
        )

        assert first is not None and first.consumed_at is not None
        assert second is None


def test_read_returns_none_after_consume() -> None:
    _engine, session_local = _db()
    with session_local() as db_session:
        artifact = create_resume_parse_artifact(
            text="Redis project",
            parsed={},
            filename=None,
            db_session=db_session,
        )

        assert artifact is not None
        consume_resume_parse_artifact(artifact.artifact_id, db_session=db_session)

        assert read_resume_parse_artifact(
            artifact.artifact_id,
            db_session=db_session,
        ) is None


def test_cleanup_expired_resume_parse_artifacts_deletes_only_expired(
    monkeypatch,
) -> None:
    _engine, session_local = _db()
    with session_local() as db_session:
        monkeypatch.setattr(
            artifacts_mod,
            "_now",
            lambda: datetime.now(UTC) - timedelta(hours=2),
        )
        old = create_resume_parse_artifact(
            text="old",
            parsed={},
            filename=None,
            db_session=db_session,
        )
        monkeypatch.undo()
        fresh = create_resume_parse_artifact(
            text="fresh",
            parsed={},
            filename=None,
            db_session=db_session,
        )

        assert old is not None
        assert fresh is not None
        deleted = cleanup_expired_resume_parse_artifacts(db_session=db_session)

        assert deleted == 1
        assert read_resume_parse_artifact(
            fresh.artifact_id,
            db_session=db_session,
        ) is not None
        assert db_session.get(ResumeParseArtifact, old.artifact_id) is None


def test_artifact_cross_worker_simulation(monkeypatch) -> None:
    engine, session_local = _db()

    @contextmanager
    def get_session():
        with session_local() as session:
            yield session
            session.commit()

    monkeypatch.setattr(artifacts_mod, "get_db_session", get_session)

    with Session(engine) as writer:
        artifact = create_resume_parse_artifact(
            text="Redis",
            parsed={},
            filename=None,
            db_session=writer,
        )
        writer.commit()

    assert artifact is not None
    with Session(engine) as reader:
        found = read_resume_parse_artifact(
            artifact.artifact_id,
            db_session=reader,
        )
        assert found is not None
        assert found.redacted_text == artifact.redacted_text


def test_consume_resume_parse_artifact_persists_consumed_at() -> None:
    _engine, session_local = _db()
    with session_local() as db_session:
        artifact = create_resume_parse_artifact(
            text="Redis project",
            parsed={},
            filename=None,
            db_session=db_session,
        )

        assert artifact is not None
        consumed = consume_resume_parse_artifact(
            artifact.artifact_id,
            db_session=db_session,
        )
        row = db_session.scalar(
            select(ResumeParseArtifact).where(
                ResumeParseArtifact.artifact_id == artifact.artifact_id
            )
        )

        assert consumed is not None
        assert row is not None
        assert row.consumed_at is not None
