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

from app.api.v1 import interview as interview_api
from app.core.session_auth import hash_recovery_token, hash_session_token
from app.models.base import Base
from app.models.interview_session import InterviewSession


def _payload() -> dict[str, Any]:
    return {
        "candidate": {
            "name": "王同学",
            "resume_parsed": {
                "summary": "三年后端开发经验",
                "skills": ["python", "fastapi"],
                "highlights": ["负责过面试系统"],
            },
        },
        "job_spec": {
            "title": "后端开发工程师",
            "level": "mid",
            "required_skills": ["python", "api"],
            "rubric_dimensions": ["technical_depth", "system_design"],
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

    monkeypatch.setattr(interview_api, "get_db_session", get_session, raising=False)
    yield testing_session_local


class _StartManager:
    def __init__(self) -> None:
        self.started: dict[str, Any] | None = None

    def session_exists(self, session_id: str) -> bool:
        return False

    def start(self, session_id: str, trace_id: str, initial: dict[str, Any], **kwargs: Any):
        self.started = {
            "session_id": session_id,
            "trace_id": trace_id,
            "initial": initial,
            **kwargs,
        }
        return object()


class _ExpiredHandle:
    trace_id = "trace-expired"
    session_token_hash = hash_session_token("expired-secret")
    session_token_expires_at = datetime.now(UTC) - timedelta(seconds=1)


class _ExpiredManager:
    def get(self, session_id: str) -> _ExpiredHandle | None:
        return _ExpiredHandle() if session_id == "sess-expired" else None


def _client_with_manager(monkeypatch: pytest.MonkeyPatch, manager: Any) -> TestClient:
    monkeypatch.setattr(interview_api, "get_session_manager", lambda: manager)
    app = FastAPI()
    app.include_router(interview_api.router)
    return TestClient(app)


def _seed_recoverable_session(
    testing_session_local,
    *,
    recovery_token: str = "recover-secret-123",
    recovery_expires_at: datetime | None = None,
    revoked_at: datetime | None = None,
) -> None:
    now = datetime.now(UTC)
    with testing_session_local() as sess:
        sess.add(
            InterviewSession(
                session_id="sess-recover",
                trace_id="trace-recover",
                session_token_hash=hash_session_token("old-secret"),
                session_token_expires_at=now - timedelta(minutes=1),
                recovery_token_hash=hash_recovery_token(recovery_token),
                recovery_token_expires_at=recovery_expires_at
                or now + timedelta(days=1),
                recovery_token_revoked_at=revoked_at,
                candidate_name="王同学",
                job_title="后端开发工程师",
                job_level="mid",
                mode="mixed",
                status="interrupted",
                created_at=now,
                updated_at=now,
            )
        )
        sess.commit()


def test_start_session_returns_recovery_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = _StartManager()
    client = _client_with_manager(monkeypatch, manager)

    resp = client.post("/api/v1/interview/sessions", json=_payload())

    assert resp.status_code == 200
    body = resp.json()
    assert body["session_token"]
    assert body["session_token_expires_at"]
    assert body["recovery_token"]
    assert body["recovery_token_expires_at"]
    assert manager.started is not None
    assert manager.started["session_token_hash"]
    assert manager.started["session_token_expires_at"]
    assert manager.started["recovery_token_hash"]
    assert manager.started["recovery_token_expires_at"]


def test_recover_session_returns_fresh_session_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _isolated_db(monkeypatch) as testing_session_local:
        _seed_recoverable_session(testing_session_local)
        client = _client_with_manager(monkeypatch, _StartManager())

        resp = client.post(
            "/api/v1/interview/sessions/sess-recover/recover",
            json={"recovery_token": "recover-secret-123"},
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["session_id"] == "sess-recover"
        assert body["session_token"]
        assert body["session_token"] != "old-secret"
        assert body["session_token_expires_at"]
        with testing_session_local() as sess:
            row = sess.get(InterviewSession, "sess-recover")
            assert row is not None
            assert row.session_token_hash == hash_session_token(body["session_token"])
            expires_at = row.session_token_expires_at
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=UTC)
            assert expires_at > datetime.now(UTC)


@pytest.mark.parametrize(
    ("kwargs", "token"),
    [
        (
            {"recovery_expires_at": datetime.now(UTC) - timedelta(seconds=1)},
            "recover-secret-123",
        ),
        ({"revoked_at": datetime.now(UTC)}, "recover-secret-123"),
        ({}, "wrong-secret-123"),
    ],
)
def test_recover_session_rejects_invalid_recovery_token_without_detail(
    monkeypatch: pytest.MonkeyPatch,
    kwargs: dict[str, Any],
    token: str,
) -> None:
    with _isolated_db(monkeypatch) as testing_session_local:
        _seed_recoverable_session(testing_session_local, **kwargs)
        client = _client_with_manager(monkeypatch, _StartManager())

        resp = client.post(
            "/api/v1/interview/sessions/sess-recover/recover",
            json={"recovery_token": token},
        )

        assert resp.status_code == 401
        assert resp.json()["detail"] == "invalid recovery token"


def test_expired_session_token_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client_with_manager(monkeypatch, _ExpiredManager())

    resp = client.get(
        "/api/v1/interview/sessions/sess-expired/question",
        headers={"X-Session-Token": "expired-secret"},
    )

    assert resp.status_code == 401
    assert resp.json()["detail"] == "session token expired"
