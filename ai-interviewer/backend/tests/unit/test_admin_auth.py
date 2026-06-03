"""Auth + shape tests for the ``/admin/*`` observability router.

``require_admin_access`` gates every admin route. It accepts active
``role=admin`` account cookies and keeps ``API_TOKEN`` as a bootstrap
fallback.

Also regression-covers ``/admin/strategies`` after the ``e.metadata``
AttributeError fix.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.v1 import account as account_api
from app.api.v1 import admin as admin_api
from app.api.v1 import auth as auth_api
from app.core import settings as settings_mod
from app.models.auth import AuthSession, User
from app.models.base import Base
from app.models.interview_session import InterviewSession
from app.models.user_credit import UserCreditAccount, UserCreditLedger


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
    app.include_router(admin_api.api_v1_router)
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


@contextmanager
def _isolated_auth_db(monkeypatch: pytest.MonkeyPatch):
    engine = create_engine(
        "sqlite://",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session_local = sessionmaker(
        bind=engine,
        expire_on_commit=False,
        autoflush=False,
    )
    Base.metadata.create_all(engine)

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

    monkeypatch.setattr(auth_api, "get_db_session", get_session, raising=False)
    monkeypatch.setattr(account_api, "get_db_session", get_session, raising=False)
    monkeypatch.setattr(
        "app.services.user_auth.get_db_session",
        get_session,
        raising=False,
    )
    monkeypatch.setattr(admin_api, "get_session", get_session, raising=False)
    yield testing_session_local


def _auth_admin_client() -> TestClient:
    app = FastAPI()
    app.include_router(account_api.router)
    app.include_router(auth_api.router)
    app.include_router(admin_api.router)
    app.include_router(admin_api.api_v1_router)
    return TestClient(app)


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


def test_admin_routes_use_role_aware_access_gate() -> None:
    source = Path(admin_api.__file__).read_text(encoding="utf-8")

    assert "def require_admin_access" in source
    assert "Depends(require_admin_access)" in source
    assert "Depends(require_admin_token)" not in source


def test_admin_access_rejects_anonymous_and_regular_users(monkeypatch):
    _set_token(monkeypatch, "secret-abc")

    with _isolated_auth_db(monkeypatch):
        client = _auth_admin_client()

        anonymous = client.get("/admin/security/summary")
        assert anonymous.status_code == 401

        client.post(
            "/api/v1/auth/register",
            json={"email": "plain-user@example.com", "password": "correct horse"},
        )
        regular = client.get("/admin/security/summary")

        assert regular.status_code == 403


def test_admin_role_cookie_can_access_admin_without_api_token(monkeypatch):
    _set_token(monkeypatch, "secret-abc")

    with _isolated_auth_db(monkeypatch) as testing_session_local:
        client = _auth_admin_client()
        registered = client.post(
            "/api/v1/auth/register",
            json={"email": "operator@example.com", "password": "correct horse"},
        )
        user_id = registered.json()["user"]["id"]
        with testing_session_local() as sess:
            user = sess.get(User, user_id)
            assert user is not None
            user.role = "admin"
            sess.commit()

        resp = client.get("/admin/security/summary")

        assert resp.status_code == 200


def test_inactive_admin_cookie_is_rejected(monkeypatch):
    _set_token(monkeypatch, "secret-abc")

    with _isolated_auth_db(monkeypatch) as testing_session_local:
        client = _auth_admin_client()
        registered = client.post(
            "/api/v1/auth/register",
            json={"email": "disabled-admin@example.com", "password": "correct horse"},
        )
        user_id = registered.json()["user"]["id"]
        with testing_session_local() as sess:
            user = sess.get(User, user_id)
            assert user is not None
            user.role = "admin"
            user.status = "disabled"
            sess.commit()

        resp = client.get("/admin/security/summary")

        assert resp.status_code == 401


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
    session_factory = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    with session_factory() as sess:
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
        with session_factory() as sess:
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
    session_factory = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    now = datetime.now(UTC)
    with session_factory() as sess:
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
        with session_factory() as sess:
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


def test_admin_interview_sessions_includes_owner_identity_fields(
    client,
    monkeypatch,
):
    """Admin history can distinguish owned account sessions from anonymous ones."""
    _set_token(monkeypatch, None, allow_open_admin=True)

    from contextlib import contextmanager

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    import app.models as models_mod
    from app.models import InterviewSession, User
    from app.models.base import Base

    engine = create_engine(
        "sqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    now = datetime.now(UTC)
    with session_factory() as sess:
        owner = User(
            email="owner@example.com",
            password_hash="hash",
            role="user",
            status="active",
        )
        sess.add(owner)
        sess.flush()
        sess.add_all(
            [
                InterviewSession(
                    session_id="sess-owned",
                    trace_id="trace-owned",
                    owner_user_id=owner.id,
                    owner_claimed_at=now,
                    candidate_name="Alex",
                    job_title="Backend Engineer",
                    job_level="mid",
                    mode="mixed",
                    status="completed",
                    final_report={"overall_score": 8},
                    created_at=now,
                    updated_at=now,
                ),
                InterviewSession(
                    session_id="sess-anon",
                    trace_id="trace-anon",
                    candidate_name="Guest",
                    job_title="Frontend Engineer",
                    job_level="junior",
                    mode="mixed",
                    status="running",
                    created_at=now - timedelta(minutes=1),
                    updated_at=now - timedelta(minutes=1),
                ),
            ]
        )
        sess.commit()
        owner_id = owner.id

    @contextmanager
    def get_session():
        with session_factory() as sess:
            yield sess
            sess.commit()

    monkeypatch.setattr(models_mod, "get_session", get_session)

    resp = client.get("/admin/interview-sessions?limit=10")

    assert resp.status_code == 200
    by_id = {item["session_id"]: item for item in resp.json()["sessions"]}
    assert by_id["sess-owned"]["owner_user_id"] == owner_id
    assert by_id["sess-owned"]["owner_email"] == "owner@example.com"
    assert by_id["sess-owned"]["owner_status"] == "active"
    assert by_id["sess-anon"]["owner_user_id"] is None
    assert by_id["sess-anon"]["owner_email"] is None
    assert by_id["sess-anon"]["owner_status"] is None


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
    session_factory = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    with session_factory() as sess:
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
        with session_factory() as sess:
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


def test_admin_user_credit_ops_are_token_gated_and_adjust_balances(
    client,
    monkeypatch,
) -> None:
    _set_token(monkeypatch, "secret-token")

    from contextlib import contextmanager

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from app.models.auth import User
    from app.models.base import Base

    engine = create_engine(
        "sqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    with session_factory() as sess:
        sess.add(
            User(
                email="credits-admin@example.com",
                password_hash="hash",
                role="user",
                status="active",
            )
        )
        sess.commit()

    @contextmanager
    def get_session():
        with session_factory() as sess:
            yield sess
            sess.commit()

    monkeypatch.setattr(admin_api, "get_session", get_session)

    assert client.get("/api/v1/admin/user-credits").status_code == 401
    assert (
        client.get(
            "/api/v1/admin/user-credits",
            headers={"Authorization": "Bearer wrong"},
        ).status_code
        == 403
    )

    listed = client.get(
        "/api/v1/admin/user-credits",
        headers={"Authorization": "Bearer secret-token"},
    )

    assert listed.status_code == 200
    body = listed.json()
    assert body["count"] == 1
    user_item = body["users"][0]
    assert user_item["email"] == "credits-admin@example.com"
    assert user_item["balance"] == 10

    user_id = user_item["user_id"]
    adjusted = client.post(
        f"/api/v1/admin/users/{user_id}/credit-adjustments",
        json={"amount_delta": 3, "reason": "manual beta grant"},
        headers={"Authorization": "Bearer secret-token"},
    )
    assert adjusted.status_code == 200
    assert adjusted.json()["balance"] == 13

    blocked = client.post(
        f"/api/v1/admin/users/{user_id}/credit-adjustments",
        json={"amount_delta": -99, "reason": "bad adjustment"},
        headers={"Authorization": "Bearer secret-token"},
    )
    assert blocked.status_code == 409

    missing = client.post(
        "/api/v1/admin/users/9999/credit-adjustments",
        json={"amount_delta": 1, "reason": "missing user"},
        headers={"Authorization": "Bearer secret-token"},
    )
    assert missing.status_code == 404

    missing_ledger = client.get(
        "/api/v1/admin/users/9999/credit-ledger",
        headers={"Authorization": "Bearer secret-token"},
    )
    assert missing_ledger.status_code == 404

    ledger = client.get(
        f"/api/v1/admin/users/{user_id}/credit-ledger",
        headers={"Authorization": "Bearer secret-token"},
    )
    assert ledger.status_code == 200
    entries = ledger.json()["entries"]
    assert any(entry["kind"] == "free_grant" and entry["delta"] == 10 for entry in entries)
    assert any(entry["kind"] == "admin_adjustment" and entry["delta"] == 3 for entry in entries)


def test_admin_credit_requests_can_be_approved_or_rejected(monkeypatch):
    _set_token(monkeypatch, "secret-abc")

    with _isolated_auth_db(monkeypatch) as testing_session_local:
        admin_client = _auth_admin_client()
        requester_client = _auth_admin_client()
        reject_client = _auth_admin_client()

        requester_registered = requester_client.post(
            "/api/v1/auth/register",
            json={"email": "requester@example.com", "password": "correct horse"},
        )
        requester_id = requester_registered.json()["user"]["id"]
        reject_registered = reject_client.post(
            "/api/v1/auth/register",
            json={"email": "reject-me@example.com", "password": "correct horse"},
        )
        assert reject_registered.status_code == 200
        admin_registered = admin_client.post(
            "/api/v1/auth/register",
            json={"email": "credit-admin@example.com", "password": "correct horse"},
        )
        admin_id = admin_registered.json()["user"]["id"]
        with testing_session_local() as sess:
            admin = sess.get(User, admin_id)
            assert admin is not None
            admin.role = "admin"
            sess.commit()

        pending = requester_client.post(
            "/api/v1/account/credit-requests",
            json={
                "requested_amount": 6,
                "reason": "Preparing for final onsite interviews.",
            },
        )
        rejected_pending = reject_client.post(
            "/api/v1/account/credit-requests",
            json={"requested_amount": 2, "reason": "Need one more practice pass."},
        )
        assert pending.status_code == 200
        assert rejected_pending.status_code == 200
        request_id = pending.json()["request"]["id"]
        reject_id = rejected_pending.json()["request"]["id"]

        anon = _auth_admin_client().get("/api/v1/admin/credit-requests")
        regular = requester_client.get("/api/v1/admin/credit-requests")
        assert anon.status_code == 401
        assert regular.status_code == 403

        listed = admin_client.get(
            "/api/v1/admin/credit-requests?status=pending&email=requester"
        )
        assert listed.status_code == 200
        listed_body = listed.json()
        assert listed_body["count"] == 1
        assert listed_body["requests"][0]["user_email"] == "requester@example.com"
        assert listed_body["requests"][0]["requested_amount"] == 6
        assert "password_hash" not in str(listed_body)
        assert "token_hash" not in str(listed_body)

        approved = admin_client.post(
            f"/api/v1/admin/credit-requests/{request_id}/decision",
            json={"status": "approved", "reason": "Approved for beta cohort."},
        )
        assert approved.status_code == 200
        approved_body = approved.json()
        assert approved_body["request"]["status"] == "approved"
        assert approved_body["request"]["decided_by_user_id"] == admin_id
        assert approved_body["request"]["credit_ledger_entry_id"] is not None
        assert approved_body["credit_ledger_entry"]["kind"] == "admin_adjustment"
        assert approved_body["credit_ledger_entry"]["delta"] == 6
        assert approved_body["credit_ledger_entry"]["balance_after"] == 16

        duplicate_approval = admin_client.post(
            f"/api/v1/admin/credit-requests/{request_id}/decision",
            json={"status": "approved", "reason": "Should not run twice."},
        )
        assert duplicate_approval.status_code == 409

        rejected = admin_client.post(
            f"/api/v1/admin/credit-requests/{reject_id}/decision",
            json={"status": "rejected", "reason": "Please use existing balance first."},
        )
        assert rejected.status_code == 200
        assert rejected.json()["request"]["status"] == "rejected"
        assert rejected.json()["credit_ledger_entry"] is None

        requester_view = requester_client.get("/api/v1/account/credit-requests")
        assert requester_view.status_code == 200
        assert requester_view.json()["requests"][0]["status"] == "approved"

        with testing_session_local() as sess:
            adjustments = (
                sess.query(UserCreditLedger)
                .filter(UserCreditLedger.user_id == requester_id)
                .filter(UserCreditLedger.kind == "admin_adjustment")
                .all()
            )
            assert len(adjustments) == 1
            assert adjustments[0].delta == 6


def test_admin_users_list_is_role_gated_and_returns_safe_aggregates(monkeypatch):
    _set_token(monkeypatch, "secret-abc")
    now = datetime.now(UTC)

    with _isolated_auth_db(monkeypatch) as testing_session_local:
        client = _auth_admin_client()
        registered = client.post(
            "/api/v1/auth/register",
            json={"email": "operator@example.com", "password": "correct horse"},
        )
        admin_id = registered.json()["user"]["id"]
        with testing_session_local() as sess:
            admin = sess.get(User, admin_id)
            assert admin is not None
            admin.role = "admin"
            target = User(
                email="candidate@example.com",
                password_hash="hash",
                role="user",
                status="active",
                created_at=now - timedelta(days=1),
                updated_at=now - timedelta(hours=2),
            )
            empty_credit = User(
                email="no-credit@example.com",
                password_hash="hash",
                role="user",
                status="active",
                created_at=now - timedelta(days=2),
                updated_at=now - timedelta(hours=3),
            )
            sess.add_all([target, empty_credit])
            sess.flush()
            sess.add_all(
                [
                    UserCreditAccount(
                        user_id=target.id,
                        balance=4,
                        free_grant_version=None,
                        created_at=now,
                        updated_at=now,
                    ),
                    InterviewSession(
                        session_id="sess-owned-account-admin",
                        trace_id="trace-owned-account-admin",
                        owner_user_id=target.id,
                        owner_claimed_at=now,
                        candidate_name="Alex",
                        job_title="Backend Engineer",
                        job_level="mid",
                        mode="mixed",
                        status="completed",
                        created_at=now,
                        updated_at=now,
                    ),
                    AuthSession(
                        user_id=target.id,
                        token_hash="target-token-hash",
                        expires_at=now + timedelta(days=1),
                        last_seen_at=now - timedelta(minutes=5),
                        created_at=now - timedelta(hours=1),
                    ),
                ]
            )
            sess.commit()

        anonymous = _auth_admin_client().get("/api/v1/admin/users")
        assert anonymous.status_code == 401

        resp = client.get("/api/v1/admin/users?email=candidate&status=active&role=user")

        assert resp.status_code == 200
        body = resp.json()
        assert body["count"] == 1
        item = body["users"][0]
        assert item["email"] == "candidate@example.com"
        assert item["role"] == "user"
        assert item["status"] == "active"
        assert item["credit_balance"] == 4
        assert item["interview_session_count"] == 1
        assert item["last_seen_at"]
        assert "password_hash" not in item
        assert "token_hash" not in item

        no_credit = client.get("/api/v1/admin/users?email=no-credit")
        assert no_credit.status_code == 200
        assert no_credit.json()["users"][0]["credit_balance"] == 0
        with testing_session_local() as sess:
            assert sess.query(UserCreditLedger).count() == 0
            assert sess.get(UserCreditAccount, empty_credit.id) is None


def test_admin_user_detail_returns_safe_profile_ledger_and_recent_sessions(monkeypatch):
    _set_token(monkeypatch, "secret-abc")
    now = datetime.now(UTC)

    with _isolated_auth_db(monkeypatch) as testing_session_local:
        client = _auth_admin_client()
        registered = client.post(
            "/api/v1/auth/register",
            json={"email": "operator-detail@example.com", "password": "correct horse"},
        )
        admin_id = registered.json()["user"]["id"]
        with testing_session_local() as sess:
            admin = sess.get(User, admin_id)
            assert admin is not None
            admin.role = "admin"
            target = User(
                email="detail-user@example.com",
                password_hash="hash",
                role="user",
                status="active",
                created_at=now - timedelta(days=2),
                updated_at=now - timedelta(hours=2),
            )
            sess.add(target)
            sess.flush()
            sess.add_all(
                [
                    UserCreditAccount(
                        user_id=target.id,
                        balance=7,
                        free_grant_version="free_grant:v1",
                        created_at=now,
                        updated_at=now,
                    ),
                    UserCreditLedger(
                        user_id=target.id,
                        delta=7,
                        kind="admin_adjustment",
                        external_ref="admin_adjustment:detail-test",
                        session_id=None,
                        reason="manual adjustment",
                        balance_after=7,
                        created_at=now,
                    ),
                    InterviewSession(
                        session_id="sess-detail-owned",
                        trace_id="trace-detail-owned",
                        owner_user_id=target.id,
                        owner_claimed_at=now,
                        candidate_name="Detail User",
                        job_title="Data Engineer",
                        job_level="senior",
                        mode="mixed",
                        status="completed",
                        final_report={"overall_score": 8.5, "growth_signal": "strong"},
                        created_at=now,
                        updated_at=now,
                    ),
                ]
            )
            sess.commit()
            target_id = int(target.id)

        resp = client.get(f"/api/v1/admin/users/{target_id}")

        assert resp.status_code == 200
        body = resp.json()
        assert body["user"]["email"] == "detail-user@example.com"
        assert body["credit"]["balance"] == 7
        assert body["recent_credit_entries"][0]["kind"] == "admin_adjustment"
        assert body["recent_interview_sessions"][0]["session_id"] == "sess-detail-owned"
        assert body["recent_interview_sessions"][0]["overall_score"] == 8.5
        assert "password_hash" not in body["user"]
        assert "token_hash" not in str(body)

        missing = client.get("/api/v1/admin/users/99999")
        assert missing.status_code == 404


def test_admin_can_disable_regular_user_and_existing_cookie_stops_authenticating(
    monkeypatch,
) -> None:
    _set_token(monkeypatch, "secret-abc")

    with _isolated_auth_db(monkeypatch) as testing_session_local:
        admin_client = _auth_admin_client()
        user_client = _auth_admin_client()
        user_registered = user_client.post(
            "/api/v1/auth/register",
            json={"email": "disable-me@example.com", "password": "correct horse"},
        )
        target_id = user_registered.json()["user"]["id"]
        admin_registered = admin_client.post(
            "/api/v1/auth/register",
            json={"email": "status-admin@example.com", "password": "correct horse"},
        )
        admin_id = admin_registered.json()["user"]["id"]
        with testing_session_local() as sess:
            admin = sess.get(User, admin_id)
            assert admin is not None
            admin.role = "admin"
            sess.commit()

        disabled = admin_client.post(
            f"/api/v1/admin/users/{target_id}/status",
            json={"status": "disabled", "reason": "abuse report"},
        )

        assert disabled.status_code == 200
        assert disabled.json()["user"]["status"] == "disabled"
        assert user_client.get("/api/v1/auth/me").json()["authenticated"] is False

        reenabled = admin_client.post(
            f"/api/v1/admin/users/{target_id}/status",
            json={"status": "active", "reason": "appeal accepted"},
        )
        assert reenabled.status_code == 200
        assert reenabled.json()["user"]["status"] == "active"


def test_admin_user_status_blocks_admin_targets_self_and_invalid_input(monkeypatch):
    _set_token(monkeypatch, "secret-abc")

    with _isolated_auth_db(monkeypatch) as testing_session_local:
        client = _auth_admin_client()
        registered = client.post(
            "/api/v1/auth/register",
            json={"email": "guarded-admin@example.com", "password": "correct horse"},
        )
        admin_id = registered.json()["user"]["id"]
        with testing_session_local() as sess:
            admin = sess.get(User, admin_id)
            assert admin is not None
            admin.role = "admin"
            other_admin = User(
                email="other-admin@example.com",
                password_hash="hash",
                role="admin",
                status="active",
            )
            regular = User(
                email="guarded-user@example.com",
                password_hash="hash",
                role="user",
                status="active",
            )
            sess.add_all([other_admin, regular])
            sess.commit()
            other_admin_id = int(other_admin.id)
            regular_id = int(regular.id)

        self_resp = client.post(
            f"/api/v1/admin/users/{admin_id}/status",
            json={"status": "disabled", "reason": "self lockout"},
        )
        admin_target = client.post(
            f"/api/v1/admin/users/{other_admin_id}/status",
            json={"status": "disabled", "reason": "dangerous"},
        )
        invalid_status = client.post(
            f"/api/v1/admin/users/{regular_id}/status",
            json={"status": "suspended", "reason": "invalid"},
        )
        missing_reason = client.post(
            f"/api/v1/admin/users/{regular_id}/status",
            json={"status": "disabled"},
        )

        assert self_resp.status_code == 409
        assert admin_target.status_code == 409
        assert invalid_status.status_code == 422
        assert missing_reason.status_code == 422


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
