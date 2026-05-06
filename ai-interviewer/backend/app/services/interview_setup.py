from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass
from typing import Any, Callable

from app.engine.agents.security import check_user_context
from app.services.jd_parser import all_dimension_options, dimension_label, parse_job_spec
from app.services.job_directions import list_interview_directions
from app.services.job_templates import get_job_template
from app.services.resume_parse_cache import (
    get_resume_parse_cache,
    resume_parse_cache_key,
    should_cache_resume_parse,
)
from app.services.resume_parser import (
    EXTRACT_TEXT_TIMEOUT_SECONDS,
    ResumeParseError,
    extract_text_with_timeout,
    parse_resume,
)
from app.services.session_manager import temporary_llm_override


class ResumeTextExtractionError(Exception):
    def __init__(self, original: Exception) -> None:
        super().__init__(str(original))
        self.original = original


@dataclass(frozen=True)
class ResumeSetupParseResult:
    payload: dict[str, Any]
    text: str
    cache_key: str
    cached: bool
    cache_age_ms: int | None = None


def resume_parse_payload(parsed: Any, text: str) -> dict[str, Any]:
    return {
        "candidate_name": parsed.candidate_name,
        "candidate_profile": parsed.candidate_profile,
        "summary": parsed.summary,
        "skills": parsed.skills,
        "highlights": parsed.highlights,
        "projects": parsed.projects,
        "focus_areas": parsed.focus_areas,
        "concerns": parsed.concerns,
        "raw_text_preview": text[:2000],
        "parse_status": parsed.parse_status,
        "context_flags": check_user_context(text, source="resume").categories,
    }


def parse_resume_setup_upload(
    *,
    filename: str | None,
    content_type: str | None,
    raw: bytes,
    llm_override: dict[str, Any] | None,
    extract_text_fn: Callable[..., str] = extract_text_with_timeout,
    parse_resume_fn: Callable[..., Any] = parse_resume,
    get_cache_fn: Callable[[], Any] = get_resume_parse_cache,
    cache_key_fn: Callable[..., str] = resume_parse_cache_key,
    should_cache_fn: Callable[[dict[str, Any]], bool] = should_cache_resume_parse,
    timeout_seconds: float = EXTRACT_TEXT_TIMEOUT_SECONDS,
) -> ResumeSetupParseResult:
    try:
        text = extract_text_fn(
            filename=filename,
            content_type=content_type,
            data=raw,
            timeout_seconds=timeout_seconds,
        )
    except ResumeParseError:
        raise
    except Exception as e:
        raise ResumeTextExtractionError(e) from e
    cache_key = cache_key_fn(
        text=text,
        filename=filename,
        llm_override=llm_override,
    )
    cache = get_cache_fn()
    if cache is not None:
        hit = cache.get(cache_key)
        if hit is not None:
            payload = dict(hit.payload)
            status = payload.get("parse_status")
            if isinstance(status, dict):
                payload["parse_status"] = {
                    **status,
                    "cached": True,
                    "cache_age_ms": hit.age_ms,
                }
            payload["raw_text_preview"] = text[:2000]
            return ResumeSetupParseResult(
                payload=payload,
                text=text,
                cache_key=cache_key,
                cached=True,
                cache_age_ms=hit.age_ms,
            )

    context = temporary_llm_override(llm_override) if llm_override else nullcontext()
    with context:
        if llm_override:
            parsed = parse_resume_fn(text, force_llm=True, filename=filename)
        else:
            parsed = parse_resume_fn(text, filename=filename)
    payload = resume_parse_payload(parsed, text)
    if cache is not None and should_cache_fn(payload):
        cache.set(cache_key, payload)
    return ResumeSetupParseResult(
        payload=payload,
        text=text,
        cache_key=cache_key,
        cached=False,
    )


def parse_jd_setup_payload(
    *,
    text: str,
    direction: str | None,
    title: str | None,
    level: str | None,
    llm_override: dict[str, Any] | None,
    parse_job_spec_fn: Callable[..., Any] = parse_job_spec,
) -> dict[str, Any]:
    with temporary_llm_override(llm_override):
        parsed = parse_job_spec_fn(
            text,
            direction=direction,
            title=title,
            level=level,
            force_llm=bool(llm_override),
        )
    context_flags = check_user_context(text, source="jd").categories
    return {
        "required_skills": parsed.required_skills,
        "rubric_dimensions": parsed.rubric_dimensions,
        "rubric_dimension_labels": [
            {"id": dimension, "label": dimension_label(dimension)}
            for dimension in parsed.rubric_dimensions
        ],
        "suggested_level": parsed.suggested_level,
        "rationale": parsed.rationale,
        "unmapped_requirements": parsed.unmapped_requirements or [],
        "context_flags": context_flags,
    }


def list_dimensions_payload() -> dict[str, Any]:
    return {"dimensions": all_dimension_options()}


def list_directions_payload() -> dict[str, Any]:
    return {
        "directions": [
            direction.to_api_dict() for direction in list_interview_directions()
        ]
    }


def default_job_template_payload(direction: str, level: str | None = None) -> dict[str, Any]:
    template = get_job_template(direction)
    return template.to_api_dict(level=level)
