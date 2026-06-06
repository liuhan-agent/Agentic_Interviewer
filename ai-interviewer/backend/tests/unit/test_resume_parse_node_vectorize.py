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


def test_resume_parse_node_traces_opening_event_without_raw_materials(
    monkeypatch,
) -> None:
    traced: list[tuple[str, dict[str, object], int | None]] = []

    class _Tracer:
        def trace_session_started(self, _state: dict[str, object]) -> None:
            return None

        def trace_node_event(
            self,
            _state: dict[str, object],
            *,
            node: str,
            payload: dict[str, object],
            logical_turn_idx: int | None = None,
            **_kwargs: object,
        ) -> None:
            traced.append((node, payload, logical_turn_idx))

    monkeypatch.setattr(resume_parse_mod, "get_tracer", lambda: _Tracer())
    monkeypatch.setattr(
        resume_parse_mod,
        "read_resume_parse_artifact",
        lambda _source_id: None,
    )

    out = resume_parse_node(
        {
            "session_id": "sess_opening",
            "turn_idx": 0,
            "job_spec": {
                "title": "Backend",
                "required_skills": ["Redis", "Kafka"],
                "rubric_dimensions": ["system_design", "communication"],
                "rubric": {
                    "system_design": "Assess system design.",
                    "communication": "Assess communication.",
                },
            },
            "candidate": {
                "resume_source_id": "resume-source-secret-123",
                "resume_vector_status": {
                    "resume_revision_id": "resume-revision-secret-456",
                },
                "resume_parsed": {
                    "summary": "raw resume secret should not appear",
                    "skills": ["Redis", "Spring Boot", "Kafka"],
                    "highlights": ["raw highlight secret should not appear"],
                    "concerns": ["raw concern secret should not appear"],
                    "candidate_profile": {"school": "raw school secret"},
                    "projects": [
                        {
                            "id": "p1",
                            "name": "Coupon Guard",
                            "role": "Tech Lead",
                            "tech_stack": ["Redis", "Kafka"],
                            "question_anchors": ["热点 key 失效压测"],
                            "responsibilities": [
                                "raw responsibility secret should not appear"
                            ],
                            "achievements": [
                                "raw achievement secret should not appear"
                            ],
                        }
                    ],
                    "focus_areas": [
                        {
                            "id": "f1",
                            "label": "缓存一致性治理",
                            "project_id": "p1",
                            "dimensions": ["system_design"],
                            "skills": ["Redis"],
                            "priority": 1,
                        }
                    ],
                },
            },
        }
    )

    assert out["dimensions"] == ["system_design", "communication"]
    events = [item for item in traced if item[0] == "resume_parse"]
    assert events
    _node, payload, logical_turn_idx = events[-1]
    assert logical_turn_idx == 0
    assert payload["phase"] == "opening"
    assert payload["workflow_node"] == "resume_parse"
    assert payload["semantic_node"] == "resume_parse"
    assert payload["dimensions"] == ["system_design", "communication"]
    assert payload["rubric_dimensions"] == ["system_design", "communication"]
    assert payload["required_skills"] == ["Redis", "Kafka"]
    assert payload["candidate_skills"] == ["Redis", "Spring Boot", "Kafka"]
    assert payload["resume_projects_count"] == 1
    assert payload["resume_focus_areas_count"] == 1
    assert payload["resume_projects"] == [
        {
            "id": "p1",
            "name": "Coupon Guard",
            "role": "Tech Lead",
            "tech_stack": ["Redis", "Kafka"],
        }
    ]
    assert payload["resume_focus_areas"] == [
        {
            "id": "f1",
            "label": "缓存一致性治理",
            "project_id": "p1",
            "dimensions": ["system_design"],
            "skills": ["Redis"],
            "priority": 1,
        }
    ]
    assert payload["resume_anchors"] == [
        {
            "label": "缓存一致性治理",
            "project_name": "Coupon Guard",
            "tech_stack": ["Redis", "Kafka"],
            "question_anchors": ["热点 key 失效压测"],
            "skills": ["Redis"],
            "dimensions": ["system_design"],
        }
    ]
    assert payload["rubric_dimension_keys"] == ["system_design", "communication"]
    assert payload["dimensions_count"] == 2
    assert payload["rubric_count"] == 2
    assert payload["dimension_status_summary"] == {
        "total": 2,
        "pending": 2,
        "active": 0,
        "passed": 0,
        "failed": 0,
        "other": 0,
    }
    assert payload["scores_per_dim_summary"] == {
        "total": 2,
        "scored": 0,
        "unscored": 2,
    }
    assert payload["resume_vector_status"]["status"] == "skipped"  # type: ignore[index]
    dumped = str(payload)
    assert "raw resume secret should not appear" not in dumped
    assert "raw highlight secret should not appear" not in dumped
    assert "raw concern secret should not appear" not in dumped
    assert "raw school secret" not in dumped
    assert "raw responsibility secret should not appear" not in dumped
    assert "raw achievement secret should not appear" not in dumped
    assert "Assess system design." not in dumped
    assert "resume-source-secret-123" not in dumped
    assert "resume-revision-secret-456" not in dumped
