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
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
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
        "text": "Redis Lua coupon guard protected atomic deduction.",
        "tech_keywords": ["Redis", "Lua"],
        "dimensions_hint": ["system_design"],
        "chunker_mode": "A",
        "embedding_model_version": current_embedding_model_version(),
        "embedding": _vec(1.0),
        "expires_at": datetime.now(UTC) + timedelta(hours=2),
    }
    data.update(overrides)
    row = SessionAnchorChunk(**data)
    db_session.add(row)
    db_session.flush()
    return row


def test_retrieve_candidate_anchors_returns_resume_and_self_intro_quotas(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "app.services.session_anchor_retriever.embed_query",
        lambda *_args, **_kwargs: _vec(1.0),
    )
    session_local = _db()
    with session_local() as db_session:
        _add_chunk(db_session, chunk_index=0, heading="Coupon consistency")
        _add_chunk(
            db_session,
            chunk_index=1,
            heading="Lua compensation",
            text="Lua script and RabbitMQ compensation kept rollback safe.",
            embedding=_vec(0.99, 0.01),
        )
        _add_chunk(
            db_session,
            chunk_index=2,
            heading="Prometheus alerts",
            text="Prometheus alerts watched Redis hot keys.",
            embedding=_vec(0.98, 0.02),
        )
        _add_chunk(
            db_session,
            source_type="self_intro",
            source_revision_id="intro_rev_1",
            source_artifact_id=None,
            source_turn_id=0,
            chunk_index=0,
            tier="anchor_card",
            section_name="self_intro",
            heading="Opening claim",
            project_name=None,
            text="I mentioned 50w QPS Redis Lua atomic deduction.",
            chunker_mode="SI",
            embedding=_vec(0.97, 0.03),
        )
        _add_chunk(
            db_session,
            source_type="self_intro",
            source_revision_id="intro_rev_1",
            source_artifact_id=None,
            source_turn_id=0,
            chunk_index=1,
            tier="anchor_card",
            section_name="self_intro",
            heading="Lower self intro",
            project_name=None,
            text="I also mentioned team collaboration.",
            chunker_mode="SI",
            embedding=_vec(0.96, 0.04),
        )

        result = retrieve_candidate_anchors(
            session_id="sess_a",
            resume_revision_id="rev_1",
            self_intro_revision_id="intro_rev_1",
            dimension="system_design",
            seed={"id": "seed_1", "scenario_brief": "Redis consistency"},
            target_skills=["Redis", "Lua"],
            rule_anchor={"project_name": "Coupon Guard"},
            self_intro_profile={"emphasized_projects": ["Coupon Guard"]},
            db_session=db_session,
        )

    assert result.fallback_reason is None
    assert [hit.source_type for hit in result.hits].count("resume") == 2
    assert [hit.source_type for hit in result.hits].count("self_intro") == 1
    assert "Redis Lua coupon guard" in result.resume_block
    assert "Lua script and RabbitMQ" in result.resume_block
    assert "Prometheus alerts" not in result.resume_block
    assert "50w QPS" in result.self_intro_block
    assert "team collaboration" not in result.self_intro_block


def test_retrieve_candidate_anchors_isolates_source_revisions(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.session_anchor_retriever.embed_query",
        lambda *_args, **_kwargs: _vec(1.0),
    )
    session_local = _db()
    with session_local() as db_session:
        _add_chunk(db_session, text="current resume row")
        _add_chunk(db_session, source_revision_id="rev_old", text="old resume row")
        _add_chunk(db_session, session_id="sess_b", text="other session row")
        _add_chunk(
            db_session,
            source_type="self_intro",
            source_revision_id="intro_rev_1",
            source_artifact_id=None,
            source_turn_id=0,
            tier="anchor_card",
            section_name="self_intro",
            heading="current intro",
            project_name=None,
            text="current self intro row",
            chunker_mode="SI",
        )
        _add_chunk(
            db_session,
            source_type="self_intro",
            source_revision_id="intro_old",
            source_artifact_id=None,
            source_turn_id=0,
            tier="anchor_card",
            section_name="self_intro",
            heading="old intro",
            project_name=None,
            text="old self intro row",
            chunker_mode="SI",
        )

        result = retrieve_candidate_anchors(
            session_id="sess_a",
            resume_revision_id="rev_1",
            self_intro_revision_id="intro_rev_1",
            dimension="system_design",
            seed={"scenario_brief": "Redis consistency"},
            target_skills=[],
            rule_anchor=None,
            self_intro_profile={},
            db_session=db_session,
        )

    rendered = f"{result.resume_block}\n{result.self_intro_block}"
    assert "current resume row" in rendered
    assert "current self intro row" in rendered
    assert "old resume row" not in rendered
    assert "old self intro row" not in rendered
    assert "other session row" not in rendered


def test_retrieve_candidate_anchors_uses_embedding_override_version(monkeypatch) -> None:
    embedding_override = {
        "provider": "qwen",
        "api_key": "sk-qwen-embedding",
        "model": "text-embedding-v4",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "dimensions": 1536,
    }
    captured: dict[str, Any] = {}

    def fake_embed_query(text: str, **kwargs: Any) -> list[float]:
        captured["kwargs"] = kwargs
        return _vec(1.0)

    monkeypatch.setattr(
        "app.services.session_anchor_retriever.embed_query",
        fake_embed_query,
    )
    session_local = _db()
    with session_local() as db_session:
        _add_chunk(
            db_session,
            embedding_model_version="qwen:text-embedding-v4:1536@v1",
            text="qwen embedded current resume row",
        )
        _add_chunk(
            db_session,
            embedding_model_version=current_embedding_model_version(),
            text="server default row should not match",
        )

        result = retrieve_candidate_anchors(
            session_id="sess_a",
            resume_revision_id="rev_1",
            self_intro_revision_id=None,
            dimension="system_design",
            seed={"scenario_brief": "Redis consistency"},
            target_skills=[],
            rule_anchor=None,
            self_intro_profile={},
            db_session=db_session,
            embedding_override=embedding_override,
        )

    assert result.fallback_reason is None
    assert "qwen embedded current resume row" in result.resume_block
    assert "server default row should not match" not in result.resume_block
    assert captured["kwargs"]["embedding_override"] == embedding_override
    assert captured["kwargs"]["timeout_ms"] == 3000


def test_retrieve_candidate_anchors_uses_self_intro_terms_in_query(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    def fake_embed_query(text: str, **kwargs: Any) -> list[float]:
        captured["text"] = text
        captured["cache_key"] = kwargs.get("cache_key")
        return _vec(1.0)

    monkeypatch.setattr(
        "app.services.session_anchor_retriever.embed_query",
        fake_embed_query,
    )
    session_local = _db()
    with session_local() as db_session:
        _add_chunk(db_session)

        retrieve_candidate_anchors(
            session_id="sess_a",
            resume_revision_id="rev_1",
            self_intro_revision_id=None,
            dimension="system_design",
            seed={"id": "seed_coupon", "scenario_brief": "Redis consistency"},
            target_skills=["Redis"],
            rule_anchor=None,
            self_intro_profile={
                "emphasized_projects": ["coupon guard"],
                "emphasized_skills": ["Lua"],
                "preferred_focus": ["rollback safety"],
            },
            db_session=db_session,
        )

    assert "coupon guard" in captured["text"]
    assert "rollback safety" in captured["text"]
    assert "seed_coupon" in captured["cache_key"]


def test_retrieve_candidate_anchors_query_is_anchor_centric(monkeypatch) -> None:
    captured: dict[str, Any] = {"texts": []}

    def fake_embed_query(text: str, **kwargs: Any) -> list[float]:
        captured["texts"].append(text)
        captured["cache_key"] = kwargs.get("cache_key")
        return _vec(0.0, 1.0) if "Checkout Recovery" in text else _vec(1.0)

    monkeypatch.setattr(
        "app.services.session_anchor_retriever.embed_query",
        fake_embed_query,
    )
    session_local = _db()
    with session_local() as db_session:
        _add_chunk(db_session)

        result = retrieve_candidate_anchors(
            session_id="sess_a",
            resume_revision_id="rev_1",
            self_intro_revision_id=None,
            dimension="system_design",
            seed={"id": "seed_tradeoff", "scenario_brief": "generic tradeoff"},
            target_skills=["Java"],
            rule_anchor={
                "anchor_key": "focus-payment-consistency",
                "label": "Coupon deduction consistency",
                "project_name": "Coupon Guard",
                "skills": ["Redis", "Lua"],
                "tech_stack": ["Spring Boot"],
                "question_anchors": ["rollback safety", "hot key protection"],
                "dimensions": ["system_design", "technical_depth"],
            },
            self_intro_profile={
                "emphasized_projects": ["Checkout Recovery"],
                "emphasized_skills": ["compensation"],
                "preferred_focus": ["candidate priority"],
            },
            db_session=db_session,
        )

    artifact = result.as_artifact(mode="primary")
    assert len(captured["texts"]) == 2
    anchor_text, boost_text = captured["texts"]
    assert anchor_text.startswith("Coupon deduction consistency Coupon Guard")
    assert "Redis Lua Spring Boot" in anchor_text
    assert "rollback safety" in anchor_text
    assert "technical_depth" in anchor_text
    assert "payment consistency" in anchor_text
    assert "Checkout Recovery" not in anchor_text
    assert boost_text.startswith("Coupon deduction consistency Coupon Guard")
    assert "Checkout Recovery" in boost_text
    assert "generic tradeoff" not in boost_text
    assert artifact["anchor_query_text"] == anchor_text
    assert artifact["boost_query_text"] == boost_text
    assert artifact["constraint_query_text"] == "system_design Java generic tradeoff"
    assert artifact["anchor_terms"][:2] == [
        "Coupon deduction consistency",
        "Coupon Guard",
    ]
    assert "payment consistency" in artifact["anchor_terms"]
    assert artifact["boost_terms"] == [
        "Checkout Recovery",
        "compensation",
        "candidate priority",
    ]
    assert artifact["constraint_terms"] == [
        "system_design",
        "Java",
        "generic tradeoff",
    ]
    assert artifact["query_terms"] == (
        artifact["anchor_terms"]
        + artifact["boost_terms"]
        + artifact["constraint_terms"]
    )
    assert artifact["query_text"] == " ".join(artifact["query_terms"])


def test_retrieve_candidate_anchors_merges_queries_and_reranks_with_constraints(
    monkeypatch,
) -> None:
    captured_texts: list[str] = []

    def fake_embed_query(text: str, **_kwargs: Any) -> list[float]:
        captured_texts.append(text)
        return _vec(0.0, 1.0) if "Checkout Recovery" in text else _vec(1.0)

    monkeypatch.setattr(
        "app.services.session_anchor_retriever.embed_query",
        fake_embed_query,
    )
    session_local = _db()
    with session_local() as db_session:
        _add_chunk(
            db_session,
            chunk_index=0,
            heading="Anchor exact",
            text="Coupon consistency architecture overview.",
            tech_keywords=[],
            dimensions_hint=[],
            embedding=_vec(1.0, 0.0),
        )
        _add_chunk(
            db_session,
            chunk_index=1,
            heading="Boost exact",
            text="Checkout Recovery compensation work.",
            tech_keywords=[],
            dimensions_hint=[],
            embedding=_vec(0.0, 1.0),
        )
        _add_chunk(
            db_session,
            chunk_index=2,
            heading="Constraint rich",
            text="Redis Lua rollback safety in system design.",
            tech_keywords=["Redis", "Lua"],
            dimensions_hint=["system_design"],
            embedding=_vec(0.8, 0.6),
        )

        result = retrieve_candidate_anchors(
            session_id="sess_a",
            resume_revision_id="rev_1",
            self_intro_revision_id=None,
            dimension="system_design",
            seed={"scenario_brief": "rollback safety"},
            target_skills=["Redis", "Lua"],
            rule_anchor={
                "label": "Coupon deduction consistency",
                "project_name": "Coupon Guard",
            },
            self_intro_profile={
                "emphasized_projects": ["Checkout Recovery"],
            },
            db_session=db_session,
        )

    artifact = result.as_artifact(mode="primary")
    assert len(captured_texts) == 2
    assert artifact["ranking_weights"] == {
        "anchor": 0.7,
        "boost": 0.2,
        "constraint": 0.1,
    }
    resume_hits = [hit for hit in artifact["hits"] if hit["source_type"] == "resume"]
    assert [hit["heading"] for hit in resume_hits[:2]] == [
        "Constraint rich",
        "Anchor exact",
    ]
    rich = resume_hits[0]
    assert rich["anchor_score"] > 0
    assert rich["boost_score"] > 0
    assert rich["constraint_match"] == 1.0
    assert rich["matched_target_skills"] == ["redis", "lua"]
    assert rich["matched_dimensions"] == ["system_design"]
    assert rich["matched_seed_terms"] == ["rollback", "safety"]
    assert rich["final_score"] == rich["score"]
    assert rich["raw_score"] == max(rich["anchor_score"], rich["boost_score"])


def test_retrieve_candidate_anchors_skips_boost_embedding_without_boost_terms(
    monkeypatch,
) -> None:
    captured_texts: list[str] = []

    def fake_embed_query(text: str, **_kwargs: Any) -> list[float]:
        captured_texts.append(text)
        return _vec(1.0)

    monkeypatch.setattr(
        "app.services.session_anchor_retriever.embed_query",
        fake_embed_query,
    )
    session_local = _db()
    with session_local() as db_session:
        _add_chunk(db_session)

        result = retrieve_candidate_anchors(
            session_id="sess_a",
            resume_revision_id="rev_1",
            self_intro_revision_id=None,
            dimension="system_design",
            seed=None,
            target_skills=[],
            rule_anchor={
                "label": "Coupon deduction consistency",
                "project_name": "Coupon Guard",
            },
            self_intro_profile={},
            db_session=db_session,
        )

    artifact = result.as_artifact(mode="primary")
    assert captured_texts == ["Coupon deduction consistency Coupon Guard"]
    assert artifact["boost_query_text"] == ""
    assert artifact["boost_fallback_reason"] is None


def test_retrieve_candidate_anchors_boost_timeout_keeps_anchor_hits(
    monkeypatch,
) -> None:
    captured_texts: list[str] = []

    def fake_embed_query(text: str, **_kwargs: Any) -> list[float] | None:
        captured_texts.append(text)
        if "Checkout Recovery" in text:
            return None
        return _vec(1.0)

    monkeypatch.setattr(
        "app.services.session_anchor_retriever.embed_query",
        fake_embed_query,
    )
    session_local = _db()
    with session_local() as db_session:
        _add_chunk(db_session, text="Redis Lua coupon guard anchor row.")

        result = retrieve_candidate_anchors(
            session_id="sess_a",
            resume_revision_id="rev_1",
            self_intro_revision_id=None,
            dimension="system_design",
            seed=None,
            target_skills=[],
            rule_anchor={
                "label": "Coupon deduction consistency",
                "project_name": "Coupon Guard",
            },
            self_intro_profile={
                "emphasized_projects": ["Checkout Recovery"],
            },
            db_session=db_session,
        )

    artifact = result.as_artifact(mode="primary")
    assert len(captured_texts) == 2
    assert result.fallback_reason is None
    assert "Redis Lua coupon guard" in result.resume_block
    assert artifact["boost_fallback_reason"] == "timeout"


def test_retrieve_candidate_anchors_ignores_hash_anchor_key_in_query(
    monkeypatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_embed_query(text: str, **_kwargs: Any) -> list[float]:
        captured["text"] = text
        return _vec(1.0)

    monkeypatch.setattr(
        "app.services.session_anchor_retriever.embed_query",
        fake_embed_query,
    )
    session_local = _db()
    with session_local() as db_session:
        _add_chunk(db_session)

        result = retrieve_candidate_anchors(
            session_id="sess_a",
            resume_revision_id="rev_1",
            self_intro_revision_id=None,
            dimension="system_design",
            seed=None,
            target_skills=[],
            rule_anchor={
                "anchor_key": "focus-proj-coupon-a1b2c3d4e5f6",
                "label": "Coupon deduction consistency",
                "project_name": "Coupon Guard",
            },
            self_intro_profile={},
            db_session=db_session,
        )

    artifact = result.as_artifact(mode="primary")
    assert "a1b2c3d4e5f6" not in captured["text"]
    assert "proj coupon" not in captured["text"]
    assert "a1b2c3d4e5f6" not in " ".join(artifact["anchor_terms"])


def test_retrieve_candidate_anchors_returns_timeout_fallback(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.session_anchor_retriever.embed_query",
        lambda *_args, **_kwargs: None,
    )
    session_local = _db()
    with session_local() as db_session:
        _add_chunk(db_session)

        result = retrieve_candidate_anchors(
            session_id="sess_a",
            resume_revision_id="rev_1",
            self_intro_revision_id="intro_rev_1",
            dimension="system_design",
            seed={"scenario_brief": "Redis Lua consistency"},
            target_skills=["Redis", "Lua"],
            rule_anchor=None,
            self_intro_profile={},
            db_session=db_session,
        )

    assert result.fallback_reason == "timeout"
    assert result.resume_block == ""
    assert result.self_intro_block == ""
