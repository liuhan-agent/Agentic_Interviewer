from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.session_anchor import SessionAnchorChunk
from app.services.resume_embedding import current_embedding_model_version
from app.services.session_anchor_retriever import retrieve_candidate_anchors


def _db():
    engine = create_engine(
        "sqlite://",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SessionAnchorChunk.__table__.create(engine)
    return sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)


def _vec(first: float, second: float = 0.0) -> list[float]:
    return [first, second, *([0.0] * 1534)]


def _add_chunk(db_session, **overrides: Any) -> SessionAnchorChunk:
    data = {
        "session_id": "sess_a",
        "source_type": "resume",
        "source_revision_id": "rev_1",
        "source_artifact_id": "artifact_1",
        "source_turn_id": None,
        "chunk_index": 0,
        "tier": "highlight",
        "section_name": "Projects",
        "heading": "Coupon consistency",
        "project_name": "Coupon Guard",
        "text": "sess_a current Redis Lua chunk.",
        "tech_keywords": ["Redis", "Lua"],
        "dimensions_hint": ["system_design"],
        "chunker_mode": "A",
        "embedding_model_version": current_embedding_model_version(),
        "embedding": _vec(0.98),
        "expires_at": datetime.now(UTC) + timedelta(hours=2),
    }
    data.update(overrides)
    row = SessionAnchorChunk(**data)
    db_session.add(row)
    db_session.flush()
    return row


def _retrieve(db_session):
    return retrieve_candidate_anchors(
        session_id="sess_a",
        resume_revision_id="rev_1",
        self_intro_revision_id="intro_rev_1",
        dimension="system_design",
        seed={"scenario_brief": "Redis Lua consistency"},
        target_skills=["Redis"],
        rule_anchor=None,
        self_intro_profile={},
        db_session=db_session,
    )


def test_cross_session_query_never_returns_other_session_chunks(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.session_anchor_retriever.embed_query",
        lambda *_args, **_kwargs: _vec(1.0),
    )
    session_local = _db()
    with session_local() as db_session:
        _add_chunk(db_session, text="allowed session A row", embedding=_vec(0.97))
        _add_chunk(
            db_session,
            session_id="sess_b",
            text="forbidden higher score session B row",
            embedding=_vec(1.0),
        )

        result = _retrieve(db_session)

    rendered = f"{result.resume_block}\n{result.self_intro_block}"
    assert "allowed session A row" in rendered
    assert "forbidden higher score session B row" not in rendered


def test_source_revision_filter_rejects_same_session_old_revision(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.session_anchor_retriever.embed_query",
        lambda *_args, **_kwargs: _vec(1.0),
    )
    session_local = _db()
    with session_local() as db_session:
        _add_chunk(db_session, text="allowed current revision", embedding=_vec(0.96))
        _add_chunk(
            db_session,
            source_revision_id="rev_old",
            text="forbidden old revision with higher score",
            embedding=_vec(1.0),
        )

        result = _retrieve(db_session)

    assert "allowed current revision" in result.resume_block
    assert "forbidden old revision" not in result.resume_block


def test_session_and_revision_filters_are_both_required(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.session_anchor_retriever.embed_query",
        lambda *_args, **_kwargs: _vec(1.0),
    )
    session_local = _db()
    with session_local() as db_session:
        _add_chunk(db_session, text="allowed exact row", embedding=_vec(0.94))
        _add_chunk(
            db_session,
            session_id="sess_b",
            source_revision_id="rev_1",
            text="forbidden same revision other session",
            embedding=_vec(1.0),
        )
        _add_chunk(
            db_session,
            session_id="sess_a",
            source_revision_id="rev_old",
            text="forbidden same session old revision",
            embedding=_vec(0.99),
        )

        result = _retrieve(db_session)

    rendered = f"{result.resume_block}\n{result.self_intro_block}"
    assert "allowed exact row" in rendered
    assert "forbidden same revision other session" not in rendered
    assert "forbidden same session old revision" not in rendered
