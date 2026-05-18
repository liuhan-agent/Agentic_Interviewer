"""Persistence helpers for setup-time resume parse artifacts."""
from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, update
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.core.settings import get_settings
from app.data.clean import redact_pii
from app.models.base import get_session as get_db_session
from app.models.resume_parse_artifact import ResumeParseArtifact

log = get_logger(__name__)


@dataclass(frozen=True)
class ResumeParseArtifactPayload:
    artifact_id: str
    redacted_text: str
    parsed: dict[str, Any]
    filename: str | None
    text_sha256: str
    created_at: datetime
    expires_at: datetime
    consumed_at: datetime | None


def create_resume_parse_artifact(
    *,
    text: str,
    parsed: dict[str, Any],
    filename: str | None,
    db_session: Session | None = None,
) -> ResumeParseArtifactPayload | None:
    """Redact, persist, and return a fresh artifact row."""

    try:
        return _with_session(
            db_session,
            lambda session: _create_resume_parse_artifact(
                text=text,
                parsed=parsed,
                filename=filename,
                db_session=session,
            ),
        )
    except Exception as e:  # pragma: no cover - persistence outage fallback
        log.warning("create_resume_parse_artifact failed: %s", e)
        return None


def read_resume_parse_artifact(
    artifact_id: str,
    *,
    db_session: Session | None = None,
) -> ResumeParseArtifactPayload | None:
    """Read without consuming; returns ``None`` when unusable."""

    try:
        return _with_session(
            db_session,
            lambda session: _read_resume_parse_artifact(
                artifact_id,
                db_session=session,
            ),
        )
    except Exception as e:  # pragma: no cover - persistence outage fallback
        log.warning("read_resume_parse_artifact failed: %s", e)
        return None


def consume_resume_parse_artifact(
    artifact_id: str,
    *,
    db_session: Session | None = None,
) -> ResumeParseArtifactPayload | None:
    """Atomically consume an artifact once and return its payload."""

    try:
        return _with_session(
            db_session,
            lambda session: _consume_resume_parse_artifact(
                artifact_id,
                db_session=session,
            ),
        )
    except Exception as e:  # pragma: no cover - persistence outage fallback
        log.warning("consume_resume_parse_artifact failed: %s", e)
        return None


def cleanup_expired_resume_parse_artifacts(
    *,
    db_session: Session | None = None,
) -> int:
    """Delete expired artifact rows and return the number deleted."""

    try:
        result = _with_session(
            db_session,
            lambda session: session.execute(
                delete(ResumeParseArtifact).where(
                    ResumeParseArtifact.expires_at < _now()
                )
            ).rowcount,
        )
        return int(result or 0)
    except Exception as e:  # pragma: no cover - cleanup should fail soft
        log.warning("cleanup_expired_resume_parse_artifacts failed: %s", e)
        return 0


def _create_resume_parse_artifact(
    *,
    text: str,
    parsed: dict[str, Any],
    filename: str | None,
    db_session: Session,
) -> ResumeParseArtifactPayload:
    now = _now()
    redacted = redact_pii(text or "").cleaned
    row = ResumeParseArtifact(
        artifact_id=secrets.token_urlsafe(24),
        redacted_text=redacted,
        parsed=dict(parsed or {}),
        filename=filename,
        text_sha256=hashlib.sha256(redacted.encode("utf-8")).hexdigest(),
        created_at=now,
        expires_at=now
        + timedelta(
            seconds=max(
                60,
                int(get_settings().resume_rag_parse_artifact_ttl_seconds or 3600),
            )
        ),
        consumed_at=None,
    )
    db_session.add(row)
    db_session.flush()
    return _payload_from_row(row)


def _read_resume_parse_artifact(
    artifact_id: str,
    *,
    db_session: Session,
) -> ResumeParseArtifactPayload | None:
    if not artifact_id:
        return None
    row = db_session.get(ResumeParseArtifact, artifact_id)
    if (
        row is None
        or row.consumed_at is not None
        or _ensure_aware(row.expires_at) <= _now()
    ):
        return None
    return _payload_from_row(row)


def _consume_resume_parse_artifact(
    artifact_id: str,
    *,
    db_session: Session,
) -> ResumeParseArtifactPayload | None:
    if not artifact_id:
        return None
    now = _now()
    stmt = (
        update(ResumeParseArtifact)
        .where(
            ResumeParseArtifact.artifact_id == artifact_id,
            ResumeParseArtifact.consumed_at.is_(None),
            ResumeParseArtifact.expires_at > now,
        )
        .values(consumed_at=now)
        .returning(ResumeParseArtifact)
    )
    row = db_session.execute(stmt).scalar_one_or_none()
    if row is None:
        return None
    db_session.flush()
    return _payload_from_row(row)


def _payload_from_row(row: ResumeParseArtifact) -> ResumeParseArtifactPayload:
    return ResumeParseArtifactPayload(
        artifact_id=row.artifact_id,
        redacted_text=row.redacted_text or "",
        parsed=dict(row.parsed or {}),
        filename=row.filename,
        text_sha256=row.text_sha256 or "",
        created_at=row.created_at,
        expires_at=row.expires_at,
        consumed_at=row.consumed_at,
    )


def _with_session(
    db_session: Session | None,
    fn,
):
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
