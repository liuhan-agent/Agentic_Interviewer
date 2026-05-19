from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1 import admin as admin_api


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(admin_api.router)
    app.include_router(admin_api.api_v1_router)
    return TestClient(app)


def test_admin_knowledge_coverage_counts_only_ingestible_files(
    tmp_path: Path, monkeypatch
) -> None:
    (tmp_path / "business_questions").mkdir()
    (tmp_path / "tech_questions").mkdir()
    (tmp_path / "behavioral_questions").mkdir()
    (tmp_path / "sample_resumes").mkdir()
    (tmp_path / "strategy").mkdir()
    (tmp_path / "skills").mkdir()
    (tmp_path / "business_questions" / "sales.md").write_text(
        "S" * 700, encoding="utf-8"
    )
    (tmp_path / "tech_questions" / "backend.md").write_text("backend", encoding="utf-8")
    (tmp_path / "behavioral_questions" / "communication.md").write_text(
        "behavioral", encoding="utf-8"
    )
    (tmp_path / "sample_resumes" / "alex.md").write_text("resume", encoding="utf-8")
    (tmp_path / "strategy" / "interview_strategy.md").write_text(
        "strategy", encoding="utf-8"
    )
    (tmp_path / "strategy" / ".dream_state.json").write_text("{}", encoding="utf-8")
    (tmp_path / "skills" / "interview_skill.md").write_text(
        "skill", encoding="utf-8"
    )
    (tmp_path / "interview_directions.json").write_text("{}", encoding="utf-8")
    (tmp_path / "job_templates.json").write_text("{}", encoding="utf-8")

    monkeypatch.setattr(
        admin_api,
        "get_settings",
        lambda: SimpleNamespace(
            api_token=None,
            allow_open_admin=True,
            knowledge_dir=tmp_path,
        ),
    )

    response = _client().get("/api/v1/admin/knowledge/coverage")

    assert response.status_code == 200
    payload = response.json()
    assert payload == {"by_source_type": {}, "total_files": 0, "total_chunks": 0}


def test_admin_knowledge_coverage_requires_admin_token(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(
        admin_api,
        "get_settings",
        lambda: SimpleNamespace(
            api_token="secret-abc",
            allow_open_admin=False,
            knowledge_dir=tmp_path,
        ),
    )

    client = _client()

    missing = client.get("/api/v1/admin/knowledge/coverage")
    assert missing.status_code == 401

    ok = client.get(
        "/api/v1/admin/knowledge/coverage",
        headers={"Authorization": "Bearer secret-abc"},
    )
    assert ok.status_code == 200
    assert ok.json() == {"by_source_type": {}, "total_files": 0, "total_chunks": 0}

    legacy = client.get(
        "/admin/knowledge/coverage",
        headers={"Authorization": "Bearer secret-abc"},
    )
    assert legacy.status_code == 200
