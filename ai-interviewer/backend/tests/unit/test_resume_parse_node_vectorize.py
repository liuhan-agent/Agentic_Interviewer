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


def test_resume_parse_node_starts_background_vector_job(monkeypatch) -> None:
    session_local = _db()
    with session_local() as db_session:
        artifact = create_resume_parse_artifact(
            text=HIGH_STRUCTURE_TEXT,
            parsed={"summary": "Redis"},
            filename="r.md",
            db_session=db_session,
        )
        assert artifact is not None
        captured: dict[str, object] = {}

        def fake_start_job(**kwargs):
            captured.update(kwargs)
            return {
                "status": "pending_background",
                "source_type": "resume",
                "resume_source_id": kwargs["resume_source_id"],
                "resume_revision_id": None,
            }

        monkeypatch.setattr(
            resume_parse_mod,
            "read_resume_parse_artifact",
            lambda artifact_id: read_resume_parse_artifact(
                artifact_id,
                db_session=db_session,
            ),
        )
        monkeypatch.setattr(resume_parse_mod, "start_resume_vector_job", fake_start_job)
        monkeypatch.setattr(
            resume_parse_mod,
            "vectorize_resume",
            lambda **_kw: (_ for _ in ()).throw(
                AssertionError("resume_parse_node must not vectorize synchronously")
            ),
            raising=False,
        )

        out = resume_parse_node(
            {
                "session_id": "sess_a",
                "job_spec": {"title": "Backend"},
                "candidate": {
                    "resume_source_id": artifact.artifact_id,
                    "resume_parsed": {"summary": "candidate copy"},
                },
            }
        )

        status = out["candidate"]["resume_vector_status"]
        assert status["status"] == "pending_background"
        assert status["resume_source_id"] == artifact.artifact_id
        assert captured["session_id"] == "sess_a"
        assert captured["resume_source_id"] == artifact.artifact_id
        assert captured["parsed"] == {"summary": "candidate copy"}
        assert read_resume_parse_artifact(
            artifact.artifact_id,
            db_session=db_session,
        ) is not None


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
            "read_resume_parse_artifact",
            lambda artifact_id: read_resume_parse_artifact(
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


def test_resume_parse_node_returns_pending_when_background_job_start_fails(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        resume_parse_mod,
        "read_resume_parse_artifact",
        lambda artifact_id: type("Artifact", (), {"artifact_id": artifact_id})(),
    )
    monkeypatch.setattr(
        resume_parse_mod,
        "start_resume_vector_job",
        lambda **_kw: {
            "status": "failed",
            "error": "executor unavailable",
            "resume_source_id": "artifact_1",
            "resume_revision_id": None,
        },
    )

    out = resume_parse_node(
        {
            "session_id": "sess_a",
            "job_spec": {"title": "Backend"},
            "candidate": {"resume_source_id": "artifact_1"},
        }
    )

    assert out["candidate"]["resume_vector_status"]["status"] == "failed"
    assert out["candidate"]["resume_vector_status"]["error"] == "executor unavailable"


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
