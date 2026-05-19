from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.v1 import admin as admin_api
from app.models.generation_trace import GenerationTrace
from app.models.interview_session import InterviewSession
from app.models.resume_parse_artifact import ResumeParseArtifact
from app.models.session_anchor import SessionAnchorChunk
from app.services.resume_embedding import current_embedding_model_version
from app.services.session_anchor_vectorize import (
    vectorize_resume,
    vectorize_self_intro_anchor_cards,
)

LONG_SELF_INTRO_TEXT = (
    "I led the Redis coupon guard project, designed Lua atomic deduction, "
    "handled RabbitMQ compensation, built Prometheus alerts, and reviewed "
    "incidents with product and operations teams. The work balanced consistency, "
    "rollback safety, observability, and user experience under traffic."
)

LONG_RESUME_TAIL = (
    "\n- Added replay tests for coupon rollback, payment confirmation, and "
    "inventory restore scenarios across Redis, MySQL, RabbitMQ, and Spring Boot."
    "\n- Coordinated on-call reviews, dashboards, and release checklists with "
    "product, QA, operations, and customer success during campaign traffic."
    "\n- Reworked data validation, audit trails, and alert routing so incidents "
    "could be traced from user request through queue retry and database writes."
    "\n- Documented ownership boundaries, failure modes, and escalation paths for "
    "future maintainers while keeping measurable latency and availability targets."
)


def _db(*, include_admin_tables: bool = False):
    engine = create_engine(
        "sqlite://",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SessionAnchorChunk.__table__.create(engine)
    if include_admin_tables:
        ResumeParseArtifact.__table__.create(engine)
        InterviewSession.__table__.create(engine)
        GenerationTrace.__table__.create(engine)
    return sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)


def _patch_embeddings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.services.session_anchor_vectorize.embed_chunks",
        lambda texts, **_kwargs: [[0.1] * 1536 for _ in texts],
    )


def test_phone_numbers_are_redacted_before_storing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_embeddings(monkeypatch)
    session_local = _db()
    raw = (
        "Projects\n"
        "Redis Coupon Guard | Backend Owner\n"
        "- 联系电话 13800001111, alex@example.com, Redis 项目负责人。\n"
        "- Designed Lua atomic deduction and RabbitMQ compensation.\n"
        "- Built Prometheus alerts and MySQL audit tables.\n"
        "- Tuned Spring Boot APIs under campaign traffic.\n"
        f"{LONG_RESUME_TAIL}\n"
        "Skills\nRedis, Lua, RabbitMQ, MySQL, Prometheus, Spring Boot"
    )
    with session_local() as db_session:
        vectorize_resume(
            session_id="sess_a",
            resume_revision_id="rev_1",
            source_artifact_id="artifact_1",
            raw_text=raw,
            parsed=None,
            db_session=db_session,
        )
        rows = db_session.scalars(select(SessionAnchorChunk)).all()

    assert rows
    for row in rows:
        assert "13800001111" not in row.text
        assert "alex@example.com" not in row.text


def test_id_card_numbers_are_redacted_before_storing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_embeddings(monkeypatch)
    session_local = _db()
    raw = (
        "Projects\n"
        "Risk Platform | Backend Owner\n"
        "- 身份证 32010119900101003X, Redis 项目负责人。\n"
        "- Designed Lua atomic deduction and RabbitMQ compensation.\n"
        "- Built Prometheus alerts and MySQL audit tables.\n"
        "- Tuned Spring Boot APIs under campaign traffic.\n"
        f"{LONG_RESUME_TAIL}\n"
        "Skills\nRedis, Lua, RabbitMQ, MySQL, Prometheus, Spring Boot"
    )
    with session_local() as db_session:
        vectorize_resume(
            session_id="sess_a",
            resume_revision_id="rev_1",
            source_artifact_id="artifact_1",
            raw_text=raw,
            parsed=None,
            db_session=db_session,
        )
        rows = db_session.scalars(select(SessionAnchorChunk)).all()

    assert rows
    assert all("32010119900101003X" not in row.text for row in rows)


def test_self_intro_anchor_cards_are_redacted_before_storing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_embeddings(monkeypatch)
    session_local = _db()
    with session_local() as db_session:
        vectorize_self_intro_anchor_cards(
            session_id="sess_intro",
            self_intro_revision_id="intro_rev_1",
            turn_idx=0,
            sanitized_answer=LONG_SELF_INTRO_TEXT,
            anchor_cards=[
                {
                    "kind": "claim",
                    "title": "Contact leak",
                    "text": (
                        "I can be reached at 13800001111 while I describe Redis work."
                    ),
                    "tech_keywords": ["Redis"],
                }
            ],
            db_session=db_session,
        )
        rows = db_session.scalars(select(SessionAnchorChunk)).all()

    assert rows
    assert all("13800001111" not in row.text for row in rows)


@contextmanager
def _admin_db(monkeypatch: pytest.MonkeyPatch):
    session_local = _db(include_admin_tables=True)

    @contextmanager
    def get_session():
        sess = session_local()
        try:
            yield sess
            sess.commit()
        except Exception:
            sess.rollback()
            raise
        finally:
            sess.close()

    monkeypatch.setattr(admin_api, "get_session", get_session, raising=False)
    monkeypatch.setattr(
        admin_api,
        "get_settings",
        lambda: type(
            "S",
            (),
            {"api_token": None, "allow_open_admin": True, "app_env": "dev"},
        )(),
    )
    yield session_local


def test_subject_deletion_wipes_all_anchor_rows_and_trace_payloads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _admin_db(monkeypatch) as session_local:
        now = datetime.now(UTC)
        with session_local() as db_session:
            db_session.add(
                SessionAnchorChunk(
                    session_id="sess_x",
                    source_type="resume",
                    source_revision_id="rev_1",
                    source_artifact_id="artifact_x",
                    source_turn_id=None,
                    chunk_index=0,
                    tier="highlight",
                    section_name="Projects",
                    heading="Coupon",
                    project_name="Coupon Guard",
                    text="Redis secret anchor",
                    tech_keywords=["Redis"],
                    dimensions_hint=["system_design"],
                    chunker_mode="A",
                    embedding_model_version=current_embedding_model_version(),
                    embedding=[0.1] * 1536,
                    expires_at=now + timedelta(hours=1),
                )
            )
            db_session.add(
                ResumeParseArtifact(
                    artifact_id="artifact_x",
                    redacted_text="Redis secret resume",
                    parsed={},
                    filename=None,
                    text_sha256="x",
                    created_at=now,
                    expires_at=now + timedelta(hours=1),
                )
            )
            db_session.add(
                InterviewSession(
                    session_id="sess_x",
                    trace_id="trace_x",
                    candidate_name="Ada",
                    job_title="Backend",
                    job_level="senior",
                    mode="mixed",
                    status="running",
                    setup_snapshot={
                        "candidate": {
                            "resume_source_id": "artifact_x",
                            "resume_parsed": {"summary": "Redis secret resume"},
                        },
                    },
                    current_question={
                        "selection_artifacts": {
                            "candidate_anchor_rag": {"hits": [{"id": 1}]},
                        },
                    },
                )
            )
            db_session.add(
                GenerationTrace(
                    trace_id="trace_x",
                    session_id="sess_x",
                    turn_idx=0,
                    node="ask_question",
                    state_snapshot={
                        "payload": {
                            "selection_artifacts": {
                                "candidate_anchor_rag": {"hits": [{"id": 1}]},
                            },
                            "resume_rag_block": "[resume] Redis secret anchor",
                        }
                    },
                )
            )
            db_session.commit()

        app = FastAPI()
        app.include_router(admin_api.router)
        response = TestClient(app).delete("/admin/sessions/sess_x/anchor-data")

        with session_local() as db_session:
            chunks = db_session.scalars(
                select(SessionAnchorChunk).where(SessionAnchorChunk.session_id == "sess_x")
            ).all()
            trace = db_session.scalars(select(GenerationTrace)).one()
            artifact = db_session.get(ResumeParseArtifact, "artifact_x")

    assert response.status_code == 200
    assert chunks == []
    assert artifact is None
    snapshot_text = str(trace.state_snapshot)
    assert "candidate_anchor_rag" not in snapshot_text
    assert "Redis secret" not in snapshot_text
