"""Background resume vectorization jobs for session anchor RAG."""
from __future__ import annotations

import concurrent.futures
import secrets
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.core.logging import get_logger
from app.core.settings import get_settings
from app.services.resume_anchor_cache import (
    resume_anchor_cache_key,
    try_bind_cached_resume_anchors,
)
from app.services.resume_embedding import current_embedding_model_version
from app.services.resume_parse_artifacts import consume_resume_parse_artifact
from app.services.session_anchor_vectorize import vectorize_resume

log = get_logger(__name__)


@dataclass
class _ResumeVectorJob:
    key: tuple[str, str]
    status: dict[str, Any]
    done: threading.Event = field(default_factory=threading.Event)
    future: concurrent.futures.Future | None = None


_LOCK = threading.Lock()
_JOBS: dict[tuple[str, str], _ResumeVectorJob] = {}
_EXECUTOR = concurrent.futures.ThreadPoolExecutor(
    max_workers=max(1, int(get_settings().resume_rag_embedding_concurrency or 4)),
    thread_name_prefix="resume-vector",
)


def start_resume_vector_job(
    *,
    session_id: str,
    resume_source_id: str | None,
    parsed: dict[str, Any] | None = None,
    embedding_override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Start a deduped background vectorization job and return its status."""

    job = _ensure_job(
        session_id=session_id,
        resume_source_id=resume_source_id,
        parsed=parsed,
        embedding_override=embedding_override,
    )
    return _status_copy(job.status) if job is not None else _skipped_no_source(resume_source_id)


def wait_for_resume_vector_status(
    *,
    session_id: str,
    resume_source_id: str | None,
    parsed: dict[str, Any] | None = None,
    embedding_override: dict[str, Any] | None = None,
    timeout_ms: int | None = None,
) -> dict[str, Any]:
    """Wait briefly for a background resume vector job to finish."""

    job = _ensure_job(
        session_id=session_id,
        resume_source_id=resume_source_id,
        parsed=parsed,
        embedding_override=embedding_override,
    )
    if job is None:
        return _skipped_no_source(resume_source_id)
    timeout_seconds = max(0, int(timeout_ms or 0)) / 1000.0
    if job.done.wait(timeout=timeout_seconds):
        return _status_copy(job.status)
    return {
        **_status_copy(job.status),
        "wait_timed_out": True,
        "wait_timeout_ms": int(timeout_ms or 0),
    }


def refresh_resume_vector_status(
    *,
    session_id: str,
    resume_source_id: str | None,
    parsed: dict[str, Any] | None = None,
    embedding_override: dict[str, Any] | None = None,
    current_status: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a finished status if available; otherwise keep/start pending work."""

    if isinstance(current_status, dict) and current_status.get("status") in {
        "ready",
        "failed",
        "skipped",
    }:
        return _status_copy(current_status)
    return wait_for_resume_vector_status(
        session_id=session_id,
        resume_source_id=resume_source_id,
        parsed=parsed,
        embedding_override=embedding_override,
        timeout_ms=0,
    )


def _ensure_job(
    *,
    session_id: str,
    resume_source_id: str | None,
    parsed: dict[str, Any] | None,
    embedding_override: dict[str, Any] | None,
) -> _ResumeVectorJob | None:
    sid = str(session_id or "").strip()
    source_id = str(resume_source_id or "").strip()
    if not sid or not source_id:
        return None
    key = (sid, source_id)
    with _LOCK:
        existing = _JOBS.get(key)
        if existing is not None:
            return existing
        job = _ResumeVectorJob(key=key, status=_pending_status(sid, source_id))
        _JOBS[key] = job
    try:
        job.future = _EXECUTOR.submit(
            _run_resume_vector_job,
            job,
            parsed if isinstance(parsed, dict) else None,
            dict(embedding_override) if isinstance(embedding_override, dict) else None,
        )
    except Exception as exc:  # pragma: no cover - executor outage
        safe_error = _safe_error(exc, embedding_override)
        log.warning("resume vector job failed to start: session=%s error=%s", sid, safe_error)
        _set_status(
            job,
            {
                **_pending_status(sid, source_id),
                "status": "failed",
                "error": safe_error,
            },
        )
    return job


def _run_resume_vector_job(
    job: _ResumeVectorJob,
    parsed: dict[str, Any] | None,
    embedding_override: dict[str, Any] | None,
) -> None:
    session_id, source_id = job.key
    try:
        artifact = consume_resume_parse_artifact(source_id)
        if artifact is None:
            _set_status(
                job,
                {
                    **_pending_status(session_id, source_id),
                    "status": "skipped",
                    "skipped_reason": "parse_artifact_missing_or_expired",
                },
            )
            return
        revision_id = secrets.token_urlsafe(18)
        parsed_payload = parsed if parsed else artifact.parsed
        source_cache_key = None
        try:
            model_version = current_embedding_model_version(embedding_override)
            source_cache_key = resume_anchor_cache_key(
                redacted_text=artifact.redacted_text,
                parsed=parsed_payload,
                embedding_model_version=model_version,
            )
            cached_status = try_bind_cached_resume_anchors(
                session_id=session_id,
                resume_revision_id=revision_id,
                source_artifact_id=artifact.artifact_id,
                cache_key=source_cache_key,
                embedding_model_version=model_version,
            )
            if cached_status is not None:
                cached_status.setdefault("resume_source_id", artifact.artifact_id)
                cached_status.setdefault("resume_revision_id", revision_id)
                _set_status(job, cached_status)
                return
        except Exception as exc:
            log.warning(
                "resume anchor cache lookup failed: session=%s source=%s error=%s",
                session_id,
                source_id,
                _safe_error(exc, embedding_override),
            )
        status = vectorize_resume(
            session_id=session_id,
            resume_revision_id=revision_id,
            source_artifact_id=artifact.artifact_id,
            raw_text=artifact.redacted_text,
            parsed=parsed_payload,
            embedding_override=embedding_override,
            source_cache_key=source_cache_key,
        )
        status.setdefault("resume_source_id", artifact.artifact_id)
        status.setdefault("resume_revision_id", revision_id)
        status.setdefault("cache_hit", False)
        _set_status(job, status)
    except Exception as exc:  # pragma: no cover - vectorize_resume normally degrades
        safe_error = _safe_error(exc, embedding_override)
        log.warning(
            "resume vector job failed: session=%s source=%s error=%s",
            session_id,
            source_id,
            safe_error,
        )
        _set_status(
            job,
            {
                **_pending_status(session_id, source_id),
                "status": "failed",
                "error": safe_error,
            },
        )


def _set_status(job: _ResumeVectorJob, status: dict[str, Any]) -> None:
    with _LOCK:
        job.status = _status_copy(status)
        job.done.set()


def _pending_status(session_id: str, resume_source_id: str) -> dict[str, Any]:
    return {
        "status": "pending_background",
        "source_type": "resume",
        "resume_source_id": resume_source_id,
        "resume_revision_id": None,
        "skipped_reason": None,
        "error": None,
        "started_at": datetime.now(UTC).isoformat(),
    }


def _skipped_no_source(resume_source_id: str | None) -> dict[str, Any]:
    return {
        "status": "skipped",
        "source_type": "resume",
        "resume_source_id": resume_source_id,
        "resume_revision_id": None,
        "skipped_reason": "no_parse_artifact",
    }


def _safe_error(
    exc: Exception,
    embedding_override: dict[str, Any] | None,
) -> str:
    try:
        from app.engine.agents.llm_client import redact_llm_secrets

        secret_config = (
            {"embedding_override": embedding_override}
            if isinstance(embedding_override, dict)
            else None
        )
        return redact_llm_secrets(str(exc), secret_config)
    except Exception:
        return str(exc)


def _status_copy(status: dict[str, Any]) -> dict[str, Any]:
    return dict(status or {})


def _reset_resume_vector_jobs_for_tests() -> None:
    with _LOCK:
        _JOBS.clear()
