"""Auth + shape tests for the ``/admin/*`` observability router.

``require_admin_token`` gates every admin route. Two axes:
1. Dev default (``api_token`` empty) - routes stay open.
2. Production default (``api_token`` set) - requests without the
   Bearer header get 401, wrong tokens get 403, the correct token
   passes through.

Also regression-covers ``/admin/strategies`` after the ``e.metadata``
AttributeError fix.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api.v1 import admin as admin_api
from app.core import settings as settings_mod


@pytest.fixture()
def client(monkeypatch) -> TestClient:
    """Build a minimal FastAPI app with just the admin router.

    We intentionally avoid ``create_app()`` because it touches the
    DB / schedulers; for auth + shape checks the router alone is
    enough.
    """
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(admin_api.router)
    return TestClient(app)


def _set_token(
    monkeypatch,
    value: str | None,
    *,
    app_env: str = "dev",
    allow_open_admin: bool = False,
) -> None:
    """Swap ``get_settings()`` return value for the duration of a test.

    The stub carries every Settings attribute the admin routes read
    today (``api_token`` for auth + the bandit / decay knobs the
    snapshot serialises). Adding a new snapshot field will surface
    here as an ``AttributeError`` which is intentional - it prevents
    the admin contract from drifting without an updated test.
    """

    env = app_env
    open_admin = allow_open_admin

    class _S:
        app_env = env
        api_token = value
        allow_open_admin = open_admin
        database_url = "sqlite:///:memory:"
        policy_mode = "template"
        thompson_exploration_rate = 0.15
        enable_bandit_decay = False
        bandit_decay_factor = 0.99
        bandit_decay_floor = 1.0
        bandit_decay_interval_days = 1
        langsmith_tracing = True
        langsmith_endpoint = "https://api.smith.langchain.com"
        effective_langsmith_project = "agentic-interviewer-dev"
        resume_rag_embedding_concurrency = 4

    monkeypatch.setattr(admin_api, "get_settings", lambda: _S())
    monkeypatch.setattr(settings_mod, "get_settings", lambda: _S())


def test_admin_rejects_requests_when_dev_token_missing_by_default(client, monkeypatch):
    """Unset token should fail closed unless explicitly allowed."""
    _set_token(monkeypatch, None)

    resp = client.get("/admin/bandit/snapshot")

    assert resp.status_code == 503
    assert "API_TOKEN" in resp.text


def test_admin_open_when_explicitly_allowed(client, monkeypatch):
    """Local demos can opt into open admin with an explicit flag."""
    _set_token(monkeypatch, None, allow_open_admin=True)

    monkeypatch.setattr(
        "app.ml.rl.thompson.get_bandit",
        lambda: _FakeBandit(),
    )
    resp = client.get("/admin/bandit/snapshot")
    assert resp.status_code == 200
    body = resp.json()
    assert body["policy_mode"] in {"template", "legacy"}


def test_admin_bandit_snapshot_includes_persisted_posterior_summary(
    client,
    monkeypatch,
):
    _set_token(monkeypatch, None, allow_open_admin=True)

    monkeypatch.setattr(
        "app.ml.rl.thompson.get_bandit",
        lambda: _FakeBandit({"senior:system_design::plan_deep_probe": {}}),
    )
    monkeypatch.setattr(
        "app.services.strategy_learning_facts.bandit_posterior_snapshot",
        lambda limit=10: {
            "persisted_prior_count": 2,
            "top_posteriors": [
                {
                    "context_key": "senior:system_design",
                    "action_id": "plan_deep_probe",
                    "alpha": 8.0,
                    "beta": 2.0,
                    "mean_reward": 0.8,
                    "observation_count": 8,
                }
            ],
        },
    )

    resp = client.get("/admin/bandit/snapshot")

    assert resp.status_code == 200
    body = resp.json()
    assert body["memory_prior_count"] == 1
    assert body["persisted_prior_count"] == 2
    assert body["posterior_source"] == "db_aggregate"
    assert body["top_posteriors"][0]["action_id"] == "plan_deep_probe"


def test_admin_rejects_requests_when_prod_token_missing(client, monkeypatch):
    """Production misconfig must not silently expose admin surfaces."""
    _set_token(monkeypatch, None, app_env="prod")

    resp = client.get("/admin/bandit/snapshot")

    assert resp.status_code == 503
    assert "API_TOKEN" in resp.text


def test_admin_requires_bearer_when_token_set(client, monkeypatch):
    """Missing / malformed Authorization header -> 401."""
    _set_token(monkeypatch, "secret-abc")

    resp = client.get("/admin/bandit/snapshot")
    assert resp.status_code == 401
    assert "bearer" in resp.headers.get("www-authenticate", "").lower()

    bad_scheme = client.get(
        "/admin/bandit/snapshot", headers={"Authorization": "Basic xyz"}
    )
    assert bad_scheme.status_code == 401


def test_admin_rejects_wrong_token(client, monkeypatch):
    """Wrong token -> 403 (distinct from 401 so operators can tell)."""
    _set_token(monkeypatch, "secret-abc")

    resp = client.get(
        "/admin/bandit/snapshot", headers={"Authorization": "Bearer wrong"}
    )
    assert resp.status_code == 403


def test_admin_accepts_correct_token(client, monkeypatch):
    """Exact token match -> request flows through."""
    _set_token(monkeypatch, "secret-abc")

    monkeypatch.setattr(
        "app.ml.rl.thompson.get_bandit",
        lambda: _FakeBandit(),
    )

    resp = client.get(
        "/admin/bandit/snapshot",
        headers={"Authorization": "Bearer secret-abc"},
    )
    assert resp.status_code == 200


def test_admin_strategies_route_flattens_entry_fields(client, monkeypatch):
    """Regression: /admin/strategies used to AttributeError on e.metadata."""
    _set_token(monkeypatch, None, allow_open_admin=True)

    from contextlib import contextmanager

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from app.models.base import Base
    from app.models.strategy_memory import StrategyMemory

    engine = create_engine(
        "sqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    with Session() as sess:
        sess.add(
            StrategyMemory(
                id="seed:demo_skill",
                slug="demo_skill",
                name="Demo Skill",
                description="Helps on the demo dimension.",
                source="seed",
                memory_key="seed:demo:mid",
                dimensions=["demo"],
                job_levels=["mid"],
                body_markdown="(body)",
                status="active",
                promotion_stage="seed",
            )
        )
        sess.commit()

    @contextmanager
    def get_session():
        with Session() as sess:
            yield sess
            sess.commit()

    monkeypatch.setattr(admin_api, "get_session", get_session)

    resp = client.get("/admin/strategies")
    assert resp.status_code == 200
    body: dict[str, Any] = resp.json()
    assert body["count"] == 1
    item = body["strategies"][0]
    assert item["name"] == "Demo Skill"
    assert item["dimensions"] == ["demo"]
    assert item["job_levels"] == ["mid"]
    assert item["description"].startswith("Helps on")


def test_admin_sessions_uses_manager_snapshot(client, monkeypatch):
    """The admin route should depend on SessionManager's public API."""
    _set_token(monkeypatch, None, allow_open_admin=True)

    class _FakeManager:
        def snapshot(self) -> list[dict[str, Any]]:
            return [
                {
                    "session_id": "sess-1",
                    "trace_id": "trace-1",
                    "turn_idx": 2,
                    "asked_turn": 1,
                    "has_question": True,
                    "done": False,
                    "cancelled": False,
                    "created_at": "2026-04-25T00:00:00+00:00",
                    "error": None,
                }
            ]

    monkeypatch.setattr(
        "app.services.session_manager.get_session_manager",
        lambda: _FakeManager(),
    )
    monkeypatch.setattr(admin_api, "_latest_langsmith_run_ids", lambda session_ids: {})

    resp = client.get("/admin/sessions")

    assert resp.status_code == 200
    assert resp.json() == {
        "count": 1,
        "langsmith": {
            "tracing_enabled": True,
            "project": "agentic-interviewer-dev",
            "web_url": "https://smith.langchain.com",
        },
        "sessions": [
            {
                "session_id": "sess-1",
                "trace_id": "trace-1",
                "langsmith_run_id": None,
                "turn_idx": 2,
                "asked_turn": 1,
                "has_question": True,
                "done": False,
                "cancelled": False,
                "created_at": "2026-04-25T00:00:00+00:00",
                "error": None,
            }
        ],
    }


def test_admin_sessions_enriches_langsmith_run_id(client, monkeypatch):
    """Active sessions should carry the latest persisted LangSmith run id."""
    _set_token(monkeypatch, None, allow_open_admin=True)

    class _FakeManager:
        def snapshot(self) -> list[dict[str, Any]]:
            return [
                {
                    "session_id": "sess-1",
                    "trace_id": "trace-1",
                    "turn_idx": 2,
                    "asked_turn": 1,
                    "has_question": True,
                    "done": False,
                    "cancelled": False,
                    "created_at": "2026-04-25T00:00:00+00:00",
                    "error": None,
                },
                {
                    "session_id": "sess-2",
                    "trace_id": "trace-2",
                    "turn_idx": 0,
                    "asked_turn": -1,
                    "has_question": False,
                    "done": False,
                    "cancelled": False,
                    "created_at": "2026-04-25T00:01:00+00:00",
                    "error": None,
                },
            ]

    monkeypatch.setattr(
        "app.services.session_manager.get_session_manager",
        lambda: _FakeManager(),
    )
    monkeypatch.setattr(
        admin_api,
        "_latest_langsmith_run_ids",
        lambda session_ids: {"sess-1": "run-eval-42"},
        raising=False,
    )

    resp = client.get("/admin/sessions")

    assert resp.status_code == 200
    body = resp.json()
    assert body["sessions"][0]["langsmith_run_id"] == "run-eval-42"
    assert body["sessions"][1]["langsmith_run_id"] is None


def test_admin_interview_sessions_returns_persisted_history(client, monkeypatch):
    """History route reads DB-backed sessions, not just in-memory handles."""
    _set_token(monkeypatch, None, allow_open_admin=True)

    monkeypatch.setattr(
        admin_api,
        "_recent_interview_sessions",
        lambda limit=20, offset=0, **filters: [
            {
                "session_id": "sess-done",
                "trace_id": "trace-done",
                "candidate_name": "候选人",
                "job_title": "后端工程师",
                "job_level": "senior",
                "mode": "mixed",
                "status": "completed",
                "turn_idx": 5,
                "asked_turn": 4,
                "created_at": "2026-05-01T10:00:00+00:00",
                "updated_at": "2026-05-01T10:20:00+00:00",
                "has_report": True,
                "overall_score": 7.66,
                "overall_verdict": "strong_hire",
                "error_kind": None,
                "retryable": False,
            }
        ],
    )

    resp = client.get("/admin/interview-sessions")

    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 1
    item = body["sessions"][0]
    assert item["session_id"] == "sess-done"
    assert item["has_report"] is True
    assert item["overall_score"] == 7.66
    assert item["overall_verdict"] == "strong_hire"


def test_admin_interview_sessions_reports_total_count(client, monkeypatch):
    """History count distinguishes returned page size from DB total rows."""
    _set_token(monkeypatch, None, allow_open_admin=True)

    monkeypatch.setattr(
        admin_api,
        "_recent_interview_sessions",
        lambda limit=20, offset=0, **filters: [
            {
                "session_id": "sess-page",
                "status": "completed",
                "has_report": True,
            }
        ],
    )
    monkeypatch.setattr(
        admin_api,
        "_interview_session_total_count",
        lambda **filters: 23,
        raising=False,
    )

    resp = client.get("/admin/interview-sessions")

    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 1
    assert body["total_count"] == 23
    assert body["limit"] == 20


def test_admin_interview_sessions_supports_offset_pagination(
    client,
    monkeypatch,
):
    """History route pages DB rows instead of hard-capping at the first 20."""
    _set_token(monkeypatch, None, allow_open_admin=True)
    seen: dict[str, int] = {}

    def recent(
        limit: int = 20,
        offset: int = 0,
        **filters: Any,
    ) -> list[dict[str, Any]]:
        seen["limit"] = limit
        seen["offset"] = offset
        return [
            {
                "session_id": "sess-page-3",
                "status": "completed",
                "has_report": True,
            }
        ]

    monkeypatch.setattr(admin_api, "_recent_interview_sessions", recent)
    monkeypatch.setattr(
        admin_api,
        "_interview_session_total_count",
        lambda **filters: 43,
        raising=False,
    )

    resp = client.get("/admin/interview-sessions?limit=10&offset=20")

    assert resp.status_code == 200
    body = resp.json()
    assert seen == {"limit": 10, "offset": 20}
    assert body["count"] == 1
    assert body["total_count"] == 43
    assert body["limit"] == 10
    assert body["offset"] == 20


def test_admin_interview_sessions_total_count_covers_returned_page(
    client,
    monkeypatch,
):
    """Total count never reports less than the page already reached."""
    _set_token(monkeypatch, None, allow_open_admin=True)

    monkeypatch.setattr(
        admin_api,
        "_recent_interview_sessions",
        lambda limit=20, offset=0, **filters: [
            {
                "session_id": "sess-page-2-item-1",
                "status": "completed",
                "has_report": True,
            },
            {
                "session_id": "sess-page-2-item-2",
                "status": "completed",
                "has_report": True,
            },
        ],
    )
    monkeypatch.setattr(
        admin_api,
        "_interview_session_total_count",
        lambda **filters: 0,
        raising=False,
    )

    resp = client.get("/admin/interview-sessions?limit=20&offset=20")

    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 2
    assert body["total_count"] == 22
    assert body["offset"] == 20


def test_admin_interview_sessions_passes_filter_query_params(client, monkeypatch):
    """History route filters are part of the server-side pagination query."""
    _set_token(monkeypatch, None, allow_open_admin=True)
    seen_recent: dict[str, Any] = {}
    seen_count: dict[str, Any] = {}

    def recent(limit: int = 20, offset: int = 0, **filters: Any) -> list[dict[str, Any]]:
        seen_recent.update({"limit": limit, "offset": offset, **filters})
        return [
            {
                "session_id": "sess-filtered",
                "status": "completed",
                "has_report": True,
                "trace_health": "complete",
            }
        ]

    def count(**filters: Any) -> int:
        seen_count.update(filters)
        return 1

    monkeypatch.setattr(admin_api, "_recent_interview_sessions", recent)
    monkeypatch.setattr(admin_api, "_interview_session_total_count", count, raising=False)

    resp = client.get(
        "/admin/interview-sessions"
        "?limit=10&offset=20&status=completed&trace_health=complete"
        "&has_report=true&q=后端&since=7d"
    )

    assert resp.status_code == 200
    assert seen_recent == {
        "limit": 10,
        "offset": 20,
        "status_filter": "completed",
        "trace_health_filter": "complete",
        "has_report_filter": True,
        "q": "后端",
        "since": "7d",
    }
    assert seen_count == {
        "status_filter": "completed",
        "trace_health_filter": "complete",
        "has_report_filter": True,
        "q": "后端",
        "since": "7d",
    }
    body = resp.json()
    assert body["filters"] == {
        "status": "completed",
        "trace_health": "complete",
        "has_report": True,
        "q": "后端",
        "since": "7d",
    }


def test_admin_interview_sessions_filters_database_before_pagination(
    client,
    monkeypatch,
):
    """Search/status/report/trace filters apply to the full DB result set."""
    _set_token(monkeypatch, None, allow_open_admin=True)

    from contextlib import contextmanager

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    import app.models as models_mod
    from app.models import GenerationTrace, InterviewSession
    from app.models.base import Base

    engine = create_engine(
        "sqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    now = datetime.now(UTC)
    with Session() as sess:
        sess.add_all(
            [
                InterviewSession(
                    session_id="sess-complete",
                    trace_id="trace-complete",
                    candidate_name="Alice",
                    job_title="后端工程师",
                    job_level="senior",
                    mode="mixed",
                    status="completed",
                    final_report={"overall_score": 8},
                    created_at=now - timedelta(days=2),
                ),
                InterviewSession(
                    session_id="sess-partial",
                    trace_id="trace-partial",
                    candidate_name="Alice",
                    job_title="后端工程师",
                    job_level="senior",
                    mode="mixed",
                    status="completed",
                    final_report={"overall_score": 6},
                    created_at=now - timedelta(days=1),
                ),
                InterviewSession(
                    session_id="sess-missing-report",
                    trace_id="trace-missing-report",
                    candidate_name="Alice",
                    job_title="后端工程师",
                    job_level="senior",
                    mode="mixed",
                    status="completed",
                    final_report=None,
                    created_at=now - timedelta(days=1),
                ),
                InterviewSession(
                    session_id="sess-old",
                    trace_id="trace-old",
                    candidate_name="Alice",
                    job_title="后端工程师",
                    job_level="senior",
                    mode="mixed",
                    status="completed",
                    final_report={"overall_score": 7},
                    created_at=now - timedelta(days=20),
                ),
            ]
        )
        sess.add_all(
            [
                GenerationTrace(
                    trace_id="trace-complete",
                    session_id="sess-complete",
                    turn_idx=1,
                    node="evaluator",
                ),
                GenerationTrace(
                    trace_id="trace-complete",
                    session_id="sess-complete",
                    turn_idx=1,
                    node="reward_update",
                ),
                GenerationTrace(
                    trace_id="trace-partial",
                    session_id="sess-partial",
                    turn_idx=1,
                    node="ask_question",
                ),
                GenerationTrace(
                    trace_id="trace-old",
                    session_id="sess-old",
                    turn_idx=1,
                    node="evaluator",
                ),
                GenerationTrace(
                    trace_id="trace-old",
                    session_id="sess-old",
                    turn_idx=1,
                    node="reward_update",
                ),
            ]
        )
        sess.commit()

    @contextmanager
    def get_session():
        with Session() as sess:
            yield sess
            sess.commit()

    monkeypatch.setattr(models_mod, "get_session", get_session)

    resp = client.get(
        "/admin/interview-sessions"
        "?status=completed&trace_health=complete&has_report=true&q=后端&since=7d"
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["total_count"] == 1
    assert [item["session_id"] for item in body["sessions"]] == ["sess-complete"]
    assert body["sessions"][0]["trace_health"] == "complete"


def test_admin_interview_session_traces_returns_payload(client, monkeypatch):
    """Trace Explorer route returns compact nodes for a persisted session."""
    _set_token(monkeypatch, None, allow_open_admin=True)

    monkeypatch.setattr(
        admin_api,
        "_interview_session_trace_payload",
        lambda session_id, limit=100: {
            "session_id": session_id,
            "trace_id": "trace-done",
            "status": "completed",
            "has_report": True,
            "overall_score": 7.66,
            "overall_verdict": "strong_hire",
            "trace_count": 2,
            "evaluator_trace_count": 1,
            "reward_trace_count": 1,
            "final_report_trace_count": 0,
            "trace_health": "complete",
            "nodes": [
                {
                    "id": 1,
                    "turn_idx": 0,
                    "node": "evaluator",
                    "dimension": "technical_depth",
                    "action_id": "plan_deep_probe",
                    "score": 7.5,
                    "passed": True,
                    "immediate_reward": 0.8,
                    "immediate_reward_applied": False,
                    "payload": {"rationale": "ok"},
                    "created_at": "2026-05-01T10:00:00+00:00",
                }
            ],
        },
    )

    resp = client.get("/admin/interview-sessions/sess-done/traces")

    assert resp.status_code == 200
    body = resp.json()
    assert body["session_id"] == "sess-done"
    assert body["trace_health"] == "complete"
    assert body["nodes"][0]["node"] == "evaluator"


def test_admin_interview_session_traces_returns_global_debug_counts(
    client,
    monkeypatch,
):
    """Trace Explorer pagination still returns full-session diagnostics."""
    _set_token(monkeypatch, None, allow_open_admin=True)

    from contextlib import contextmanager

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    import app.models as models_mod
    from app.models import GenerationTrace, InterviewSession
    from app.models.base import Base

    engine = create_engine(
        "sqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    with Session() as sess:
        sess.add(
            InterviewSession(
                session_id="sess-debug",
                trace_id="trace-debug",
                candidate_name="Debug Candidate",
                job_title="Platform Engineer",
                job_level="senior",
                mode="mixed",
                status="completed",
                final_report={"overall_score": 7.5, "verdict": "hire"},
                created_at=datetime.now(UTC),
            )
        )
        sess.add_all(
            [
                GenerationTrace(
                    trace_id="trace-debug",
                    session_id="sess-debug",
                    turn_idx=0,
                    node="director_sample",
                ),
                GenerationTrace(
                    trace_id="trace-debug",
                    session_id="sess-debug",
                    turn_idx=0,
                    node="evaluator",
                    evaluation={"source": "fallback"},
                    score=5.0,
                ),
                GenerationTrace(
                    trace_id="trace-debug",
                    session_id="sess-debug",
                    turn_idx=0,
                    node="reward_update",
                ),
                GenerationTrace(
                    trace_id="trace-debug",
                    session_id="sess-debug",
                    turn_idx=1,
                    node="evaluator",
                    evaluation={"source": "model"},
                    score=8.0,
                ),
            ]
        )
        sess.commit()

    @contextmanager
    def get_session():
        with Session() as sess:
            yield sess
            sess.commit()

    monkeypatch.setattr(models_mod, "get_session", get_session)

    resp = client.get("/admin/interview-sessions/sess-debug/traces?limit=2")

    assert resp.status_code == 200
    body = resp.json()
    assert len(body["nodes"]) == 2
    assert body["nodes_has_more"] is True
    assert body["node_type_counts"] == {
        "director_sample": 1,
        "evaluator": 2,
        "reward_update": 1,
    }
    assert body["fallback_trace_count"] == 1
    assert body["turn_count"] == 2


def test_admin_metrics_endpoint_returns_prometheus_text(client, monkeypatch):
    _set_token(monkeypatch, None, allow_open_admin=True)

    resp = client.get("/admin/metrics")

    assert resp.status_code == 200
    assert "text/plain" in resp.headers["content-type"]
    assert "trace_write_failures_total" in resp.text


def test_admin_tracer_health_returns_counter_snapshot(client, monkeypatch):
    _set_token(monkeypatch, None, allow_open_admin=True)

    resp = client.get("/admin/tracer/health")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] in {"ok", "degraded"}
    assert "trace_write_success_total" in body
    assert "trace_write_failures_total" in body
    assert "operations" in body


def test_admin_security_summary_returns_security_counters(client, monkeypatch):
    _set_token(monkeypatch, None, allow_open_admin=True)

    from app.core.metrics import (
        record_context_flags,
        record_rate_limit_block,
        record_session_privacy_delete,
        record_setup_parse_error,
        record_ws_invalid_frame,
        reset_security_metrics_for_tests,
    )

    reset_security_metrics_for_tests()
    record_setup_parse_error("resume", "resume_parse_failed")
    record_context_flags("jd", ["possible_prompt_injection"])
    record_rate_limit_block("llm_test")
    record_ws_invalid_frame("invalid_json")
    record_session_privacy_delete("session")

    resp = client.get("/admin/security/summary")

    assert resp.status_code == 200
    assert resp.json() == {
        "setup_parse_errors": {"resume:resume_parse_failed": 1},
        "context_flags": {"jd:possible_prompt_injection": 1},
        "rate_limit_blocks": {"llm_test": 1},
        "ws_invalid_frames": {"invalid_json": 1},
        "session_privacy_deletes": {"session": 1},
    }
    reset_security_metrics_for_tests()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakeBandit:
    """Tiny stand-in so the snapshot route doesn't need a real DB.

    Only used to exercise the 200-path; counters can be any
    serialisable shape the route happens to json.dumps.
    """

    def __init__(self, priors: dict[str, Any] | None = None) -> None:
        self._priors = priors or {}

    def snapshot(self) -> dict[str, Any]:
        return self._priors
