from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.v1 import interview as interview_api
from app.models.base import Base
from app.models.generation_trace import GenerationTrace
from app.models.interview_session import InterviewSession
from app.models.outcome_record import OutcomeRecord
from app.services import privacy_cleanup

_DEFAULT_CHECKPOINT = object()


class _Manager:
    def __init__(self, *, active: bool = False) -> None:
        self.active = active
        self.cancelled: list[str] = []
        self.removed: list[str] = []

    def get(self, session_id: str) -> object | None:
        return object() if self.active and session_id == "sess-delete" else None

    def cancel(self, session_id: str, *, join_timeout: float = 5.0) -> bool:
        self.cancelled.append(session_id)
        return self.active

    def remove(self, session_id: str) -> None:
        self.removed.append(session_id)


def _client(
    monkeypatch: pytest.MonkeyPatch,
    manager: _Manager,
    *,
    checkpoint: object = _DEFAULT_CHECKPOINT,
) -> TestClient:
    monkeypatch.setattr(interview_api, "get_session_manager", lambda: manager)
    if checkpoint is _DEFAULT_CHECKPOINT:
        monkeypatch.setattr(
            interview_api,
            "_delete_checkpoint_thread",
            lambda _session_id: True,
            raising=False,
        )
    else:
        monkeypatch.setattr(
            interview_api,
            "_delete_checkpoint_thread",
            checkpoint,
            raising=False,
        )
    app = FastAPI()
    app.include_router(interview_api.router)
    return TestClient(app)


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
    monkeypatch.setattr(privacy_cleanup, "get_db_session", get_session, raising=False)
    yield testing_session_local


def _seed_session(testing_session_local, session_id: str = "sess-delete") -> None:
    now = datetime.now(UTC)
    with testing_session_local() as sess:
        sess.add(
            InterviewSession(
                session_id=session_id,
                trace_id="trace-delete",
                candidate_name="刘韩",
                job_title="Java 后端",
                job_level="junior",
                mode="mixed",
                status="completed",
                final_report={"ok": True},
                current_question=None,
                turn_idx=1,
                asked_turn=0,
                created_at=now,
                updated_at=now,
            )
        )
        sess.add(
            GenerationTrace(
                trace_id="trace-delete",
                session_id=session_id,
                turn_idx=0,
                node="ask_question",
                dimension="technical_depth",
                action_id="simple",
                policy_id=None,
                context_key=None,
                policy_context_keys=None,
                score=None,
                passed=None,
                immediate_reward=None,
                delayed_reward=None,
                applied_to_bandit=False,
                immediate_reward_applied=False,
                state_snapshot={},
                question="Q",
                answer=None,
                evaluation=None,
                langsmith_run_id=None,
            )
        )
        sess.add(
            OutcomeRecord(
                session_id=session_id,
                outcome="hired",
                performance_score=0.8,
                notes="demo",
            )
        )
        sess.commit()


def _counts(testing_session_local, session_id: str = "sess-delete") -> dict[str, Any]:
    with testing_session_local() as sess:
        return {
            "session": sess.get(InterviewSession, session_id) is not None,
            "traces": sess.query(GenerationTrace)
            .filter(GenerationTrace.session_id == session_id)
            .count(),
            "outcome": sess.get(OutcomeRecord, session_id) is not None,
        }


def test_delete_session_requires_matching_confirm_id(monkeypatch: pytest.MonkeyPatch):
    client = _client(monkeypatch, _Manager())

    missing = client.delete("/api/v1/interview/sessions/sess-delete")
    mismatch = client.delete(
        "/api/v1/interview/sessions/sess-delete?confirm_session_id=other"
    )

    assert missing.status_code == 400
    assert mismatch.status_code == 400


def test_delete_session_hard_deletes_persisted_rows(monkeypatch: pytest.MonkeyPatch):
    with _isolated_db(monkeypatch) as testing_session_local:
        _seed_session(testing_session_local)
        client = _client(monkeypatch, _Manager())

        resp = client.delete(
            "/api/v1/interview/sessions/sess-delete"
            "?confirm_session_id=sess-delete"
        )

        assert resp.status_code == 200
        assert resp.json() == {
            "session_id": "sess-delete",
            "deleted": True,
            "sessions_deleted": 1,
            "traces_deleted": 1,
            "outcomes_deleted": 1,
            "outcome_deleted": True,
            "checkpoint_deleted": True,
        }
        assert _counts(testing_session_local) == {
            "session": False,
            "traces": 0,
            "outcome": False,
        }


def test_delete_session_is_idempotent_when_rows_are_missing(
    monkeypatch: pytest.MonkeyPatch,
):
    with _isolated_db(monkeypatch):
        client = _client(monkeypatch, _Manager())

        resp = client.delete(
            "/api/v1/interview/sessions/sess-missing"
            "?confirm_session_id=sess-missing"
        )

        assert resp.status_code == 200
        assert resp.json() == {
            "session_id": "sess-missing",
            "deleted": False,
            "sessions_deleted": 0,
            "traces_deleted": 0,
            "outcomes_deleted": 0,
            "outcome_deleted": False,
            "checkpoint_deleted": True,
        }


def test_delete_session_cancels_and_removes_active_handle(
    monkeypatch: pytest.MonkeyPatch,
):
    with _isolated_db(monkeypatch):
        manager = _Manager(active=True)
        client = _client(monkeypatch, manager)

        resp = client.delete(
            "/api/v1/interview/sessions/sess-delete"
            "?confirm_session_id=sess-delete"
        )

        assert resp.status_code == 200
        assert manager.cancelled == ["sess-delete"]
        assert manager.removed == ["sess-delete"]


def test_delete_session_tolerates_checkpoint_delete_failure(
    monkeypatch: pytest.MonkeyPatch,
):
    def fail_checkpoint(_session_id: str) -> bool:
        raise RuntimeError("checkpoint unavailable")

    with _isolated_db(monkeypatch) as testing_session_local:
        _seed_session(testing_session_local)
        client = _client(monkeypatch, _Manager(), checkpoint=fail_checkpoint)

        resp = client.delete(
            "/api/v1/interview/sessions/sess-delete"
            "?confirm_session_id=sess-delete"
        )

        assert resp.status_code == 200
        assert resp.json()["deleted"] is True
        assert resp.json()["checkpoint_deleted"] is False
