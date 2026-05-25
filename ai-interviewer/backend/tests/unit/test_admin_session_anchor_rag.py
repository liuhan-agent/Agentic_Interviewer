from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.v1 import admin as admin_api
from app.models.generation_trace import GenerationTrace
from app.models.interview_session import InterviewSession
from app.models.resume_anchor_cache import ResumeAnchorCacheChunk
from app.models.resume_parse_artifact import ResumeParseArtifact
from app.models.session_anchor import SessionAnchorChunk
from app.services.resume_embedding import current_embedding_model_version


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(admin_api.router)
    return TestClient(app)


def _settings(*, token: str | None = None, open_admin: bool = True) -> Any:
    return SimpleNamespace(
        api_token=token,
        allow_open_admin=open_admin,
        app_env="dev",
        resume_rag_mode="shadow",
    )


@contextmanager
def _isolated_db(monkeypatch: pytest.MonkeyPatch):
    engine = create_engine(
        "sqlite://",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    for table in (
        SessionAnchorChunk.__table__,
        ResumeAnchorCacheChunk.__table__,
        ResumeParseArtifact.__table__,
        InterviewSession.__table__,
        GenerationTrace.__table__,
    ):
        table.create(engine, checkfirst=True)

    testing_session_local = sessionmaker(
        bind=engine,
        expire_on_commit=False,
        autoflush=False,
    )

    @contextmanager
    def get_session():
        sess = testing_session_local()
        try:
            yield sess
            sess.commit()
        except Exception:
            sess.rollback()
            raise
        finally:
            sess.close()

    monkeypatch.setattr(admin_api, "get_session", get_session, raising=False)
    yield testing_session_local


def _vec(first: float = 1.0) -> list[float]:
    return [first, *([0.0] * 1535)]


def _chunk(**overrides: Any) -> SessionAnchorChunk:
    data = {
        "session_id": "sess_a",
        "source_type": "resume",
        "source_revision_id": "rev_1",
        "source_artifact_id": "artifact_a",
        "source_turn_id": None,
        "chunk_index": 0,
        "tier": "highlight",
        "section_name": "Projects",
        "heading": "Coupon consistency",
        "project_name": "Coupon Guard",
        "text": "Redis Lua coupon guard.",
        "tech_keywords": ["Redis", "Lua"],
        "dimensions_hint": ["system_design"],
        "chunker_mode": "A",
        "embedding_model_version": current_embedding_model_version(),
        "embedding": _vec(),
        "expires_at": datetime.now(UTC) + timedelta(days=1),
        "source_cache_key": None,
    }
    data.update(overrides)
    return SessionAnchorChunk(**data)


def _session(**overrides: Any) -> InterviewSession:
    now = datetime.now(UTC)
    data = {
        "session_id": "sess_a",
        "trace_id": "trace-anchor",
        "candidate_name": "Ada",
        "job_title": "Backend",
        "job_level": "senior",
        "mode": "mixed",
        "status": "running",
        "created_at": now,
        "updated_at": now,
    }
    data.update(overrides)
    return InterviewSession(**data)


def _trace(
    *,
    payload: dict[str, Any],
    created_at: datetime | None = None,
    session_id: str = "sess_a",
    trace_id: str = "trace-anchor",
    turn_idx: int = 0,
) -> GenerationTrace:
    return GenerationTrace(
        trace_id=trace_id,
        session_id=session_id,
        turn_idx=turn_idx,
        node="ask_question",
        dimension="system_design",
        action_id=None,
        policy_id=None,
        context_key=None,
        policy_context_keys=None,
        score=None,
        passed=None,
        immediate_reward=None,
        delayed_reward=None,
        applied_to_bandit=False,
        immediate_reward_applied=False,
        state_snapshot={"payload": payload},
        question="How would you design coupon consistency?",
        answer=None,
        evaluation=None,
        langsmith_run_id=None,
        created_at=created_at or datetime.now(UTC),
    )


def test_admin_session_anchor_summary_requires_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(admin_api, "get_settings", lambda: _settings(token="secret"))

    resp = _client().get("/admin/session-anchors/summary")

    assert resp.status_code == 401


def test_admin_session_anchor_summary_returns_source_and_mode_counts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(admin_api, "get_settings", lambda: _settings())
    with _isolated_db(monkeypatch) as testing_session_local:
        with testing_session_local() as sess:
            sess.add_all(
                [
                    _chunk(session_id="sess_a", chunker_mode="A"),
                    _chunk(session_id="sess_a", chunker_mode="A", chunk_index=1),
                    _chunk(session_id="sess_b", chunker_mode="B"),
                    _chunk(
                        session_id="sess_a",
                        source_type="self_intro",
                        source_revision_id="intro_rev_1",
                        source_artifact_id=None,
                        source_turn_id=0,
                        tier="anchor_card",
                        chunker_mode="SI",
                        project_name=None,
                    ),
                ]
            )
            sess.commit()

        resp = _client().get("/admin/session-anchors/summary")

    assert resp.status_code == 200
    body = resp.json()
    assert body["resume_rag_mode"] == "shadow"
    assert body["total_chunks"] == 4
    assert body["total_sessions"] == 2
    assert body["by_source_type"]["resume"] == {"chunks": 3, "sessions": 2}
    assert body["by_source_type"]["self_intro"] == {"chunks": 1, "sessions": 1}
    assert body["by_mode"]["A"]["chunks"] == 2
    assert body["by_mode"]["SI"]["chunks"] == 1
    assert body["by_mode"]["A"]["avg_chunks_per_session"] == 2.0
    assert body["embedding_model_version"] == current_embedding_model_version()


def test_admin_session_anchor_metrics_groups_hits_and_fallbacks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(admin_api, "get_settings", lambda: _settings())
    with _isolated_db(monkeypatch) as testing_session_local:
        with testing_session_local() as sess:
            sess.add_all(
                [
                    _trace(
                        payload={
                            "selection_artifacts": {
                                "candidate_anchor_rag": {
                                    "status": "primary",
                                    "fallback_reason": None,
                                    "latency_ms": 100,
                                    "hits": [
                                        {
                                            "source_type": "resume",
                                            "chunker_mode": "A",
                                            "score": 0.91,
                                        },
                                        {
                                            "source_type": "self_intro",
                                            "chunker_mode": "SI",
                                            "score": 0.88,
                                        },
                                    ],
                                }
                            }
                        }
                    ),
                    _trace(
                        payload={
                            "selection_artifacts": {
                                "candidate_anchor_rag": {
                                    "status": "shadow",
                                    "fallback_reason": "low_score",
                                    "latency_ms": 250,
                                    "hits": [],
                                }
                            }
                        }
                    ),
                    _trace(
                        payload={
                            "selection_artifacts": {
                                "candidate_anchor_rag": {"status": "off"}
                            }
                        }
                    ),
                    _trace(
                        payload={},
                        created_at=datetime.now(UTC) - timedelta(days=2),
                    ),
                ]
            )
            sess.commit()

        resp = _client().get("/admin/session-anchors/metrics")

    assert resp.status_code == 200
    body = resp.json()
    assert body["window_hours"] == 24
    assert body["by_source_type"]["resume"]["total_retrievals"] == 2
    assert body["by_source_type"]["resume"]["hit_count"] == 1
    assert body["by_source_type"]["resume"]["hit_rate"] == 0.5
    assert body["by_source_type"]["resume"]["fallback_distribution"]["low_score"] == 1
    assert body["by_source_type"]["resume"]["latency_ms"] == {"p50": 100, "p99": 250}
    assert body["by_source_type"]["self_intro"]["hit_count"] == 1
    assert body["by_mode"]["A"]["hit_count"] == 1
    assert body["by_mode"]["SI"]["hit_count"] == 1
    assert body["by_mode"]["unknown"]["fallback_distribution"]["low_score"] == 1


def test_admin_session_anchor_sessions_returns_recent_session_level_rollup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(admin_api, "get_settings", lambda: _settings())
    now = datetime.now(UTC)
    with _isolated_db(monkeypatch) as testing_session_local:
        with testing_session_local() as sess:
            sess.add_all(
                [
                    _session(
                        session_id="sess_hit",
                        trace_id="trace-hit",
                        candidate_name="Ada",
                        job_title="Backend Engineer",
                        status="completed",
                        created_at=now - timedelta(hours=2),
                        updated_at=now - timedelta(hours=1),
                    ),
                    _session(
                        session_id="sess_off",
                        trace_id="trace-off",
                        candidate_name="Grace",
                        job_title="ML Engineer",
                        status="running",
                        created_at=now - timedelta(hours=3),
                        updated_at=now - timedelta(hours=2),
                    ),
                    _session(
                        session_id="sess_empty",
                        trace_id="trace-empty",
                        candidate_name="Lin",
                        job_title="Frontend Engineer",
                        status="errored",
                        created_at=now - timedelta(hours=4),
                        updated_at=now - timedelta(hours=3),
                    ),
                    _session(
                        session_id="sess_notrace",
                        trace_id="trace-notrace",
                        candidate_name="NoTrace",
                        job_title="Product Engineer",
                        status="running",
                        created_at=now - timedelta(hours=5),
                        updated_at=now - timedelta(hours=4),
                    ),
                    _session(
                        session_id="sess_trace_mode",
                        trace_id="trace-trace-mode",
                        candidate_name="TraceMode",
                        job_title="Data Engineer",
                        status="completed",
                        created_at=now - timedelta(hours=6),
                        updated_at=now - timedelta(hours=5),
                    ),
                    _session(
                        session_id="sess_old",
                        trace_id="trace-old",
                        candidate_name="Old",
                        job_title="Expired",
                        status="completed",
                        created_at=now - timedelta(days=2),
                        updated_at=now - timedelta(days=2),
                    ),
                    _chunk(session_id="sess_hit", source_type="resume", chunker_mode="A"),
                    _chunk(
                        session_id="sess_hit",
                        source_type="self_intro",
                        source_revision_id="intro_rev",
                        source_artifact_id=None,
                        source_turn_id=0,
                        chunker_mode="SI",
                        tier="anchor_card",
                    ),
                    _trace(
                        session_id="sess_hit",
                        trace_id="trace-hit",
                        turn_idx=0,
                        created_at=now - timedelta(hours=1, minutes=30),
                        payload={
                            "selection_artifacts": {
                                "candidate_anchor_rag": {
                                    "status": "primary",
                                    "fallback_reason": None,
                                    "latency_ms": 100,
                                    "prompt_injected": True,
                                    "prompt_source_counts": {
                                        "resume": 1,
                                        "self_intro": 1,
                                    },
                                    "prompt_block_chars": 128,
                                    "hits": [
                                        {"source_type": "resume", "chunker_mode": "A"},
                                        {"source_type": "self_intro", "chunker_mode": "SI"},
                                    ],
                                }
                            }
                        },
                    ),
                    _trace(
                        session_id="sess_hit",
                        trace_id="trace-hit",
                        turn_idx=1,
                        created_at=now - timedelta(hours=1),
                        payload={
                            "selection_artifacts": {
                                "candidate_anchor_rag": {
                                    "status": "shadow",
                                    "fallback_reason": "low_score",
                                    "latency_ms": 300,
                                    "hits": [],
                                }
                            }
                        },
                    ),
                    _trace(
                        session_id="sess_hit",
                        trace_id="trace-hit",
                        turn_idx=2,
                        created_at=now - timedelta(minutes=50),
                        payload={
                            "selection_artifacts": {
                                "candidate_anchor_rag": {
                                    "status": "shadow",
                                    "fallback_reason": None,
                                    "latency_ms": 200,
                                    "prompt_injected": False,
                                    "hits": [
                                        {"source_type": "resume", "chunker_mode": "A"},
                                    ],
                                }
                            }
                        },
                    ),
                    _trace(
                        session_id="sess_off",
                        trace_id="trace-off",
                        created_at=now - timedelta(hours=2),
                        payload={
                            "selection_artifacts": {
                                "candidate_anchor_rag": {
                                    "status": "off",
                                    "hits": [],
                                }
                            }
                        },
                    ),
                    _trace(
                        session_id="sess_empty",
                        trace_id="trace-empty",
                        created_at=now - timedelta(hours=3),
                        payload={
                            "selection_artifacts": {
                                "candidate_anchor_rag": {
                                    "status": "shadow",
                                    "fallback_reason": "sampled_out",
                                    "latency_ms": 20,
                                    "hits": [],
                                }
                            }
                        },
                    ),
                    _trace(
                        session_id="sess_trace_mode",
                        trace_id="trace-trace-mode",
                        created_at=now - timedelta(hours=5),
                        payload={
                            "selection_artifacts": {
                                "candidate_anchor_rag": {
                                    "status": "primary",
                                    "latency_ms": 80,
                                    "prompt_injected": True,
                                    "prompt_source_counts": {
                                        "resume": 1,
                                        "self_intro": 1,
                                    },
                                    "prompt_block_chars": 96,
                                    "hits": [
                                        {"source_type": "resume", "chunker_mode": "A"},
                                        {"source_type": "self_intro"},
                                    ],
                                }
                            }
                        },
                    ),
                    _trace(
                        session_id="sess_old",
                        trace_id="trace-old",
                        created_at=now - timedelta(days=2),
                        payload={
                            "selection_artifacts": {
                                "candidate_anchor_rag": {
                                    "status": "primary",
                                    "latency_ms": 50,
                                    "hits": [{"source_type": "resume", "chunker_mode": "A"}],
                                }
                            }
                        },
                    ),
                ]
            )
            sess.commit()

        resp = _client().get("/admin/session-anchors/sessions?since=24h")

    assert resp.status_code == 200
    body = resp.json()
    assert body["window"] == "24h"
    assert body["session_count"] == 5
    assert body["summary"]["indexed_sessions"] == 1
    assert body["summary"]["hit_sessions"] == 2
    assert body["summary"]["fallback_sessions"] == 2
    assert [row["session_id"] for row in body["sessions"]] == [
        "sess_hit",
        "sess_off",
        "sess_empty",
        "sess_notrace",
        "sess_trace_mode",
    ]

    hit = body["sessions"][0]
    assert hit["candidate_name"] == "Ada"
    assert hit["job_title"] == "Backend Engineer"
    assert hit["session_status"] == "completed"
    assert hit["has_resume_chunks"] is True
    assert hit["has_self_intro_chunks"] is True
    assert hit["total_chunks"] == 2
    assert hit["chunks_by_source"] == {"resume": 1, "self_intro": 1}
    assert hit["chunker_modes"] == ["A", "SI"]
    assert hit["chunker_modes_by_source"] == {"resume": ["A"], "self_intro": ["SI"]}
    assert hit["retrieval_attempts"] == 3
    assert hit["hit_count"] == 2
    assert hit["hit_rate"] == 0.667
    assert hit["source_hit_counts"] == {"resume": 2, "self_intro": 1}
    assert hit["avg_hits_per_attempt"] == 1.0
    assert hit["prompt_injected_turns"] == 1
    assert hit["retrieved_not_injected_turns"] == 1
    assert hit["prompt_source_counts"] == {"resume": 1, "self_intro": 1}
    assert hit["prompt_block_chars"] == 128
    assert hit["fallback_count"] == 1
    assert hit["fallback_reasons"] == {"low_score": 1}
    assert hit["latency_ms"] == {"p50": 200, "p95": 300, "p99": 300}
    assert hit["rag_status_distribution"] == {"primary": 1, "shadow": 2}
    assert hit["last_trace_at"] is not None

    off = body["sessions"][1]
    assert off["retrieval_attempts"] == 0
    assert off["hit_rate"] == 0.0
    assert off["prompt_injected_turns"] == 0
    assert off["rag_status_distribution"] == {"off": 1}

    empty = body["sessions"][2]
    assert empty["total_chunks"] == 0
    assert empty["retrieval_attempts"] == 1
    assert empty["fallback_reasons"] == {"sampled_out": 1}

    notrace = body["sessions"][3]
    assert notrace["total_chunks"] == 0
    assert notrace["retrieval_attempts"] == 0
    assert notrace["hit_count"] == 0
    assert notrace["fallback_count"] == 0
    assert notrace["prompt_injected_turns"] == 0
    assert notrace["retrieved_not_injected_turns"] == 0
    assert notrace["rag_status_distribution"] == {}
    assert notrace["last_trace_at"] is None

    trace_mode = body["sessions"][4]
    assert trace_mode["total_chunks"] == 0
    assert trace_mode["chunker_modes"] == ["A", "SI"]
    assert trace_mode["chunker_modes_by_source"] == {"resume": ["A"], "self_intro": ["SI"]}
    assert trace_mode["has_resume_chunks"] is False
    assert trace_mode["source_hit_counts"] == {"resume": 1, "self_intro": 1}
    assert trace_mode["prompt_injected_turns"] == 1
    assert trace_mode["prompt_source_counts"] == {"resume": 1, "self_intro": 1}
    assert trace_mode["prompt_block_chars"] == 96


def test_admin_session_anchor_sessions_uses_setup_snapshot_after_chunk_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(admin_api, "get_settings", lambda: _settings())
    now = datetime.now(UTC)
    with _isolated_db(monkeypatch) as testing_session_local:
        with testing_session_local() as sess:
            sess.add(
                _session(
                    session_id="sess_completed_cleanup",
                    trace_id="trace-completed-cleanup",
                    candidate_name="Grace",
                    job_title="Platform Engineer",
                    status="completed",
                    created_at=now - timedelta(hours=2),
                    updated_at=now - timedelta(hours=1),
                    setup_snapshot={
                        "candidate": {
                            "resume_vector_status": {
                                "status": "ready",
                                "source_type": "resume",
                                "mode": "A",
                                "chunk_count": 24,
                                "embedding_model_version": "qwen:text-embedding-v4:1536@v1",
                            }
                        },
                        "self_intro_vector_status": {
                            "status": "ready",
                            "source_type": "self_intro",
                            "mode": "SI",
                            "chunk_count": 5,
                            "embedding_model_version": "qwen:text-embedding-v4:1536@v1",
                        },
                    },
                )
            )
            sess.commit()

        resp = _client().get("/admin/session-anchors/sessions?since=24h")

    assert resp.status_code == 200
    body = resp.json()
    assert body["summary"]["indexed_sessions"] == 1
    row = body["sessions"][0]
    assert row["session_id"] == "sess_completed_cleanup"
    assert row["has_resume_chunks"] is True
    assert row["has_self_intro_chunks"] is True
    assert row["total_chunks"] == 29
    assert row["chunks_by_source"] == {"resume": 24, "self_intro": 5}
    assert row["chunker_modes"] == ["A", "SI"]
    assert row["chunker_modes_by_source"] == {"resume": ["A"], "self_intro": ["SI"]}
    assert row["embedding_model_versions"] == ["qwen:text-embedding-v4:1536@v1"]
    assert row["retrieval_attempts"] == 0


def test_admin_delete_session_anchor_data_wipes_chunks_artifacts_and_scrubs_snapshots(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(admin_api, "get_settings", lambda: _settings())
    now = datetime.now(UTC)
    with _isolated_db(monkeypatch) as testing_session_local:
        with testing_session_local() as sess:
            sess.add_all(
                [
                    _chunk(
                        session_id="sess_a",
                        source_artifact_id="artifact_a",
                        source_cache_key="cache_a",
                    ),
                    _chunk(session_id="sess_b", source_artifact_id="artifact_b"),
                    ResumeAnchorCacheChunk(
                        cache_key="cache_a",
                        embedding_model_version=current_embedding_model_version(),
                        chunk_index=0,
                        tier="highlight",
                        section_name="Projects",
                        heading="Coupon consistency",
                        project_name="Coupon Guard",
                        text="Redis Lua coupon guard.",
                        tech_keywords=["Redis", "Lua"],
                        dimensions_hint=["system_design"],
                        chunker_mode="A",
                        embedding=_vec(),
                        expires_at=now + timedelta(days=7),
                    ),
                    ResumeAnchorCacheChunk(
                        cache_key="cache_b",
                        embedding_model_version=current_embedding_model_version(),
                        chunk_index=0,
                        tier="highlight",
                        section_name="Projects",
                        heading="Other session",
                        project_name="Other",
                        text="Kafka risk platform.",
                        tech_keywords=["Kafka"],
                        dimensions_hint=["system_design"],
                        chunker_mode="A",
                        embedding=_vec(),
                        expires_at=now + timedelta(days=7),
                    ),
                    ResumeParseArtifact(
                        artifact_id="artifact_a",
                        redacted_text="old resume",
                        parsed={},
                        filename="a.pdf",
                        text_sha256="a",
                        created_at=now,
                        expires_at=now + timedelta(hours=1),
                    ),
                    ResumeParseArtifact(
                        artifact_id="artifact_b",
                        redacted_text="other resume",
                        parsed={},
                        filename="b.pdf",
                        text_sha256="b",
                        created_at=now,
                        expires_at=now + timedelta(hours=1),
                    ),
                    InterviewSession(
                        session_id="sess_a",
                        trace_id="trace-anchor",
                        candidate_name="Ada",
                        job_title="Backend",
                        job_level="senior",
                        mode="mixed",
                        status="running",
                        setup_snapshot={
                            "candidate": {
                                "name": "Ada",
                                "resume_source_id": "artifact_a",
                                "resume_parsed": {"summary": "Redis secret"},
                                "resume_vector_status": {
                                    "resume_source_id": "artifact_a",
                                    "status": "ready",
                                },
                            },
                            "resume_vector_status": {
                                "resume_source_id": "artifact_a",
                                "status": "ready",
                            },
                            "job_spec": {"title": "Backend"},
                        },
                        current_question={
                            "question": "Q",
                            "resume_anchor": {"project_name": "Coupon Guard"},
                            "selection_artifacts": {
                                "candidate_anchor_rag": {"hits": [{"id": 1}]},
                                "rule_seed": {"id": "seed_1"},
                            },
                        },
                        created_at=now,
                        updated_at=now,
                    ),
                    GenerationTrace(
                        trace_id="trace-anchor",
                        session_id="sess_a",
                        turn_idx=0,
                        node="ask_question",
                        state_snapshot={
                            "payload": {
                                "selection_artifacts": {
                                    "candidate_anchor_rag": {"hits": [{"id": 1}]},
                                    "rule_seed": {"id": "seed_1"},
                                },
                                "resume_rag_block": "[resume] Redis secret",
                            },
                            "state": {
                                "candidate": {
                                    "resume_parsed": {"summary": "Redis secret"},
                                    "resume_source_id": "artifact_a",
                                },
                                "self_intro_profile": {"summary": "intro secret"},
                            },
                        },
                    ),
                ]
            )
            sess.commit()

        resp = _client().delete("/admin/sessions/sess_a/anchor-data")

        with testing_session_local() as sess:
            remaining_chunks = sess.scalars(select(SessionAnchorChunk)).all()
            remaining_cache = sess.scalars(select(ResumeAnchorCacheChunk)).all()
            session_row = sess.get(InterviewSession, "sess_a")
            trace_row = sess.scalars(select(GenerationTrace)).one()
            artifact_a = sess.get(ResumeParseArtifact, "artifact_a")
            artifact_b = sess.get(ResumeParseArtifact, "artifact_b")

    assert resp.status_code == 200
    body = resp.json()
    assert body["chunks_deleted"] == 1
    assert body["resume_artifacts_deleted"] == 1
    assert body["resume_anchor_cache_deleted"] == 1
    assert body["resume_anchor_cache_keys"] == ["cache_a"]
    assert body["sessions_scrubbed"] == 1
    assert body["traces_scrubbed"] == 1
    assert {chunk.session_id for chunk in remaining_chunks} == {"sess_b"}
    assert {chunk.cache_key for chunk in remaining_cache} == {"cache_b"}
    assert artifact_a is None
    assert artifact_b is not None
    assert session_row is not None
    assert "resume_source_id" not in session_row.setup_snapshot["candidate"]
    assert "resume_parsed" not in session_row.setup_snapshot["candidate"]
    assert "resume_vector_status" not in session_row.setup_snapshot
    assert session_row.setup_snapshot["job_spec"] == {"title": "Backend"}
    assert "resume_anchor" not in session_row.current_question
    assert "candidate_anchor_rag" not in session_row.current_question["selection_artifacts"]
    assert session_row.current_question["selection_artifacts"]["rule_seed"] == {
        "id": "seed_1"
    }
    snapshot_text = str(trace_row.state_snapshot)
    assert "Redis secret" not in snapshot_text
    assert "intro secret" not in snapshot_text
    assert "candidate_anchor_rag" not in snapshot_text
    assert "rule_seed" in snapshot_text
