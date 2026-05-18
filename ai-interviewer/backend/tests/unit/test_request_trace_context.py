"""Request-level trace context tests."""
from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1 import interview as interview_api
from app.core.request_context import install_request_context_middleware


class _FakeManager:
    def __init__(self) -> None:
        self.started: list[tuple[str, str, dict[str, Any]]] = []
        self.llm_configs: list[dict[str, Any] | None] = []
        self.session_token_hashes: list[str | None] = []
        self.setup_snapshots: list[dict[str, Any] | None] = []
        self.existing_sessions: set[str] = set()

    def start(
        self,
        session_id: str,
        trace_id: str,
        initial: dict[str, Any],
        *,
        llm_config: dict[str, Any] | None = None,
        session_token_hash: str | None = None,
        session_token_expires_at: Any = None,
        recovery_token_hash: str | None = None,
        recovery_token_expires_at: Any = None,
        setup_snapshot: dict[str, Any] | None = None,
    ) -> None:
        self.started.append((session_id, trace_id, initial))
        self.llm_configs.append(llm_config)
        self.session_token_hashes.append(session_token_hash)
        self.setup_snapshots.append(setup_snapshot)

    def session_exists(self, session_id: str) -> bool:
        return session_id in self.existing_sessions


def _client_with_fake_manager(monkeypatch) -> tuple[TestClient, _FakeManager]:
    manager = _FakeManager()
    monkeypatch.setattr(interview_api, "get_session_manager", lambda: manager)
    app = FastAPI()
    install_request_context_middleware(app)
    app.include_router(interview_api.router)
    return TestClient(app), manager


def _payload(**extra: Any) -> dict[str, Any]:
    return {
        "candidate": {"name": "Ada"},
        "job_spec": {"title": "Backend Engineer", "level": "senior"},
        **extra,
    }


def test_start_session_uses_traceparent_trace_id(monkeypatch) -> None:
    client, manager = _client_with_fake_manager(monkeypatch)
    trace_id = "0123456789abcdef0123456789abcdef"
    resp = client.post(
        "/api/v1/interview/sessions",
        json=_payload(),
        headers={"traceparent": f"00-{trace_id}-0123456789abcdef-01"},
    )

    assert resp.status_code == 200
    assert resp.json()["trace_id"] == trace_id
    assert manager.started[0][1] == trace_id


def test_start_session_returns_session_token_and_stores_hash(monkeypatch) -> None:
    client, manager = _client_with_fake_manager(monkeypatch)

    resp = client.post("/api/v1/interview/sessions", json=_payload())

    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body["session_token"], str)
    assert len(body["session_token"]) >= 32
    assert manager.session_token_hashes[0]
    assert manager.session_token_hashes[0] != body["session_token"]


def test_start_session_returns_video_capability(monkeypatch) -> None:
    client, manager = _client_with_fake_manager(monkeypatch)

    resp = client.post(
        "/api/v1/interview/sessions",
        json=_payload(enable_video_analysis=True),
    )

    assert resp.status_code == 200
    assert resp.json()["enable_video_analysis"] is True
    assert manager.started[0][2]["runtime_config"]["enable_video_analysis"] is True


def test_start_session_passes_sanitized_setup_snapshot(monkeypatch) -> None:
    client, manager = _client_with_fake_manager(monkeypatch)

    resp = client.post(
        "/api/v1/interview/sessions",
        json=_payload(
            candidate={
                "name": "Ada",
                "resume_parsed": {
                    "summary": "Built payment systems.",
                    "skills": ["Python", "Redis"],
                    "candidate_profile": {
                        "suggested_job_title": "Backend Engineer",
                        "suggested_job_level": "senior",
                    },
                },
            },
            job_spec={
                "title": "Backend Engineer",
                "level": "senior",
                "required_skills": ["Python"],
                "rubric_dimensions": ["system_design"],
                "interview_direction": "java_backend",
                "interview_industry": "internet",
            },
            llm_config={
                "provider": "qwen",
                "api_key": "secret-key",
                "model": "qwen3.6-flash",
            },
        ),
    )

    assert resp.status_code == 200
    assert manager.setup_snapshots == [
        {
            "candidate": {
                "name": "Ada",
                "resume_parsed": {
                    "summary": "Built payment systems.",
                    "skills": ["Python", "Redis"],
                    "highlights": [],
                    "projects": [],
                    "focus_areas": [],
                    "concerns": [],
                    "candidate_profile": {
                        "suggested_job_title": "Backend Engineer",
                        "suggested_job_level": "senior",
                    },
                },
            },
            "job_spec": {
                "title": "Backend Engineer",
                "level": "senior",
                "required_skills": ["Python"],
                "rubric_dimensions": ["system_design"],
                "rubric": {},
                "interview_industry": "internet",
                "interview_direction": "java_backend",
                "interview_direction_label": None,
            },
            "resume_vector_status": {
                "status": "skipped",
                "skipped_reason": "no_parse_artifact",
                "resume_source_id": None,
                "resume_revision_id": None,
            },
        }
    ]
    assert "llm_config" not in manager.setup_snapshots[0]
    assert "api_key" not in str(manager.setup_snapshots[0])


def test_explicit_body_trace_id_overrides_traceparent(monkeypatch) -> None:
    client, manager = _client_with_fake_manager(monkeypatch)
    header_trace = "0123456789abcdef0123456789abcdef"
    resp = client.post(
        "/api/v1/interview/sessions",
        json=_payload(trace_id="trace-body"),
        headers={"traceparent": f"00-{header_trace}-0123456789abcdef-01"},
    )

    assert resp.status_code == 200
    assert resp.json()["trace_id"] == "trace-body"
    assert manager.started[0][1] == "trace-body"


def test_start_session_accepts_safe_explicit_ids(monkeypatch) -> None:
    client, manager = _client_with_fake_manager(monkeypatch)

    resp = client.post(
        "/api/v1/interview/sessions",
        json=_payload(
            session_id="sess.custom-1:blue_ok",
            trace_id="trace.custom-1:blue_ok",
        ),
    )

    assert resp.status_code == 200
    assert resp.json()["session_id"] == "sess.custom-1:blue_ok"
    assert resp.json()["trace_id"] == "trace.custom-1:blue_ok"
    assert manager.started[0][0] == "sess.custom-1:blue_ok"
    assert manager.started[0][1] == "trace.custom-1:blue_ok"


def test_start_session_rejects_duplicate_session_id(monkeypatch) -> None:
    client, manager = _client_with_fake_manager(monkeypatch)
    manager.existing_sessions.add("sess-existing")

    resp = client.post(
        "/api/v1/interview/sessions",
        json=_payload(session_id="sess-existing"),
    )

    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "session_id_conflict"
    assert manager.started == []


@pytest.mark.parametrize(
    "payload",
    [
        _payload(candidate={"name": "Ada", "unexpected": "ignore me"}),
        _payload(
            candidate={
                "name": "Ada",
                "resume_parsed": {"summary": "ok", "unexpected": "ignore me"},
            },
        ),
        _payload(job_spec={"title": "Backend Engineer", "level": "senior", "unexpected": "x"}),
    ],
)
def test_start_session_rejects_unknown_external_fields(monkeypatch, payload) -> None:
    client, manager = _client_with_fake_manager(monkeypatch)

    resp = client.post("/api/v1/interview/sessions", json=payload)

    assert resp.status_code == 422
    assert manager.started == []


@pytest.mark.parametrize(
    "resume_parsed",
    [
        {"summary": "x" * 1201},
        {"skills": ["python"] * 41},
        {"skills": ["x" * 81]},
        {"highlights": ["shipped"] * 21},
        {"projects": [{"id": f"p{i}", "name": f"Project {i}"} for i in range(13)]},
        {
            "projects": [
                {
                    "id": "p1",
                    "name": "Project",
                    "question_anchors": ["x" * 161],
                }
            ]
        },
        {"focus_areas": [{"id": f"f{i}", "label": f"Focus {i}"} for i in range(21)]},
    ],
)
def test_start_session_rejects_oversized_resume_fields(monkeypatch, resume_parsed) -> None:
    client, manager = _client_with_fake_manager(monkeypatch)

    resp = client.post(
        "/api/v1/interview/sessions",
        json=_payload(candidate={"name": "Ada", "resume_parsed": resume_parsed}),
    )

    assert resp.status_code == 422
    assert manager.started == []


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("session_id", "x" * 65),
        ("trace_id", "x" * 65),
        ("session_id", "bad id"),
        ("trace_id", "bad\nid"),
    ],
)
def test_start_session_rejects_invalid_explicit_ids(
    monkeypatch,
    field: str,
    value: str,
) -> None:
    client, manager = _client_with_fake_manager(monkeypatch)

    resp = client.post("/api/v1/interview/sessions", json=_payload(**{field: value}))

    assert resp.status_code == 422
    assert manager.started == []


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("max_turns", 0),
        ("max_turns", 21),
        ("turn_budget", 0),
        ("turn_budget", 31),
        ("quality_threshold", -0.1),
        ("quality_threshold", 10.1),
    ],
)
def test_start_session_rejects_out_of_range_loop_controls(
    monkeypatch,
    field: str,
    value: int | float,
) -> None:
    client, manager = _client_with_fake_manager(monkeypatch)

    resp = client.post("/api/v1/interview/sessions", json=_payload(**{field: value}))

    assert resp.status_code == 422
    assert manager.started == []


def test_start_session_accepts_llm_role_overrides(monkeypatch) -> None:
    client, manager = _client_with_fake_manager(monkeypatch)

    resp = client.post(
        "/api/v1/interview/sessions",
        json=_payload(
            llm_config={
                "provider": "qwen",
                "api_key": "default-key",
                "model": "qwen3.6-flash",
                "role_overrides": {
                    "evaluator": {
                        "provider": "qwen",
                        "model": "qwen3.6-plus",
                    },
                    "verifier": {
                        "provider": "kimi",
                        "api_key": "kimi-key",
                        "model": "kimi-k2.6",
                    },
                    "resume_parser": {
                        "provider": "qwen",
                        "model": "qwen3.6-plus",
                    },
                },
            },
        ),
    )

    assert resp.status_code == 200
    assert manager.llm_configs[0] == {
        "provider": "qwen",
        "api_key": "default-key",
        "model": "qwen3.6-flash",
        "role_overrides": {
            "evaluator": {
                "provider": "qwen",
                "model": "qwen3.6-plus",
            },
            "verifier": {
                "provider": "kimi",
                "api_key": "kimi-key",
                "model": "kimi-k2.6",
            },
            "resume_parser": {
                "provider": "qwen",
                "model": "qwen3.6-plus",
            },
        },
    }


def test_start_session_rejects_unknown_llm_role_override(monkeypatch) -> None:
    client, manager = _client_with_fake_manager(monkeypatch)

    resp = client.post(
        "/api/v1/interview/sessions",
        json=_payload(
            llm_config={
                "provider": "qwen",
                "api_key": "default-key",
                "model": "qwen3.6-flash",
                "role_overrides": {
                    "unknown_role": {
                        "provider": "qwen",
                        "model": "qwen3.6-plus",
                    },
                },
            },
        ),
    )

    assert resp.status_code == 422
    assert manager.started == []


@pytest.mark.parametrize(
    "llm_config",
    [
        {
            "provider": "not-a-provider",
            "api_key": "secret-key",
            "model": "test-model",
        },
        {
            "provider": "qwen",
            "api_key": "secret-key",
            "model": "qwen3.6-flash",
            "base_url": "http://127.0.0.1:11434/v1",
        },
        {
            "provider": "qwen",
            "api_key": "secret-key",
            "model": "qwen3.6-flash",
            "role_overrides": {
                "evaluator": {
                    "provider": "not-a-provider",
                    "model": "qwen3.6-plus",
                },
            },
        },
    ],
)
def test_start_session_rejects_invalid_llm_config(monkeypatch, llm_config) -> None:
    client, manager = _client_with_fake_manager(monkeypatch)

    resp = client.post("/api/v1/interview/sessions", json=_payload(llm_config=llm_config))

    assert resp.status_code == 422
    assert manager.started == []
    assert "secret-key" not in resp.text
