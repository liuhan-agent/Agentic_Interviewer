from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1 import interview as interview_api


class _Manager:
    def __init__(self) -> None:
        self.started: list[tuple[str, str, dict[str, Any]]] = []
        self.setup_snapshots: list[dict[str, Any] | None] = []

    def start(
        self,
        session_id: str,
        trace_id: str,
        initial: dict[str, Any],
        *,
        setup_snapshot: dict[str, Any] | None = None,
        **_kwargs: Any,
    ):
        self.started.append((session_id, trace_id, initial))
        self.setup_snapshots.append(setup_snapshot)
        return SimpleNamespace(
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            last_activity_at=datetime.now(UTC),
        )

    def session_exists(self, _session_id: str) -> bool:
        return False


def _client(monkeypatch) -> tuple[TestClient, _Manager]:
    manager = _Manager()
    monkeypatch.setattr(interview_api, "get_session_manager", lambda: manager)
    app = FastAPI()
    app.include_router(interview_api.router)
    return TestClient(app), manager


def _payload(**extra: Any) -> dict[str, Any]:
    return {
        "candidate": {"name": "Alex", "resume_parsed": {"summary": "manual"}},
        "job_spec": {"title": "Backend Engineer", "level": "senior"},
        **extra,
    }


def test_start_session_binds_valid_parse_artifact_without_vectorizing(
    monkeypatch,
) -> None:
    http, manager = _client(monkeypatch)
    expires_at = datetime.now(UTC) + timedelta(hours=1)
    monkeypatch.setattr(
        interview_api,
        "read_resume_parse_artifact",
        lambda artifact_id: SimpleNamespace(
            artifact_id=artifact_id,
            expires_at=expires_at,
        ),
    )
    monkeypatch.setattr(
        interview_api,
        "vectorize_resume",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("POST /sessions must not vectorize")
        ),
        raising=False,
    )

    response = http.post(
        "/api/v1/interview/sessions",
        json=_payload(resume_source_id="artifact_1"),
    )

    assert response.status_code == 200
    candidate = manager.started[0][2]["candidate"]
    assert candidate["resume_source_id"] == "artifact_1"
    assert candidate["resume_vector_status"] == {
        "status": "pending_node",
        "resume_source_id": "artifact_1",
        "resume_revision_id": None,
        "expires_at": expires_at.isoformat(),
    }
    assert manager.setup_snapshots[0]["resume_vector_status"]["status"] == "pending_node"


def test_start_session_without_artifact_stamps_skipped_status(monkeypatch) -> None:
    http, manager = _client(monkeypatch)

    response = http.post("/api/v1/interview/sessions", json=_payload())

    assert response.status_code == 200
    candidate = manager.started[0][2]["candidate"]
    assert candidate["resume_vector_status"]["status"] == "skipped"
    assert candidate["resume_vector_status"]["skipped_reason"] == "no_parse_artifact"
    assert candidate["resume_vector_status"]["resume_source_id"] is None


def test_start_session_with_invalid_artifact_still_succeeds(monkeypatch) -> None:
    http, manager = _client(monkeypatch)
    monkeypatch.setattr(
        interview_api,
        "read_resume_parse_artifact",
        lambda _artifact_id: None,
    )

    response = http.post(
        "/api/v1/interview/sessions",
        json=_payload(resume_source_id="expired_artifact"),
    )

    assert response.status_code == 200
    candidate = manager.started[0][2]["candidate"]
    assert candidate["resume_vector_status"]["status"] == "skipped"
    assert candidate["resume_vector_status"]["skipped_reason"] == (
        "parse_artifact_missing_or_expired"
    )
    assert candidate["resume_vector_status"]["resume_source_id"] == "expired_artifact"
