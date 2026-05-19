from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.base import get_session as get_db_session
from app.models.session_anchor import SessionAnchorChunk
from app.services.resume_parse_artifacts import cleanup_expired_resume_parse_artifacts


def run_cleanup(
    *,
    db_session: Session | None = None,
    now: datetime | None = None,
    batch_size: int = 1000,
) -> dict[str, Any]:
    """Delete expired session anchor chunks and resume parse artifacts."""
    current = now or datetime.now(UTC)
    limit = max(1, int(batch_size or 1000))

    def _run(session: Session) -> dict[str, Any]:
        chunk_deleted = _delete_expired_chunks(
            session,
            now=current,
            batch_size=limit,
        )
        artifact_deleted = cleanup_expired_resume_parse_artifacts(
            db_session=session,
        )
        return {
            "session_anchor_chunks_deleted": chunk_deleted,
            "resume_parse_artifacts_deleted": artifact_deleted,
            "total_deleted": chunk_deleted + artifact_deleted,
            "batch_size": limit,
        }

    if db_session is not None:
        return _run(db_session)
    with get_db_session() as session:
        return _run(session)


def _delete_expired_chunks(
    session: Session,
    *,
    now: datetime,
    batch_size: int,
) -> int:
    total = 0
    while True:
        ids = list(
            session.scalars(
                select(SessionAnchorChunk.id)
                .where(SessionAnchorChunk.expires_at < now)
                .limit(batch_size)
            ).all()
        )
        if not ids:
            break
        total += int(
            session.execute(
                delete(SessionAnchorChunk).where(SessionAnchorChunk.id.in_(ids))
            ).rowcount
            or 0
        )
        session.flush()
        if len(ids) < batch_size:
            break
    return total


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Clean expired session anchor RAG chunks and parse artifacts.",
    )
    parser.add_argument("--batch-size", type=int, default=1000)
    args = parser.parse_args()
    try:
        report = run_cleanup(batch_size=args.batch_size)
    except Exception as exc:
        print(
            json.dumps(
                {"ok": False, "error": str(exc)},
                ensure_ascii=False,
                indent=2,
            ),
            file=sys.stderr,
        )
        return 1
    print(json.dumps({"ok": True, **report}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
