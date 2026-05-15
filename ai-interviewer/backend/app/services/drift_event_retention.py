"""Garbage-collect old ``verifier_drift_events`` rows.

The drift event log is append-only and the aggregation read model
(:mod:`app.services.drift_pattern_aggregation`) only ever looks at a
sliding window — anything older than ``retention_days`` is dead weight.
This sweep simply DELETEs the expired rows and returns the count so the
admin endpoint and any future scheduler can report the cleanup volume.

Safety
------
* ``retention_days`` is clamped to ``>= 1`` so a misconfigured value
  cannot truncate the entire table by accident.
* No cascade is needed — the patterns table is a materialised view; PR3
  will repopulate it from whatever events remain on the next refresh.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.models.verifier_drift import VerifierDriftEvent


@dataclass(frozen=True)
class DriftEventRetentionResult:
    deleted: int = 0


def cleanup_expired_verifier_drift_events(
    *,
    session: Session,
    retention_days: int = 90,
) -> DriftEventRetentionResult:
    """Delete drift events older than ``retention_days``."""
    days = max(int(retention_days or 0), 1)
    cutoff = datetime.now(UTC) - timedelta(days=days)

    result = session.execute(
        delete(VerifierDriftEvent).where(
            VerifierDriftEvent.created_at < cutoff
        )
    )
    deleted = int(result.rowcount or 0)
    if deleted:
        session.flush()
    return DriftEventRetentionResult(deleted=deleted)
