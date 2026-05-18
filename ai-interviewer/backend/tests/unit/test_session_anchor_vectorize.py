from __future__ import annotations

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.session_anchor import SessionAnchorChunk
from app.services.resume_embedding import ResumeEmbeddingError
from app.services.session_anchor_vectorize import (
    build_self_intro_fallback_cards,
    vectorize_resume,
    vectorize_self_intro_anchor_cards,
)

HIGH_STRUCTURE_TEXT = """
Projects

Smart Learning Coupon Guard | Backend Owner | 2024.05-2024.08
- Designed Redis Hash inventory buckets with Lua atomic deduction.
- Added RabbitMQ delayed compensation and idempotent retry records.
- Tuned Spring Boot APIs with MyBatis-Plus batch queries.
- Built Prometheus alerts for oversell risk and Redis hot keys.

Realtime Order Risk Platform | Core Developer | 2023.06-2024.04
- Built Kafka ingestion and Flink stream rules.
- Used Elasticsearch indexes for investigation queries.
- Designed PostgreSQL partitioning and archive jobs.
- Added Kubernetes rollout checks with canary metrics.

Skills
- Java, Spring Boot, Spring Cloud
- Redis, Lua, RabbitMQ
- Kafka, Flink, Elasticsearch
- PostgreSQL, MySQL, MyBatis-Plus
- Docker, Kubernetes, Prometheus
"""

LONG_SELF_INTRO_TEXT = (
    "I led the Smart Learning coupon guard project where Redis Lua scripts "
    "protected coupon deduction during high traffic. I also handled RabbitMQ "
    "compensation, Spring Boot API tuning, Prometheus alerts, and incident "
    "review with product and operations teams. The most important detail is "
    "how we balanced atomic consistency, user experience, and rollback safety."
)


def _db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    SessionAnchorChunk.__table__.create(engine)
    session_local = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    return session_local


def test_vectorize_resume_writes_chunks_and_returns_ready(monkeypatch) -> None:
    session_local = _db()
    with session_local() as db_session:
        monkeypatch.setattr(
            "app.services.session_anchor_vectorize.embed_chunks",
            lambda texts, **_kw: [[0.1] * 1536 for _ in texts],
        )

        status = vectorize_resume(
            session_id="sess_a",
            resume_revision_id="rev_1",
            source_artifact_id="artifact_1",
            raw_text=HIGH_STRUCTURE_TEXT,
            parsed=None,
            db_session=db_session,
        )
        rows = db_session.scalars(
            select(SessionAnchorChunk).where(SessionAnchorChunk.session_id == "sess_a")
        ).all()

        assert status["status"] == "ready"
        assert status["mode"] == "A"
        assert status["chunk_count"] >= 10
        assert len(rows) == status["chunk_count"]
        assert {row.source_type for row in rows} == {"resume"}
        assert {row.source_revision_id for row in rows} == {"rev_1"}
        assert rows[0].source_artifact_id == "artifact_1"


def test_vectorize_resume_writes_revision_id(monkeypatch) -> None:
    session_local = _db()
    with session_local() as db_session:
        monkeypatch.setattr(
            "app.services.session_anchor_vectorize.embed_chunks",
            lambda texts, **_kw: [[0.1] * 1536 for _ in texts],
        )

        vectorize_resume(
            session_id="sess_a",
            resume_revision_id="rev_1",
            source_artifact_id="artifact_1",
            raw_text=HIGH_STRUCTURE_TEXT,
            parsed=None,
            db_session=db_session,
        )
        vectorize_resume(
            session_id="sess_a",
            resume_revision_id="rev_2",
            source_artifact_id="artifact_2",
            raw_text=HIGH_STRUCTURE_TEXT.replace("Coupon", "Inventory"),
            parsed=None,
            db_session=db_session,
        )
        rows = db_session.scalars(
            select(SessionAnchorChunk).where(SessionAnchorChunk.session_id == "sess_a")
        ).all()

        assert {row.source_revision_id for row in rows} == {"rev_1", "rev_2"}


def test_vectorize_resume_returns_failed_on_embedding_error(monkeypatch) -> None:
    session_local = _db()
    with session_local() as db_session:
        monkeypatch.setattr(
            "app.services.session_anchor_vectorize.embed_chunks",
            lambda _texts, **_kw: (_ for _ in ()).throw(
                ResumeEmbeddingError("upstream 500")
            ),
        )

        status = vectorize_resume(
            session_id="sess_a",
            resume_revision_id="rev_failed",
            source_artifact_id="artifact_failed",
            raw_text=HIGH_STRUCTURE_TEXT,
            parsed=None,
            db_session=db_session,
        )
        rows = db_session.scalars(
            select(SessionAnchorChunk).where(SessionAnchorChunk.session_id == "sess_a")
        ).all()

        assert status["status"] == "failed"
        assert "upstream 500" in status["error"]
        assert rows == []


def test_vectorize_resume_skips_mode_d() -> None:
    status = vectorize_resume(
        session_id="sess_b",
        resume_revision_id="rev_short",
        source_artifact_id="artifact_short",
        raw_text="too short.",
        parsed=None,
    )

    assert status["status"] == "skipped"
    assert status["mode"] == "D"
    assert status["skipped_reason"] == "mode_d_minimal_resume"


def test_vectorize_self_intro_skips_short_answer() -> None:
    session_local = _db()
    with session_local() as db_session:
        status = vectorize_self_intro_anchor_cards(
            session_id="sess_a",
            self_intro_revision_id="intro_rev_1",
            turn_idx=0,
            sanitized_answer="too short",
            anchor_cards=[],
            db_session=db_session,
        )

        assert status["status"] == "skipped"
        assert status["skipped_reason"] == "skipped_short"


def test_vectorize_self_intro_writes_anchor_cards(monkeypatch) -> None:
    session_local = _db()
    with session_local() as db_session:
        monkeypatch.setattr(
            "app.services.session_anchor_vectorize.embed_chunks",
            lambda texts, **_kw: [[0.2] * 1536 for _ in texts],
        )

        status = vectorize_self_intro_anchor_cards(
            session_id="sess_a",
            self_intro_revision_id="intro_rev_1",
            turn_idx=0,
            sanitized_answer=LONG_SELF_INTRO_TEXT,
            anchor_cards=[
                {
                    "kind": "project",
                    "title": "Redis coupon guard",
                    "text": "I led the Redis Lua atomic deduction work under peak traffic.",
                    "tech_keywords": ["Redis", "Lua"],
                }
            ],
            db_session=db_session,
        )
        rows = db_session.scalars(
            select(SessionAnchorChunk).where(SessionAnchorChunk.session_id == "sess_a")
        ).all()

        assert status["status"] == "ready"
        assert rows[0].source_type == "self_intro"
        assert rows[0].source_revision_id == "intro_rev_1"
        assert rows[0].source_turn_id == 0
        assert rows[0].tier == "anchor_card"
        assert rows[0].chunker_mode == "SI"


def test_self_intro_fallback_cards_use_profile_summary() -> None:
    cards = build_self_intro_fallback_cards(
        {"summary": "Led Redis coupon consistency.", "emphasized_projects": ["Coupon"]},
        "fallback answer",
    )

    assert cards[0]["kind"] == "claim"
    assert cards[0]["text"] == "Led Redis coupon consistency."
    assert any(card["kind"] == "project" for card in cards)
