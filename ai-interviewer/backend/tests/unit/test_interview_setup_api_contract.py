from __future__ import annotations

import io
from types import SimpleNamespace
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1 import interview as interview_api
from app.services.jd_parser import JDParseError


def _client(monkeypatch) -> TestClient:
    monkeypatch.setattr(
        interview_api,
        "_enforce_setup_rate_limit",
        lambda *_args, **_kwargs: None,
    )
    app = FastAPI()
    app.include_router(interview_api.router)
    return TestClient(app)


def test_resume_parse_upload_response_contract(monkeypatch) -> None:
    http = _client(monkeypatch)
    calls: dict[str, Any] = {}

    def fake_extract_text_with_timeout(**kwargs):
        calls["extract"] = kwargs
        return "Alex Chen\nPython Kafka Redis"

    def fake_parse_resume(text: str, **kwargs):
        calls["parse"] = {"text": text, **kwargs}
        return SimpleNamespace(
            candidate_name="Alex Chen",
            candidate_profile={"current_role": "Backend Engineer"},
            summary="Backend engineer with platform experience.",
            skills=["python", "kafka", "redis"],
            highlights=["Led a streaming migration."],
            projects=[
                {
                    "id": "p1",
                    "name": "Streaming Platform",
                    "role": "Owner",
                    "tech_stack": ["Kafka"],
                    "responsibilities": ["Designed ingestion flow"],
                    "achievements": ["Reduced lag"],
                    "question_anchors": ["backpressure"],
                }
            ],
            focus_areas=[
                {
                    "id": "f1",
                    "label": "Streaming reliability",
                    "project_id": "p1",
                    "dimensions": ["system_design"],
                    "skills": ["kafka"],
                    "priority": 1,
                }
            ],
            concerns=["Needs more capacity detail."],
            parse_status={
                "mode": "basic",
                "reason": "heuristic",
                "elapsed_ms": 12,
                "text_chars": 29,
            },
        )

    monkeypatch.setattr(interview_api, "extract_text_with_timeout", fake_extract_text_with_timeout)
    monkeypatch.setattr(interview_api, "parse_resume", fake_parse_resume)
    monkeypatch.setattr(interview_api, "get_resume_parse_cache", lambda: None)

    resp = http.post(
        "/api/v1/interview/resume/parse",
        files={"file": ("resume.txt", io.BytesIO(b"ignored"), "text/plain")},
    )

    assert resp.status_code == 200
    assert calls["extract"]["filename"] == "resume.txt"
    assert calls["extract"]["content_type"] == "text/plain"
    assert calls["extract"]["timeout_seconds"] == interview_api.EXTRACT_TEXT_TIMEOUT_SECONDS
    assert calls["parse"] == {
        "text": "Alex Chen\nPython Kafka Redis",
        "filename": "resume.txt",
    }
    assert resp.json() == {
        "candidate_name": "Alex Chen",
        "candidate_profile": {"current_role": "Backend Engineer"},
        "summary": "Backend engineer with platform experience.",
        "skills": ["python", "kafka", "redis"],
        "highlights": ["Led a streaming migration."],
        "projects": [
            {
                "id": "p1",
                "name": "Streaming Platform",
                "role": "Owner",
                "tech_stack": ["Kafka"],
                "responsibilities": ["Designed ingestion flow"],
                "achievements": ["Reduced lag"],
                "question_anchors": ["backpressure"],
            }
        ],
        "focus_areas": [
            {
                "id": "f1",
                "label": "Streaming reliability",
                "project_id": "p1",
                "dimensions": ["system_design"],
                "skills": ["kafka"],
                "priority": 1,
            }
        ],
        "concerns": ["Needs more capacity detail."],
        "raw_text_preview": "Alex Chen\nPython Kafka Redis",
        "parse_status": {
            "mode": "basic",
            "reason": "heuristic",
            "elapsed_ms": 12,
            "text_chars": 29,
        },
        "context_flags": [],
    }


def test_resume_parse_upload_domain_error_contract(monkeypatch) -> None:
    http = _client(monkeypatch)

    def fail_extract_text_with_timeout(**_kwargs):
        raise interview_api.ResumeParseError("unsupported resume format")

    monkeypatch.setattr(interview_api, "extract_text_with_timeout", fail_extract_text_with_timeout)

    resp = http.post(
        "/api/v1/interview/resume/parse",
        files={"file": ("resume.zip", io.BytesIO(b"PK"), "application/zip")},
    )

    assert resp.status_code == 415
    assert resp.json()["detail"] == {
        "code": "resume_file_unsupported",
        "message": "unsupported resume format",
        "action": "upload_supported_format",
    }


def test_jd_parse_response_contract(monkeypatch) -> None:
    http = _client(monkeypatch)
    calls: dict[str, Any] = {}

    def fake_parse_job_spec(text: str, **kwargs):
        calls["parse"] = {"text": text, **kwargs}
        return SimpleNamespace(
            required_skills=["java", "redis"],
            rubric_dimensions=["technical_depth", "system_design"],
            suggested_level="senior",
            rationale="JD mentions backend ownership and architecture.",
            unmapped_requirements=["GraphQL"],
        )

    monkeypatch.setattr(interview_api, "parse_job_spec", fake_parse_job_spec)

    resp = http.post(
        "/api/v1/interview/jd/parse",
        json={
            "text": "Own Java backend systems and Redis reliability.",
            "direction": "java_backend",
            "title": "Senior Backend Engineer",
            "level": "senior",
        },
    )

    assert resp.status_code == 200
    assert calls["parse"] == {
        "text": "Own Java backend systems and Redis reliability.",
        "direction": "java_backend",
        "title": "Senior Backend Engineer",
        "level": "senior",
        "force_llm": False,
    }
    assert resp.json() == {
        "required_skills": ["java", "redis"],
        "rubric_dimensions": ["technical_depth", "system_design"],
        "rubric_dimension_labels": [
            {"id": "technical_depth", "label": "技术深度"},
            {"id": "system_design", "label": "系统设计"},
        ],
        "suggested_level": "senior",
        "rationale": "JD mentions backend ownership and architecture.",
        "unmapped_requirements": ["GraphQL"],
        "context_flags": [],
    }


def test_jd_parse_domain_error_contract(monkeypatch) -> None:
    http = _client(monkeypatch)

    def fail_parse_job_spec(*_args, **_kwargs):
        raise JDParseError("empty job description")

    monkeypatch.setattr(interview_api, "parse_job_spec", fail_parse_job_spec)

    resp = http.post("/api/v1/interview/jd/parse", json={"text": "   "})

    assert resp.status_code == 422
    assert resp.json()["detail"] == {
        "code": "jd_empty",
        "message": "岗位要求为空，请补充后再试。",
        "action": "edit_jd",
    }


def test_catalog_endpoint_contracts(monkeypatch) -> None:
    http = _client(monkeypatch)

    dimensions = http.get("/api/v1/interview/dimensions")
    assert dimensions.status_code == 200
    assert "dimensions" in dimensions.json()
    assert {"id", "label"} <= set(dimensions.json()["dimensions"][0])

    directions = http.get("/api/v1/interview/directions")
    assert directions.status_code == 200
    assert "directions" in directions.json()
    assert {"direction", "label", "industry"} <= set(directions.json()["directions"][0])

    waiting_tips = http.get("/api/v1/interview/waiting-tips")
    assert waiting_tips.status_code == 200
    waiting_tips_payload = waiting_tips.json()
    assert waiting_tips_payload["rotation_interval_ms"] == 10_000
    assert waiting_tips_payload["version"]
    assert {"id", "scope", "text"} <= set(waiting_tips_payload["tips"][0])
    waiting_tip_scopes = {tip["scope"] for tip in waiting_tips_payload["tips"]}
    assert {"default", "self_intro", "final", "problem_solving"} <= waiting_tip_scopes

    template = http.get(
        "/api/v1/interview/job-template",
        params={"direction": "java_backend", "level": "junior"},
    )
    assert template.status_code == 200
    assert {
        "direction",
        "level",
        "title",
        "template",
        "skills",
        "rubric_dimensions",
    } <= set(template.json())

    missing = http.get(
        "/api/v1/interview/job-template",
        params={"direction": "missing_direction"},
    )
    assert missing.status_code == 404
    assert missing.json()["detail"] == "Job template not found"
