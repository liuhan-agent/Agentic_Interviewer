"""Retention helpers for session-scoped anchor rows."""
from __future__ import annotations

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.base import get_session as get_db_session
from app.models.session_anchor import SessionAnchorChunk

log = get_logger(__name__)


def cleanup_completed_session_anchors(
    session_id: str,
    *,
    db_session: Session | None = None,
) -> int:
    """Delete session-scoped anchor rows after a completed interview.

    This intentionally leaves the global resume anchor cache untouched; explicit
    subject deletion owns cache purging.
    """

    sid = str(session_id or "").strip()
    if not sid:
        return 0
    try:
        return int(
            _with_session(
                db_session,
                lambda session: session.execute(
                    delete(SessionAnchorChunk).where(
                        SessionAnchorChunk.session_id == sid
                    )
                ).rowcount,
            )
            or 0
        )
    except Exception as exc:
        log.warning("completed session anchor cleanup failed for %s: %s", sid, exc)
        return 0


def _with_session(db_session: Session | None, fn):
    if db_session is not None:
        return fn(db_session)
    with get_db_session() as session:
        return fn(session)
