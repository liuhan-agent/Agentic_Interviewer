"""Turn traces + outcomes into supervised or preference training files.

For MVP we emit a JSONL where each line represents one question-answer
turn, with the evaluator score as a reward label. Phase 4 can extend
this to a DPO-style preference dataset by pairing high-score and
low-score turns within the same session.
"""
from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path

from sqlalchemy import select

from app.core.logging import get_logger
from app.models import GenerationTrace, OutcomeRecord, TraceAnnotation, get_session

log = get_logger(__name__)


def _flagged_turns(sess: object) -> set[tuple[str, int]]:
    """Return (trace_id, turn_idx) pairs flagged by human reviewers."""
    try:
        flagged = sess.query(  # type: ignore[union-attr]
            TraceAnnotation.trace_id,
            TraceAnnotation.turn_idx,
        ).filter(TraceAnnotation.verdict == "flagged").all()
        return {(r.trace_id, r.turn_idx) for r in flagged}
    except Exception:
        return set()


def _rows(
    session_ids: Iterable[str] | None = None,
    *,
    since: datetime | None = None,
    exclude_flagged: bool = True,
) -> list[dict]:
    out: list[dict] = []
    with get_session() as sess:
        stmt = select(GenerationTrace)
        if session_ids is not None:
            stmt = stmt.where(GenerationTrace.session_id.in_(list(session_ids)))
        if since is not None:
            stmt = stmt.where(GenerationTrace.created_at >= since)
        traces = list(sess.scalars(stmt))
        outcomes = {
            o.session_id: o
            for o in sess.scalars(select(OutcomeRecord))
        }
        flagged = _flagged_turns(sess) if exclude_flagged else set()
        for t in traces:
            if exclude_flagged and (t.trace_id, t.turn_idx) in flagged:
                continue
            outcome = outcomes.get(t.session_id)
            out.append(
                {
                    "session_id": t.session_id,
                    "turn_idx": t.turn_idx,
                    "dimension": t.dimension,
                    "action_id": t.action_id,
                    "context_key": t.context_key,
                    "question": t.question,
                    "answer": t.answer,
                    "score": t.score,
                    "passed": t.passed,
                    "immediate_reward": t.immediate_reward,
                    "delayed_reward": t.delayed_reward,
                    "outcome": outcome.outcome if outcome else None,
                    "performance_score": outcome.performance_score if outcome else None,
                }
            )
    return out


def export_jsonl(
    path: Path,
    *,
    session_ids: Iterable[str] | None = None,
    since: datetime | None = None,
) -> int:
    """Write every trace row as one JSON line.

    The file layout is intentionally flat so downstream SFT/DPO
    scripts can pick fields without deserialising heavy nested
    structures.

    Parameters
    ----------
    path:
        Destination file. Parent directories are created if missing.
    session_ids:
        Optional allow-list; when provided only those sessions are
        exported. Usually used for debugging or targeted re-exports.
    since:
        Optional lower bound on ``GenerationTrace.created_at``. Set
        this to ``utcnow() - timedelta(days=1)`` from a daily cron to
        get a rolling incremental dump; ``None`` keeps the legacy
        "dump everything" behaviour for one-off audits.
    """
    rows = _rows(session_ids=session_ids, since=since)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    log.info(
        "wrote %d trace rows to %s (since=%s)",
        len(rows),
        path,
        since.isoformat() if since else "<all>",
    )
    return len(rows)
