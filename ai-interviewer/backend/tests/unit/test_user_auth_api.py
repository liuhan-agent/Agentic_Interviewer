from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.v1 import account as account_api
from app.api.v1 import auth as auth_api
from app.api.v1 import interview as interview_api
from app.core.rate_limit import clear_rate_limits
from app.core.session_auth import (
    hash_recovery_token,
    hash_session_token,
    verify_recovery_token,
    verify_session_token,
)
from app.models.auth import User
from app.models.base import Base
from app.models.interview_session import InterviewSession


def _payload() -> dict[str, Any]:
    return {
        "candidate": {
            "name": "Alex",
            "resume_parsed": {
                "summary": "Backend engineer.",
                "skills": ["python"],
                "highlights": ["Built APIs."],
            },
        },
        "job_spec": {
            "title": "Backend Engineer",
            "level": "mid",
            "required_skills": ["python"],
            "rubric_dimensions": ["technical_depth"],
        },
        "max_turns": 3,
    }


@contextmanager
def _isolated_db(monkeypatch: pytest.MonkeyPatch):
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
    monkeypatch.setattr(interview_api, "get_db_session", get_session, raising=False)
    monkeypatch.setattr(
        "app.services.user_auth.get_db_session",
        get_session,
        raising=False,
    )
    yield testing_session_local


class _StartManager:
    def __init__(self) -> None:
        self.started: dict[str, Any] | None = None

    def session_exists(self, session_id: str) -> bool:
        return False

    def get(self, session_id: str) -> Any | None:
        return None

    def start(self, session_id: str, trace_id: str, initial: dict[str, Any], **kwargs: Any):
        self.started = {
            "session_id": session_id,
            "trace_id": trace_id,
            "initial": initial,
            **kwargs,
        }
        return object()


class _AuthSettings:
    app_env = "dev"
    auth_session_ttl_days = 14
    auth_registration_mode = "open"
    auth_register_rate_limit_per_minute = 20
    auth_login_rate_limit_per_minute = 60
    rate_limit_window_seconds = 60
    free_interview_credits = 10
    free_credits_require_email_verified = False

    def __init__(self, **overrides: Any) -> None:
        for key, value in overrides.items():
            setattr(self, key, value)


def _client(monkeypatch: pytest.MonkeyPatch, manager: Any | None = None) -> TestClient:
    if manager is not None:
        monkeypatch.setattr(interview_api, "get_session_manager", lambda: manager)
    app = FastAPI()
    app.include_router(account_api.router)
    app.include_router(auth_api.router)
    app.include_router(interview_api.router)
    return TestClient(app)


def test_register_sets_http_only_cookie_and_me_returns_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _isolated_db(monkeypatch):
        client = _client(monkeypatch)

        resp = client.post(
            "/api/v1/auth/register",
            json={"email": "  USER@example.COM ", "password": "correct horse"},
        )

        assert resp.status_code == 200
        assert "ai_interviewer_auth=" in resp.headers["set-cookie"]
        assert "HttpOnly" in resp.headers["set-cookie"]
        body = resp.json()
        assert body["authenticated"] is True
        assert body["user"]["email"] == "user@example.com"
        assert body["user"]["role"] == "user"

        me = client.get("/api/v1/auth/me")

        assert me.status_code == 200
        assert me.json()["user"]["email"] == "user@example.com"
        assert me.json()["user"]["role"] == "user"


def test_register_rejects_client_supplied_role(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _isolated_db(monkeypatch):
        client = _client(monkeypatch)

        resp = client.post(
            "/api/v1/auth/register",
            json={
                "email": "admin-claim@example.com",
                "password": "correct horse",
                "role": "admin",
            },
        )

        assert resp.status_code == 422


def test_register_rejects_duplicate_normalized_email(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _isolated_db(monkeypatch):
        client = _client(monkeypatch)
        first = client.post(
            "/api/v1/auth/register",
            json={"email": "user@example.com", "password": "correct horse"},
        )
        assert first.status_code == 200

        duplicate = client.post(
            "/api/v1/auth/register",
            json={"email": " USER@EXAMPLE.COM ", "password": "correct horse"},
        )

        assert duplicate.status_code == 409


def test_registration_closed_blocks_new_accounts_but_login_still_works(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _isolated_db(monkeypatch):
        client = _client(monkeypatch)
        registered = client.post(
            "/api/v1/auth/register",
            json={"email": "existing@example.com", "password": "correct horse"},
        )
        assert registered.status_code == 200
        client.post("/api/v1/auth/logout")

        monkeypatch.setattr(
            auth_api,
            "get_settings",
            lambda: _AuthSettings(auth_registration_mode="closed"),
            raising=False,
        )

        blocked = client.post(
            "/api/v1/auth/register",
            json={"email": "new@example.com", "password": "correct horse"},
        )
        login = client.post(
            "/api/v1/auth/login",
            json={"email": "existing@example.com", "password": "correct horse"},
        )

        assert blocked.status_code == 403
        assert blocked.json()["detail"]["code"] == "registration_closed"
        assert login.status_code == 200


def test_register_and_login_rate_limits_return_retry_after(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clear_rate_limits()
    try:
        with _isolated_db(monkeypatch):
            monkeypatch.setattr(
                auth_api,
                "get_settings",
                lambda: _AuthSettings(
                    auth_register_rate_limit_per_minute=1,
                    auth_login_rate_limit_per_minute=1,
                    rate_limit_window_seconds=60,
                ),
                raising=False,
            )
            client = _client(monkeypatch)

            first_register = client.post(
                "/api/v1/auth/register",
                json={"email": "limited@example.com", "password": "correct horse"},
            )
            second_register = client.post(
                "/api/v1/auth/register",
                json={"email": "limited-2@example.com", "password": "correct horse"},
            )

            assert first_register.status_code == 200
            assert second_register.status_code == 429
            assert second_register.json()["detail"]["code"] == "rate_limit_exceeded"
            assert second_register.headers["Retry-After"]

            first_login = client.post(
                "/api/v1/auth/login",
                json={"email": "limited@example.com", "password": "correct horse"},
            )
            second_login = client.post(
                "/api/v1/auth/login",
                json={"email": "limited@example.com", "password": "correct horse"},
            )

            assert first_login.status_code == 200
            assert second_login.status_code == 429
            assert second_login.json()["detail"]["code"] == "rate_limit_exceeded"
            assert second_login.headers["Retry-After"]
    finally:
        clear_rate_limits()


def test_login_and_logout_rotate_me_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _isolated_db(monkeypatch):
        client = _client(monkeypatch)
        registered = client.post(
            "/api/v1/auth/register",
            json={"email": "user@example.com", "password": "correct horse"},
        )
        assert registered.status_code == 200
        logout = client.post("/api/v1/auth/logout")
        assert logout.status_code == 200

        login = client.post(
            "/api/v1/auth/login",
            json={"email": "USER@example.com", "password": "correct horse"},
        )
        assert login.status_code == 200
        assert client.get("/api/v1/auth/me").json()["authenticated"] is True

        client.post("/api/v1/auth/logout")

        assert client.get("/api/v1/auth/me").json()["authenticated"] is False


def test_logged_in_start_session_binds_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _isolated_db(monkeypatch):
        manager = _StartManager()
        client = _client(monkeypatch, manager)
        registered = client.post(
            "/api/v1/auth/register",
            json={"email": "user@example.com", "password": "correct horse"},
        )
        user_id = registered.json()["user"]["id"]

        resp = client.post("/api/v1/interview/sessions", json=_payload())

        assert resp.status_code == 200
        assert manager.started is not None
        assert manager.started["owner_user_id"] == user_id
        assert manager.started["owner_claimed_at"] is not None
        assert resp.json()["owner_user_id"] == user_id
        assert resp.json()["billing_mode"] == "dev_unmetered"
        assert resp.json()["credit_delta"] is None
        assert resp.json()["credit_balance"] is None


def test_account_credits_requires_login_and_grants_free_credits_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _isolated_db(monkeypatch):
        client = _client(monkeypatch)

        policy = client.get("/api/v1/account/credit-policy")
        assert policy.status_code == 200
        assert policy.json() == {
            "enforced": False,
            "free_grant": 10,
            "interview_unit": "interview",
            "requires_login_for_platform_hosted": True,
            "registration_mode": "open",
            "free_credits_require_email_verified": False,
        }

        anon = client.get("/api/v1/account/credits")
        assert anon.status_code == 401

        client.post(
            "/api/v1/auth/register",
            json={"email": "credits@example.com", "password": "correct horse"},
        )

        first = client.get("/api/v1/account/credits")
        second = client.get("/api/v1/account/credits")

        assert first.status_code == 200
        assert second.status_code == 200
        assert first.json()["balance"] == 10
        assert second.json()["balance"] == 10
        assert first.json()["free_grant_total"] == 10
        assert first.json()["unit"] == "interview"
        grant_entries = [
            entry
            for entry in second.json()["recent_entries"]
            if entry["kind"] == "free_grant"
        ]
        assert len(grant_entries) == 1


def test_free_credits_can_require_verified_email_before_grant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _isolated_db(monkeypatch) as testing_session_local:
        monkeypatch.setattr(
            account_api,
            "get_settings",
            lambda: _AuthSettings(free_credits_require_email_verified=True),
            raising=False,
        )
        client = _client(monkeypatch)
        registered = client.post(
            "/api/v1/auth/register",
            json={"email": "verify-first@example.com", "password": "correct horse"},
        )
        assert registered.status_code == 200
        user_id = int(registered.json()["user"]["id"])

        before_verified = client.get("/api/v1/account/credits")
        assert before_verified.status_code == 200
        assert before_verified.json()["balance"] == 0
        assert before_verified.json()["free_grant_total"] == 0
        assert [
            entry
            for entry in before_verified.json()["recent_entries"]
            if entry["kind"] == "free_grant"
        ] == []

        with testing_session_local() as sess:
            user = sess.get(User, user_id)
            assert user is not None
            user.email_verified_at = datetime.now(UTC)
            sess.commit()

        after_verified = client.get("/api/v1/account/credits")
        repeat = client.get("/api/v1/account/credits")

        assert after_verified.status_code == 200
        assert after_verified.json()["balance"] == 10
        assert after_verified.json()["free_grant_total"] == 10
        grant_entries = [
            entry
            for entry in repeat.json()["recent_entries"]
            if entry["kind"] == "free_grant"
        ]
        assert len(grant_entries) == 1


def test_account_credit_requests_require_login_and_limit_pending(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _isolated_db(monkeypatch):
        client = _client(monkeypatch)

        anon_list = client.get("/api/v1/account/credit-requests")
        anon_create = client.post(
            "/api/v1/account/credit-requests",
            json={"requested_amount": 5, "reason": "Need more interview practice."},
        )
        assert anon_list.status_code == 401
        assert anon_create.status_code == 401

        registered = client.post(
            "/api/v1/auth/register",
            json={"email": "requester@example.com", "password": "correct horse"},
        )
        user_id = registered.json()["user"]["id"]

        created = client.post(
            "/api/v1/account/credit-requests",
            json={
                "requested_amount": 5,
                "reason": "Practicing for backend interviews.",
            },
        )

        assert created.status_code == 200
        body = created.json()
        assert body["request"]["user_id"] == user_id
        assert body["request"]["requested_amount"] == 5
        assert body["request"]["reason"] == "Practicing for backend interviews."
        assert body["request"]["status"] == "pending"
        assert body["request"]["decision_reason"] is None
        assert body["request"]["credit_ledger_entry_id"] is None

        duplicate = client.post(
            "/api/v1/account/credit-requests",
            json={"requested_amount": 3, "reason": "A second pending request."},
        )
        assert duplicate.status_code == 409

        own_requests = client.get("/api/v1/account/credit-requests")
        assert own_requests.status_code == 200
        assert own_requests.json()["count"] == 1
        assert own_requests.json()["requests"][0]["status"] == "pending"

        bad_amount = client.post(
            "/api/v1/account/credit-requests",
            json={"requested_amount": 0, "reason": "Invalid amount."},
        )
        assert bad_amount.status_code == 422

        blank_reason = client.post(
            "/api/v1/account/credit-requests",
            json={"requested_amount": 1, "reason": "   "},
        )
        assert blank_reason.status_code == 422


def test_logged_in_platform_start_debits_credit_and_returns_balance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Settings:
        app_env = "prod"
        session_token_ttl_hours = 24
        recovery_token_ttl_days = 7
        anonymous_session_start_rate_limit_per_minute = 0

    with _isolated_db(monkeypatch):
        manager = _StartManager()
        monkeypatch.setattr(interview_api, "get_settings", lambda: _Settings())
        monkeypatch.setattr(account_api, "get_settings", lambda: _Settings(), raising=False)
        client = _client(monkeypatch, manager)
        client.post(
            "/api/v1/auth/register",
            json={"email": "metered@example.com", "password": "correct horse"},
        )

        resp = client.post("/api/v1/interview/sessions", json=_payload())

        assert resp.status_code == 200
        assert manager.started is not None
        body = resp.json()
        assert body["billing_mode"] == "platform_credits"
        assert body["credit_delta"] == -1
        assert body["credit_balance"] == 9

        credits = client.get("/api/v1/account/credits")
        assert credits.status_code == 200
        assert credits.json()["balance"] == 9
        assert any(
            entry["kind"] == "session_debit" and entry["session_id"] == body["session_id"]
            for entry in credits.json()["recent_entries"]
        )


def test_admin_platform_start_still_debits_account_credits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Settings:
        app_env = "prod"
        session_token_ttl_hours = 24
        recovery_token_ttl_days = 7
        anonymous_session_start_rate_limit_per_minute = 0

    with _isolated_db(monkeypatch) as testing_session_local:
        manager = _StartManager()
        monkeypatch.setattr(interview_api, "get_settings", lambda: _Settings())
        monkeypatch.setattr(account_api, "get_settings", lambda: _Settings(), raising=False)
        client = _client(monkeypatch, manager)
        registered = client.post(
            "/api/v1/auth/register",
            json={"email": "admin-metered@example.com", "password": "correct horse"},
        )
        admin_id = registered.json()["user"]["id"]
        with testing_session_local() as sess:
            user = sess.get(User, admin_id)
            assert user is not None
            user.role = "admin"
            sess.commit()

        resp = client.post("/api/v1/interview/sessions", json=_payload())

        assert resp.status_code == 200
        assert resp.json()["billing_mode"] == "platform_credits"
        assert resp.json()["credit_delta"] == -1
        assert resp.json()["credit_balance"] == 9
        assert client.get("/api/v1/account/credits").json()["balance"] == 9


def test_platform_start_requires_login_and_blocks_when_credits_exhausted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Settings:
        app_env = "prod"
        session_token_ttl_hours = 24
        recovery_token_ttl_days = 7
        anonymous_session_start_rate_limit_per_minute = 0

    with _isolated_db(monkeypatch):
        anon_manager = _StartManager()
        monkeypatch.setattr(interview_api, "get_settings", lambda: _Settings())
        monkeypatch.setattr(account_api, "get_settings", lambda: _Settings(), raising=False)
        client = _client(monkeypatch, anon_manager)

        anon_resp = client.post("/api/v1/interview/sessions", json=_payload())

        assert anon_resp.status_code == 401
        assert anon_manager.started is None

        manager = _StartManager()
        monkeypatch.setattr(interview_api, "get_session_manager", lambda: manager)
        client.post(
            "/api/v1/auth/register",
            json={"email": "empty@example.com", "password": "correct horse"},
        )
        for _ in range(10):
            assert client.post("/api/v1/interview/sessions", json=_payload()).status_code == 200

        exhausted = client.post("/api/v1/interview/sessions", json=_payload())

        assert exhausted.status_code == 402
        assert exhausted.json()["detail"]["code"] == "platform_credits_exhausted"
        assert client.get("/api/v1/account/credits").json()["balance"] == 0


def test_byok_start_does_not_debit_platform_credits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Settings:
        app_env = "prod"
        session_token_ttl_hours = 24
        recovery_token_ttl_days = 7
        anonymous_session_start_rate_limit_per_minute = 0

    payload = _payload()
    payload["llm_config"] = {
        "provider": "openai",
        "api_key": "sk-user-provided-key",
        "model": "gpt-4o-mini",
    }

    with _isolated_db(monkeypatch):
        manager = _StartManager()
        monkeypatch.setattr(interview_api, "get_settings", lambda: _Settings())
        monkeypatch.setattr(account_api, "get_settings", lambda: _Settings(), raising=False)
        client = _client(monkeypatch, manager)
        client.post(
            "/api/v1/auth/register",
            json={"email": "byok@example.com", "password": "correct horse"},
        )
        assert client.get("/api/v1/account/credits").json()["balance"] == 10

        resp = client.post("/api/v1/interview/sessions", json=payload)

        assert resp.status_code == 200
        assert resp.json()["billing_mode"] == "byok"
        assert resp.json()["credit_delta"] is None
        assert resp.json()["credit_balance"] == 10
        assert client.get("/api/v1/account/credits").json()["balance"] == 10


def test_anonymous_start_session_keeps_owner_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _isolated_db(monkeypatch):
        manager = _StartManager()
        client = _client(monkeypatch, manager)

        resp = client.post("/api/v1/interview/sessions", json=_payload())

        assert resp.status_code == 200
        assert manager.started is not None
        assert manager.started["owner_user_id"] is None
        assert manager.started["owner_claimed_at"] is None
        assert resp.json()["owner_user_id"] is None


def test_prod_can_require_login_for_anonymous_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Settings:
        app_env = "prod"
        session_token_ttl_hours = 24
        recovery_token_ttl_days = 7
        anonymous_session_start_rate_limit_per_minute = 0

    with _isolated_db(monkeypatch):
        manager = _StartManager()
        monkeypatch.setattr(interview_api, "get_settings", lambda: _Settings())
        client = _client(monkeypatch, manager)

        resp = client.post("/api/v1/interview/sessions", json=_payload())

        assert resp.status_code == 401
        assert manager.started is None


def test_owned_session_requires_owner_account_not_session_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(UTC)
    with _isolated_db(monkeypatch) as testing_session_local:
        client = _client(monkeypatch, _StartManager())
        registered = client.post(
            "/api/v1/auth/register",
            json={"email": "owner@example.com", "password": "correct horse"},
        )
        owner_id = registered.json()["user"]["id"]
        with testing_session_local() as sess:
            sess.add(
                InterviewSession(
                    session_id="sess-owned-access",
                    trace_id="trace-owned-access",
                    owner_user_id=owner_id,
                    owner_claimed_at=now,
                    session_token_hash=hash_session_token("owned-token"),
                    session_token_expires_at=now + timedelta(hours=1),
                    candidate_name="Alex",
                    job_title="Backend Engineer",
                    job_level="mid",
                    mode="mixed",
                    status="running",
                    created_at=now,
                    updated_at=now,
                )
            )
            sess.commit()

        owner_resp = client.get(
            "/api/v1/interview/sessions/sess-owned-access/metadata",
        )
        assert owner_resp.status_code == 200

        client.post("/api/v1/auth/logout")
        anonymous_resp = client.get(
            "/api/v1/interview/sessions/sess-owned-access/metadata",
            headers={"X-Session-Token": "owned-token"},
        )
        assert anonymous_resp.status_code == 401


def test_other_user_cannot_access_owned_session_even_with_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(UTC)
    with _isolated_db(monkeypatch) as testing_session_local:
        client = _client(monkeypatch, _StartManager())
        owner = client.post(
            "/api/v1/auth/register",
            json={"email": "owner@example.com", "password": "correct horse"},
        )
        owner_id = owner.json()["user"]["id"]
        with testing_session_local() as sess:
            owner_user = sess.get(User, owner_id)
            assert owner_user is not None
            owner_user.role = "admin"
            sess.commit()
        client.post("/api/v1/auth/logout")
        client.post(
            "/api/v1/auth/register",
            json={"email": "other@example.com", "password": "correct horse"},
        )
        with testing_session_local() as sess:
            sess.add(
                InterviewSession(
                    session_id="sess-other-blocked",
                    trace_id="trace-other-blocked",
                    owner_user_id=owner_id,
                    owner_claimed_at=now,
                    session_token_hash=hash_session_token("owned-token"),
                    session_token_expires_at=now + timedelta(hours=1),
                    candidate_name="Alex",
                    job_title="Backend Engineer",
                    job_level="mid",
                    mode="mixed",
                    status="running",
                    created_at=now,
                    updated_at=now,
                )
            )
            sess.commit()

        resp = client.get(
            "/api/v1/interview/sessions/sess-other-blocked/metadata",
            headers={"X-Session-Token": "owned-token"},
        )

        assert resp.status_code == 403


def test_unowned_session_keeps_anonymous_token_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(UTC)
    with _isolated_db(monkeypatch) as testing_session_local:
        client = _client(monkeypatch, _StartManager())
        with testing_session_local() as sess:
            sess.add(
                InterviewSession(
                    session_id="sess-anon-access",
                    trace_id="trace-anon-access",
                    session_token_hash=hash_session_token("anon-token"),
                    session_token_expires_at=now + timedelta(hours=1),
                    candidate_name="Alex",
                    job_title="Backend Engineer",
                    job_level="mid",
                    mode="mixed",
                    status="running",
                    created_at=now,
                    updated_at=now,
                )
            )
            sess.commit()

        resp = client.get(
            "/api/v1/interview/sessions/sess-anon-access/metadata",
            headers={"X-Session-Token": "anon-token"},
        )

        assert resp.status_code == 200


def test_owned_session_recover_requires_owner_login(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(UTC)
    with _isolated_db(monkeypatch) as testing_session_local:
        client = _client(monkeypatch, _StartManager())
        registered = client.post(
            "/api/v1/auth/register",
            json={"email": "owner@example.com", "password": "correct horse"},
        )
        owner_id = registered.json()["user"]["id"]
        with testing_session_local() as sess:
            sess.add(
                InterviewSession(
                    session_id="sess-owned-recover",
                    trace_id="trace-owned-recover",
                    owner_user_id=owner_id,
                    owner_claimed_at=now,
                    recovery_token_hash=hash_recovery_token("recover-owned-token"),
                    recovery_token_expires_at=now + timedelta(days=1),
                    candidate_name="Alex",
                    job_title="Backend Engineer",
                    job_level="mid",
                    mode="mixed",
                    status="interrupted",
                    created_at=now,
                    updated_at=now,
                )
            )
            sess.commit()
        client.post("/api/v1/auth/logout")

        anonymous = client.post(
            "/api/v1/interview/sessions/sess-owned-recover/recover",
            json={"recovery_token": "recover-owned-token"},
        )
        assert anonymous.status_code == 401

        client.post(
            "/api/v1/auth/login",
            json={"email": "owner@example.com", "password": "correct horse"},
        )
        owner_resp = client.post(
            "/api/v1/interview/sessions/sess-owned-recover/recover",
            json={"recovery_token": "recover-owned-token"},
        )

        assert owner_resp.status_code == 200
        assert owner_resp.json()["session_token"]


def test_anonymous_recover_still_works_for_unowned_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(UTC)
    with _isolated_db(monkeypatch) as testing_session_local:
        client = _client(monkeypatch, _StartManager())
        with testing_session_local() as sess:
            sess.add(
                InterviewSession(
                    session_id="sess-anon-recover",
                    trace_id="trace-anon-recover",
                    recovery_token_hash=hash_recovery_token("recover-anon-token"),
                    recovery_token_expires_at=now + timedelta(days=1),
                    candidate_name="Alex",
                    job_title="Backend Engineer",
                    job_level="mid",
                    mode="mixed",
                    status="interrupted",
                    created_at=now,
                    updated_at=now,
                )
            )
            sess.commit()

        resp = client.post(
            "/api/v1/interview/sessions/sess-anon-recover/recover",
            json={"recovery_token": "recover-anon-token"},
        )

        assert resp.status_code == 200
        assert resp.json()["session_token"]


def test_claim_anonymous_session_requires_login_and_rotates_tokens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(UTC)
    with _isolated_db(monkeypatch) as testing_session_local:
        client = _client(monkeypatch, _StartManager())
        registered = client.post(
            "/api/v1/auth/register",
            json={"email": "user@example.com", "password": "correct horse"},
        )
        user_id = registered.json()["user"]["id"]
        with testing_session_local() as sess:
            sess.add(
                InterviewSession(
                    session_id="sess-claim",
                    trace_id="trace-claim",
                    session_token_hash=hash_session_token("old-session"),
                    session_token_expires_at=now + timedelta(hours=1),
                    recovery_token_hash=hash_recovery_token("old-recovery"),
                    recovery_token_expires_at=now + timedelta(days=1),
                    candidate_name="Alex",
                    job_title="Backend Engineer",
                    job_level="mid",
                    mode="mixed",
                    status="interrupted",
                    created_at=now,
                    updated_at=now,
                )
            )
            sess.commit()

        resp = client.post(
            "/api/v1/interview/sessions/sess-claim/claim",
            headers={"X-Session-Token": "old-session"},
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["session_token"] != "old-session"
        assert body["recovery_token"] != "old-recovery"
        with testing_session_local() as sess:
            row = sess.get(InterviewSession, "sess-claim")
            assert row is not None
            assert row.owner_user_id == user_id
            assert row.owner_claimed_at is not None
            assert verify_session_token(body["session_token"], row.session_token_hash)
            assert not verify_session_token("old-session", row.session_token_hash)
            assert verify_recovery_token(
                body["recovery_token"],
                row.recovery_token_hash,
            )
            assert not verify_recovery_token("old-recovery", row.recovery_token_hash)


def test_claim_session_owned_by_another_user_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(UTC)
    with _isolated_db(monkeypatch) as testing_session_local:
        client = _client(monkeypatch, _StartManager())
        client.post(
            "/api/v1/auth/register",
            json={"email": "owner@example.com", "password": "correct horse"},
        )
        client.post("/api/v1/auth/logout")
        second = client.post(
            "/api/v1/auth/register",
            json={"email": "second@example.com", "password": "correct horse"},
        )
        second_user_id = second.json()["user"]["id"]
        with testing_session_local() as sess:
            owner = sess.query(User).filter(User.email == "owner@example.com").one()
            assert owner.id != second_user_id
            sess.add(
                InterviewSession(
                    session_id="sess-owned",
                    trace_id="trace-owned",
                    owner_user_id=owner.id,
                    owner_claimed_at=now,
                    session_token_hash=hash_session_token("old-session"),
                    session_token_expires_at=now + timedelta(hours=1),
                    candidate_name="Alex",
                    job_title="Backend Engineer",
                    job_level="mid",
                    mode="mixed",
                    status="interrupted",
                    created_at=now,
                    updated_at=now,
                )
            )
            sess.commit()

        resp = client.post(
            "/api/v1/interview/sessions/sess-owned/claim",
            headers={"X-Session-Token": "old-session"},
        )

        assert resp.status_code == 409


def test_account_interview_sessions_requires_login(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _isolated_db(monkeypatch):
        client = _client(monkeypatch, _StartManager())

        resp = client.get("/api/v1/account/interview-sessions")

        assert resp.status_code == 401


def test_account_interview_sessions_returns_only_current_owner_without_tokens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(UTC)
    with _isolated_db(monkeypatch) as testing_session_local:
        client = _client(monkeypatch, _StartManager())
        owner = client.post(
            "/api/v1/auth/register",
            json={"email": "owner@example.com", "password": "correct horse"},
        )
        owner_id = owner.json()["user"]["id"]
        client.post("/api/v1/auth/logout")
        other = client.post(
            "/api/v1/auth/register",
            json={"email": "other@example.com", "password": "correct horse"},
        )
        other_id = other.json()["user"]["id"]
        client.post("/api/v1/auth/logout")
        client.post(
            "/api/v1/auth/login",
            json={"email": "owner@example.com", "password": "correct horse"},
        )
        with testing_session_local() as sess:
            sess.add_all(
                [
                    InterviewSession(
                        session_id="sess-owned-visible",
                        trace_id="trace-owned-visible",
                        owner_user_id=owner_id,
                        owner_claimed_at=now,
                        session_token_hash=hash_session_token("owned-token"),
                        session_token_expires_at=now + timedelta(hours=1),
                        recovery_token_hash=hash_recovery_token("recover-token"),
                        recovery_token_expires_at=now + timedelta(days=1),
                        candidate_name="Alex",
                        job_title="Backend Engineer",
                        job_level="mid",
                        mode="mixed",
                        status="completed",
                        turn_idx=3,
                        asked_turn=2,
                        final_report={
                            "overall_score": 8.2,
                            "growth_signal": "strong",
                            "overall_verdict": "strong_hire",
                            "dimension_scores": {
                                "technical_depth": {"score": 8.2},
                                "communication": {"score": None},
                                "legacy": 7,
                            },
                        },
                        created_at=now,
                        updated_at=now,
                    ),
                    InterviewSession(
                        session_id="sess-other-hidden",
                        trace_id="trace-other-hidden",
                        owner_user_id=other_id,
                        owner_claimed_at=now,
                        candidate_name="Blake",
                        job_title="Frontend Engineer",
                        job_level="senior",
                        mode="mixed",
                        status="completed",
                        created_at=now,
                        updated_at=now,
                    ),
                    InterviewSession(
                        session_id="sess-anon-hidden",
                        trace_id="trace-anon-hidden",
                        candidate_name="Casey",
                        job_title="Data Engineer",
                        job_level="junior",
                        mode="mixed",
                        status="running",
                        created_at=now,
                        updated_at=now,
                    ),
                ]
            )
            sess.commit()

        resp = client.get("/api/v1/account/interview-sessions")

        assert resp.status_code == 200
        body = resp.json()
        assert body["count"] == 1
        assert body["total_count"] == 1
        item = body["sessions"][0]
        assert item["session_id"] == "sess-owned-visible"
        assert item["owner_user_id"] == owner_id
        assert item["owner_claimed_at"]
        assert item["overall_score"] == 8.2
        assert item["growth_signal"] == "strong"
        assert item["overall_verdict"] == "strong_hire"
        assert item["dimension_scores"] == {"technical_depth": 8.2, "legacy": 7.0}
        assert "session_token" not in item
        assert "session_token_hash" not in item
        assert "recovery_token" not in item
        assert "recovery_token_hash" not in item


def test_promote_admin_script_promotes_existing_user_idempotently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.scripts import promote_admin

    with _isolated_db(monkeypatch) as testing_session_local:
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

        monkeypatch.setattr(promote_admin, "get_session", get_session)
        with testing_session_local() as sess:
            sess.add(
                User(
                    email="script-admin@example.com",
                    password_hash="hash",
                    role="user",
                    status="active",
                )
            )
            sess.commit()

        first = promote_admin.promote_admin_by_email(" script-admin@example.com ")
        second = promote_admin.promote_admin_by_email("script-admin@example.com")

        assert first["changed"] is True
        assert first["role"] == "admin"
        assert second["changed"] is False
        assert second["role"] == "admin"
        with testing_session_local() as sess:
            user = sess.query(User).filter(User.email == "script-admin@example.com").one()
            assert user.role == "admin"


def test_promote_admin_script_rejects_missing_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.scripts import promote_admin

    with _isolated_db(monkeypatch) as testing_session_local:
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

        monkeypatch.setattr(promote_admin, "get_session", get_session)
        with pytest.raises(promote_admin.PromoteAdminError):
            promote_admin.promote_admin_by_email("missing-admin@example.com")
