from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.engine.workflow.nodes import resume_parse as resume_parse_mod
from app.engine.workflow.nodes.resume_parse import resume_parse_node
from app.models.base import Base
from app.models.resume_parse_artifact import ResumeParseArtifact
from app.services.resume_parse_artifacts import (
    consume_resume_parse_artifact,
    create_resume_parse_artifact,
    read_resume_parse_artifact,
)

HIGH_STRUCTURE_TEXT = """
Projects
Smart Learning Coupon Guard | Backend Owner | 2024.05-2024.08
- Designed Redis Hash inventory buckets with Lua atomic deduction.
- Added RabbitMQ delayed compensation and idempotent retry records.
- Tuned Spring Boot APIs with MyBatis-Plus batch queries.
- Built Prometheus alerts for oversell risk and Redis hot keys.
Skills
- Java, Spring Boot, Redis, Lua, RabbitMQ, MyBatis-Plus
"""


def _db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine, tables=[ResumeParseArtifact.__table__])
    return sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)


def test_resume_parse_node_vectorizes_when_source_id_present(monkeypatch) -> None:
    session_local = _db()
    with session_local() as db_session:
        artifact = create_resume_parse_artifact(
            text=HIGH_STRUCTURE_TEXT,
            parsed={"summary": "Redis"},
            filename="r.md",
            db_session=db_session,
        )
        assert artifact is not None
        monkeypatch.setattr(
            resume_parse_mod,
            "consume_resume_parse_artifact",
            lambda artifact_id: consume_resume_parse_artifact(
                artifact_id,
                db_session=db_session,
            ),
        )
        monkeypatch.setattr(
            resume_parse_mod,
            "vectorize_resume",
            lambda **kw: {
                "status": "ready",
                "mode": "A",
                "chunk_count": 12,
                "resume_revision_id": kw["resume_revision_id"],
                "embedding_model_version": "text-embedding-3-small@v1",
            },
        )

        out = resume_parse_node(
            {
                "session_id": "sess_a",
                "job_spec": {"title": "Backend"},
                "candidate": {"resume_source_id": artifact.artifact_id},
            }
        )

        assert out["candidate"]["resume_vector_status"]["status"] == "ready"
        assert out["candidate"]["resume_vector_status"]["resume_revision_id"]
        assert read_resume_parse_artifact(
            artifact.artifact_id,
            db_session=db_session,
        ) is None


def test_resume_parse_node_skips_when_no_source_id() -> None:
    out = resume_parse_node(
        {
            "session_id": "sess_a",
            "job_spec": {"title": "Backend"},
            "candidate": {},
        }
    )

    assert out["candidate"]["resume_vector_status"]["status"] == "skipped"
    assert out["candidate"]["resume_vector_status"]["skipped_reason"] == (
        "no_parse_artifact"
    )


def test_resume_parse_node_skips_when_artifact_already_consumed(monkeypatch) -> None:
    session_local = _db()
    with session_local() as db_session:
        artifact = create_resume_parse_artifact(
            text="Redis",
            parsed={},
            filename=None,
            db_session=db_session,
        )
        assert artifact is not None
        consume_resume_parse_artifact(artifact.artifact_id, db_session=db_session)
        monkeypatch.setattr(
            resume_parse_mod,
            "consume_resume_parse_artifact",
            lambda artifact_id: consume_resume_parse_artifact(
                artifact_id,
                db_session=db_session,
            ),
        )

        out = resume_parse_node(
            {
                "session_id": "sess_a",
                "job_spec": {"title": "Backend"},
                "candidate": {"resume_source_id": artifact.artifact_id},
            }
        )

        assert out["candidate"]["resume_vector_status"]["status"] == "skipped"
        assert out["candidate"]["resume_vector_status"]["skipped_reason"] == (
            "parse_artifact_missing_or_expired"
        )


def test_resume_parse_node_returns_failed_on_vectorize_error(monkeypatch) -> None:
    session_local = _db()
    with session_local() as db_session:
        artifact = create_resume_parse_artifact(
            text=HIGH_STRUCTURE_TEXT,
            parsed=None,
            filename=None,
            db_session=db_session,
        )
        assert artifact is not None
        monkeypatch.setattr(
            resume_parse_mod,
            "consume_resume_parse_artifact",
            lambda artifact_id: consume_resume_parse_artifact(
                artifact_id,
                db_session=db_session,
            ),
        )
        monkeypatch.setattr(
            resume_parse_mod,
            "vectorize_resume",
            lambda **kw: {
                "status": "failed",
                "error": "upstream 500",
                "resume_revision_id": kw["resume_revision_id"],
            },
        )

        out = resume_parse_node(
            {
                "session_id": "sess_a",
                "job_spec": {"title": "Backend"},
                "candidate": {"resume_source_id": artifact.artifact_id},
            }
        )

        assert out["candidate"]["resume_vector_status"]["status"] == "failed"
        assert out["candidate"]["resume_vector_status"]["error"] == "upstream 500"


def test_resume_parse_node_keeps_rubric_outputs_intact() -> None:
    out = resume_parse_node(
        {
            "session_id": "sess_a",
            "job_spec": {
                "title": "Backend",
                "rubric_dimensions": ["system_design"],
                "rubric": {"system_design": "Assess system_design."},
            },
            "candidate": {},
        }
    )

    assert out["dimensions"] == ["system_design"]
    assert out["rubric"] == {"system_design": "Assess system_design."}
    assert out["scores_per_dim"] == {"system_design": None}
