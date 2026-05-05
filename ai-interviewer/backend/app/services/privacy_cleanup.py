"""Privacy deletion and retention cleanup services."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, select

from app.core.metrics import record_session_privacy_delete
from app.core.settings import get_settings
from app.models.base import get_session as get_db_session
from app.models.generation_trace import GenerationTrace
from app.models.interview_session import InterviewSession
from app.models.outcome_record import OutcomeRecord


def delete_session_data(session_id: str) -> dict[str, Any]:
    """Hard-delete persisted rows for a single interview session."""
    with get_db_session() as db:
        session_row = db.get(InterviewSession, session_id)
        outcome_row = db.get(OutcomeRecord, session_id)

        traces_deleted = db.execute(
            delete(GenerationTrace).where(GenerationTrace.session_id == session_id)
        ).rowcount

        outcome_deleted = outcome_row is not None
        if outcome_row is not None:
            db.delete(outcome_row)

        deleted = (
            session_row is not None
            or outcome_row is not None
            or int(traces_deleted or 0) > 0
        )
        if session_row is not None:
            db.delete(session_row)

    record_session_privacy_delete("trace", int(traces_deleted or 0))
    record_session_privacy_delete("outcome", 1 if outcome_deleted else 0)
    record_session_privacy_delete("session", 1 if session_row is not None else 0)
    return {
        "session_id": session_id,
        "deleted": deleted,
        "traces_deleted": int(traces_deleted or 0),
        "outcome_deleted": outcome_deleted,
    }


def _expired_ids(db, model, column, cutoff: datetime, batch_size: int) -> list[str]:
    id_column = model.session_id
    return list(
        db.scalars(
            select(id_column).where(column < cutoff).limit(batch_size)
        ).all()
    )


def _delete_by_session_ids(db, model, ids: list[str]) -> int:
    if not ids:
        return 0
    return int(
        db.execute(delete(model).where(model.session_id.in_(ids))).rowcount or 0
    )


def cleanup_expired_data(
    *,
    now: datetime | None = None,
    dry_run: bool = True,
    batch_size: int | None = None,
) -> dict[str, Any]:
    """Delete or count expired session, trace and outcome rows."""
    settings = get_settings()
    current = now or datetime.now(UTC)
    limit = batch_size or settings.privacy_cleanup_batch_size
    session_cutoff = current - timedelta(days=settings.session_retention_days)
    trace_cutoff = current - timedelta(days=settings.trace_retention_days)
    outcome_cutoff = current - timedelta(days=settings.outcome_retention_days)

    with get_db_session() as db:
        session_ids = _expired_ids(
            db, InterviewSession, InterviewSession.updated_at, session_cutoff, limit
        )
        trace_ids = _expired_ids(
            db, GenerationTrace, GenerationTrace.created_at, trace_cutoff, limit
        )
        outcome_ids = _expired_ids(
            db, OutcomeRecord, OutcomeRecord.collected_at, outcome_cutoff, limit
        )

        if dry_run:
            sessions_deleted = len(session_ids)
            traces_deleted = len(trace_ids)
            outcomes_deleted = len(outcome_ids)
        else:
            sessions_deleted = _delete_by_session_ids(db, InterviewSession, session_ids)
            traces_deleted = _delete_by_session_ids(db, GenerationTrace, trace_ids)
            outcomes_deleted = _delete_by_session_ids(db, OutcomeRecord, outcome_ids)

    if not dry_run:
        record_session_privacy_delete("session", sessions_deleted)
        record_session_privacy_delete("trace", traces_deleted)
        record_session_privacy_delete("outcome", outcomes_deleted)

    return {
        "dry_run": dry_run,
        "sessions_deleted": sessions_deleted,
        "traces_deleted": traces_deleted,
        "outcomes_deleted": outcomes_deleted,
        "batch_size": limit,
        "session_retention_days": settings.session_retention_days,
        "trace_retention_days": settings.trace_retention_days,
        "outcome_retention_days": settings.outcome_retention_days,
        "resume_cache_cleanup": "redis_ttl_only",
    }
