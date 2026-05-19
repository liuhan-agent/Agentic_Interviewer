from __future__ import annotations

import concurrent.futures
import secrets
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Literal

from app.core.logging import get_logger
from app.core.settings import get_settings
from app.services.interview_setup import resume_parse_payload
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

log = get_logger(__name__)

ResumeParseJobStatus = Literal["running", "completed", "failed", "expired"]


@dataclass
class ResumeParseJob:
    job_id: str
    filename: str | None
    status: ResumeParseJobStatus
    expires_at: datetime
    result: dict[str, Any] | None = None
    error: str | None = None


class ResumeParseJobManager:
    def __init__(self) -> None:
        self._jobs: dict[str, ResumeParseJob] = {}
        self._lock = threading.Lock()
        self._executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=4,
            thread_name_prefix="resume-parse-job",
        )

    def create(
        self,
        *,
        filename: str | None,
        content_type: str | None,
        raw: bytes,
        llm_override: dict[str, Any] | None,
        extract_text_fn: Callable[..., str] = extract_text_with_timeout,
        parse_resume_fn: Callable[..., Any] = parse_resume,
        cache_key_fn: Callable[..., str] = resume_parse_cache_key,
        get_cache_fn: Callable[[], Any] = get_resume_parse_cache,
        should_cache_fn: Callable[[dict[str, Any]], bool] = should_cache_resume_parse,
        timeout_seconds: float = EXTRACT_TEXT_TIMEOUT_SECONDS,
        llm_timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        self._prune_expired()
        text = extract_text_fn(
            filename=filename,
            content_type=content_type,
            data=raw,
            timeout_seconds=timeout_seconds,
        )
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
                return self._store_completed_job(
                    filename=filename,
                    result=payload,
                )

        settings = get_settings()
        job_id = secrets.token_urlsafe(24)
        expires_at = datetime.now(timezone.utc) + timedelta(
            seconds=max(60, int(settings.resume_parse_job_ttl_seconds))
        )
        job = ResumeParseJob(
            job_id=job_id,
            filename=filename,
            status="running",
            expires_at=expires_at,
        )
        with self._lock:
            self._jobs[job_id] = job
        timeout = (
            settings.resume_parse_job_llm_timeout_seconds
            if llm_timeout_seconds is None
            else llm_timeout_seconds
        )
        self._executor.submit(
            self._run_job,
            job_id,
            text,
            filename,
            llm_override,
            parse_resume_fn,
            cache_key,
            cache,
            should_cache_fn,
            float(timeout),
        )
        return self.snapshot(job_id)

    def get(self, job_id: str) -> dict[str, Any]:
        return self.snapshot(job_id)

    def reset_for_tests(self) -> None:
        with self._lock:
            self._jobs.clear()

    def snapshot(self, job_id: str) -> dict[str, Any]:
        self._prune_expired()
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return self._expired_snapshot(job_id)
            return self._job_snapshot(job)

    def _run_job(
        self,
        job_id: str,
        text: str,
        filename: str | None,
        llm_override: dict[str, Any] | None,
        parse_resume_fn: Callable[..., Any],
        cache_key: str,
        cache: Any,
        should_cache_fn: Callable[[dict[str, Any]], bool],
        llm_timeout_seconds: float,
    ) -> None:
        try:
            context = temporary_llm_override(llm_override)
            with context:
                parsed = parse_resume_fn(
                    text,
                    force_llm=bool(llm_override),
                    filename=filename,
                    llm_timeout_seconds=llm_timeout_seconds,
                )
            payload = resume_parse_payload(parsed, text)
            if cache is not None and should_cache_fn(payload):
                cache.set(cache_key, payload)
            with self._lock:
                job = self._jobs.get(job_id)
                if job is not None:
                    job.status = "completed"
                    job.result = payload
                    job.error = None
        except Exception as e:
            log.warning("resume_parse_job_failed: job_id=%s error=%s", job_id, e)
            with self._lock:
                job = self._jobs.get(job_id)
                if job is not None:
                    job.status = "failed"
                    job.error = str(e) or e.__class__.__name__

    def _prune_expired(self) -> None:
        now = datetime.now(timezone.utc)
        with self._lock:
            expired = [
                job_id
                for job_id, job in self._jobs.items()
                if job.expires_at <= now
            ]
            for job_id in expired:
                self._jobs.pop(job_id, None)

    @staticmethod
    def _job_snapshot(job: ResumeParseJob) -> dict[str, Any]:
        out: dict[str, Any] = {
            "job_id": job.job_id,
            "status": job.status,
            "filename": job.filename,
            "expires_at": job.expires_at.isoformat(),
        }
        if job.result is not None:
            out["result"] = job.result
        if job.error:
            out["error"] = job.error
        return out

    def _store_completed_job(
        self,
        *,
        filename: str | None,
        result: dict[str, Any],
    ) -> dict[str, Any]:
        job_id = secrets.token_urlsafe(24)
        expires_at = datetime.now(timezone.utc) + timedelta(
            seconds=max(60, int(get_settings().resume_parse_job_ttl_seconds))
        )
        job = ResumeParseJob(
            job_id=job_id,
            filename=filename,
            status="completed",
            expires_at=expires_at,
            result=result,
        )
        with self._lock:
            self._jobs[job_id] = job
        return self._job_snapshot(job)

    @staticmethod
    def _expired_snapshot(job_id: str) -> dict[str, Any]:
        return {
            "job_id": job_id,
            "status": "expired",
            "filename": None,
            "expires_at": datetime.now(timezone.utc).isoformat(),
            "error": "resume parse job is missing or expired",
        }


_manager = ResumeParseJobManager()


def create_resume_parse_job(**kwargs: Any) -> dict[str, Any]:
    return _manager.create(**kwargs)


def get_resume_parse_job(job_id: str) -> dict[str, Any]:
    return _manager.get(job_id)


def reset_resume_parse_jobs_for_tests() -> None:
    _manager.reset_for_tests()
