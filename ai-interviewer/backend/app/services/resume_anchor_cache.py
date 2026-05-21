"""Global resume anchor vector cache with session copy-on-bind."""
from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.core.settings import get_settings
from app.data.clean import redact_pii
from app.models.base import get_session as get_db_session
from app.models.resume_anchor_cache import ResumeAnchorCacheChunk
from app.models.session_anchor import SessionAnchorChunk

log = get_logger(__name__)

RESUME_ANCHOR_CHUNKER_VERSION = "resume_chunker_dual_track_2026_05_21_v1"
_PARSED_CACHE_FIELDS = (
    "candidate_profile",
    "summary",
    "skills",
    "highlights",
    "projects",
    "focus_areas",
    "concerns",
)


def resume_anchor_cache_key(
    *,
    redacted_text: str,
    parsed: dict[str, Any] | None,
    embedding_model_version: str,
) -> str:
    """Return a stable content/version key for reusable resume anchors."""

    safe_text = redact_pii(str(redacted_text or "")).cleaned
    material = {
        "redacted_text_sha256": _sha256(safe_text),
        "parsed_sha256": _sha256(_canonical_json(_chunk_affecting_parsed(parsed))),
        "chunker_version": RESUME_ANCHOR_CHUNKER_VERSION,
        "embedding_model_version": str(embedding_model_version or ""),
    }
    return _sha256(_canonical_json(material))


def try_bind_cached_resume_anchors(
    *,
    session_id: str,
    resume_revision_id: str,
    source_artifact_id: str | None,
    cache_key: str,
    embedding_model_version: str,
    db_session: Session | None = None,
) -> dict[str, Any] | None:
    """Copy fresh cached resume chunks into the current session."""

    try:
        return _with_session(
            db_session,
            lambda session: _try_bind_cached_resume_anchors(
                session=session,
                session_id=session_id,
                resume_revision_id=resume_revision_id,
                source_artifact_id=source_artifact_id,
                cache_key=cache_key,
                embedding_model_version=embedding_model_version,
            ),
        )
    except Exception as exc:
        log.warning("resume anchor cache bind failed: %s", exc)
        return None


def store_resume_anchor_cache_chunks(
    *,
    cache_key: str,
    embedding_model_version: str,
    session_id: str,
    resume_revision_id: str,
    db_session: Session | None = None,
) -> int:
    """Persist cache rows from already-written session resume chunks."""

    try:
        return int(
            _with_session(
                db_session,
                lambda session: _store_resume_anchor_cache_chunks(
                    session=session,
                    cache_key=cache_key,
                    embedding_model_version=embedding_model_version,
                    session_id=session_id,
                    resume_revision_id=resume_revision_id,
                ),
            )
            or 0
        )
    except Exception as exc:
        log.warning("resume anchor cache store failed: %s", exc)
        return 0


def purge_resume_anchor_cache_keys(
    cache_keys: list[str] | set[str] | tuple[str, ...],
    *,
    db_session: Session | None = None,
) -> int:
    """Delete all global cache rows for the given cache keys."""

    keys = sorted({str(key).strip() for key in cache_keys if str(key).strip()})
    if not keys:
        return 0
    try:
        return int(
            _with_session(
                db_session,
                lambda session: session.execute(
                    delete(ResumeAnchorCacheChunk).where(
                        ResumeAnchorCacheChunk.cache_key.in_(keys)
                    )
                ).rowcount,
            )
            or 0
        )
    except Exception as exc:
        log.warning("resume anchor cache purge failed: %s", exc)
        return 0


def cleanup_expired_resume_anchor_cache_chunks(
    *,
    db_session: Session | None = None,
    now: datetime | None = None,
    batch_size: int = 1000,
) -> int:
    """Delete expired global resume anchor cache rows."""

    current = _ensure_aware(now or _now())
    limit = max(1, int(batch_size or 1000))
    try:
        return int(
            _with_session(
                db_session,
                lambda session: _cleanup_expired_resume_anchor_cache_chunks(
                    session=session,
                    now=current,
                    batch_size=limit,
                ),
            )
            or 0
        )
    except Exception as exc:
        log.warning("resume anchor cache cleanup failed: %s", exc)
        return 0


def _try_bind_cached_resume_anchors(
    *,
    session: Session,
    session_id: str,
    resume_revision_id: str,
    source_artifact_id: str | None,
    cache_key: str,
    embedding_model_version: str,
) -> dict[str, Any] | None:
    now = _now()
    rows = list(
        session.scalars(
            select(ResumeAnchorCacheChunk)
            .where(ResumeAnchorCacheChunk.cache_key == cache_key)
            .where(ResumeAnchorCacheChunk.embedding_model_version == embedding_model_version)
            .where(ResumeAnchorCacheChunk.expires_at > now)
            .order_by(ResumeAnchorCacheChunk.chunk_index)
        ).all()
    )
    if not rows:
        return None
    expires_at = _session_expires_at(now)
    with session.begin_nested():
        for row in rows:
            row.last_used_at = now
            row.hit_count = int(row.hit_count or 0) + 1
            session.add(
                SessionAnchorChunk(
                    session_id=session_id,
                    source_type="resume",
                    source_revision_id=resume_revision_id,
                    source_artifact_id=source_artifact_id,
                    source_cache_key=cache_key,
                    source_turn_id=None,
                    chunk_index=row.chunk_index,
                    tier=row.tier,
                    section_name=row.section_name,
                    heading=row.heading,
                    project_name=row.project_name,
                    text=row.text,
                    tech_keywords=list(row.tech_keywords or []),
                    dimensions_hint=list(row.dimensions_hint or []),
                    chunker_mode=row.chunker_mode,
                    embedding_model_version=row.embedding_model_version,
                    embedding=_as_list(row.embedding),
                    expires_at=expires_at,
                )
            )
        session.flush()
    return {
        "status": "ready",
        "source_type": "resume",
        "resume_revision_id": resume_revision_id,
        "source_artifact_id": source_artifact_id,
        "resume_source_id": source_artifact_id,
        "source_cache_key": cache_key,
        "embedding_model_version": embedding_model_version,
        "mode": str(rows[0].chunker_mode or ""),
        "chunk_count": len(rows),
        "skipped_reason": None,
        "error": None,
        "cache_hit": True,
        "expires_at": expires_at.isoformat(),
    }


def _store_resume_anchor_cache_chunks(
    *,
    session: Session,
    cache_key: str,
    embedding_model_version: str,
    session_id: str,
    resume_revision_id: str,
) -> int:
    rows = list(
        session.scalars(
            select(SessionAnchorChunk)
            .where(SessionAnchorChunk.session_id == session_id)
            .where(SessionAnchorChunk.source_type == "resume")
            .where(SessionAnchorChunk.source_revision_id == resume_revision_id)
            .where(SessionAnchorChunk.embedding_model_version == embedding_model_version)
            .order_by(SessionAnchorChunk.chunk_index)
        ).all()
    )
    if not rows:
        return 0
    expires_at = _cache_expires_at()
    with session.begin_nested():
        session.execute(
            delete(ResumeAnchorCacheChunk)
            .where(ResumeAnchorCacheChunk.cache_key == cache_key)
            .where(
                ResumeAnchorCacheChunk.embedding_model_version
                == embedding_model_version
            )
        )
        for row in rows:
            session.add(
                ResumeAnchorCacheChunk(
                    cache_key=cache_key,
                    embedding_model_version=embedding_model_version,
                    chunk_index=row.chunk_index,
                    tier=row.tier,
                    section_name=row.section_name,
                    heading=row.heading,
                    project_name=row.project_name,
                    text=row.text,
                    tech_keywords=list(row.tech_keywords or []),
                    dimensions_hint=list(row.dimensions_hint or []),
                    chunker_mode=row.chunker_mode,
                    embedding=_as_list(row.embedding),
                    expires_at=expires_at,
                    last_used_at=None,
                    hit_count=0,
                )
            )
        session.flush()
    return len(rows)


def _cleanup_expired_resume_anchor_cache_chunks(
    *,
    session: Session,
    now: datetime,
    batch_size: int,
) -> int:
    total = 0
    while True:
        ids = list(
            session.scalars(
                select(ResumeAnchorCacheChunk.id)
                .where(ResumeAnchorCacheChunk.expires_at < now)
                .limit(batch_size)
            ).all()
        )
        if not ids:
            break
        total += int(
            session.execute(
                delete(ResumeAnchorCacheChunk).where(
                    ResumeAnchorCacheChunk.id.in_(ids)
                )
            ).rowcount
            or 0
        )
        session.flush()
        if len(ids) < batch_size:
            break
    return total


def _chunk_affecting_parsed(parsed: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(parsed, dict):
        return {}
    return {
        key: _canonical_value(parsed.get(key))
        for key in _PARSED_CACHE_FIELDS
        if parsed.get(key) not in (None, "", [], {})
    }


def _canonical_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _canonical_value(value[key])
            for key in sorted(value)
            if value[key] not in (None, "", [], {})
        }
    if isinstance(value, (list, tuple, set)):
        return [_canonical_value(item) for item in value if item not in (None, "", [], {})]
    if isinstance(value, str):
        return " ".join(value.split())
    return value


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    return list(value)


def _sha256(value: str) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()


def _cache_expires_at() -> datetime:
    return _now() + timedelta(
        hours=max(1, int(get_settings().resume_anchor_cache_ttl_hours or 168))
    )


def _session_expires_at(now: datetime) -> datetime:
    return now + timedelta(
        hours=max(1, int(get_settings().resume_rag_session_ttl_hours or 24)) + 24
    )


def _with_session(db_session: Session | None, fn):
    if db_session is not None:
        return fn(db_session)
    with get_db_session() as session:
        return fn(session)


def _now() -> datetime:
    return datetime.now(UTC)


def _ensure_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
