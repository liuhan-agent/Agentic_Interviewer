from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

from app.services import resume_parse_jobs
from app.services.resume_parse_jobs import ResumeParseJobManager


def _parsed_resume() -> SimpleNamespace:
    return SimpleNamespace(
        candidate_name="Alex Chen",
        candidate_profile={},
        summary="Backend engineer.",
        skills=["Redis"],
        highlights=["Built Redis systems."],
        projects=[],
        focus_areas=[],
        concerns=[],
        parse_status={"mode": "basic", "reason": "heuristic"},
    )


def _wait_completed(manager: ResumeParseJobManager, job_id: str) -> dict[str, Any]:
    for _ in range(50):
        snapshot = manager.get(job_id)
        if snapshot["status"] != "running":
            return snapshot
        time.sleep(0.02)
    raise AssertionError("resume parse job did not finish")


def test_resume_parse_job_result_includes_resume_source_id(monkeypatch) -> None:
    manager = ResumeParseJobManager()
    monkeypatch.setattr(
        resume_parse_jobs,
        "create_resume_parse_artifact",
        lambda **_kwargs: SimpleNamespace(
            artifact_id="artifact-job-1",
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        ),
    )

    created = manager.create(
        filename="resume.txt",
        content_type="text/plain",
        raw=b"ignored",
        llm_override=None,
        extract_text_fn=lambda **_kwargs: "Alex Redis",
        parse_resume_fn=lambda *_args, **_kwargs: _parsed_resume(),
        get_cache_fn=lambda: None,
    )
    snapshot = _wait_completed(manager, created["job_id"])

    assert snapshot["status"] == "completed"
    assert snapshot["result"]["resume_source_id"] == "artifact-job-1"
    assert snapshot["result"]["resume_source_expires_at"]


def test_resume_parse_job_cache_hit_still_creates_artifact(monkeypatch) -> None:
    manager = ResumeParseJobManager()
    monkeypatch.setattr(
        resume_parse_jobs,
        "create_resume_parse_artifact",
        lambda **_kwargs: SimpleNamespace(
            artifact_id="artifact-cache-1",
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        ),
    )

    class _Cache:
        def get(self, _key):
            return SimpleNamespace(
                payload={
                    "summary": "Cached resume.",
                    "parse_status": {"mode": "basic"},
                },
                age_ms=123,
            )

    snapshot = manager.create(
        filename="resume.txt",
        content_type="text/plain",
        raw=b"ignored",
        llm_override=None,
        extract_text_fn=lambda **_kwargs: "Alex Redis",
        parse_resume_fn=lambda *_args, **_kwargs: _parsed_resume(),
        cache_key_fn=lambda **_kwargs: "cache-key",
        get_cache_fn=lambda: _Cache(),
    )

    assert snapshot["status"] == "completed"
    assert snapshot["result"]["resume_source_id"] == "artifact-cache-1"
    assert snapshot["result"]["resume_source_expires_at"]
