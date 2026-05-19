"""Task entrypoint for verifier-drift event retention.

Wraps :func:`cleanup_expired_verifier_drift_events` so the admin route
and scheduler can call it without managing the DB session. Mirrors the
shape of ``drift_pattern_aggregation_tasks.run_drift_pattern_aggregation_now``.
"""
from __future__ import annotations

from dataclasses import asdict

from app.core.settings import get_settings
from app.models import get_session
from app.services.drift_event_retention import (
    cleanup_expired_verifier_drift_events,
)


def run_drift_event_retention_now() -> dict[str, int]:
    """Run one retention sweep and return counters.

    Reads ``verifier_drift_event_retention_days`` from settings so the
    admin trigger does not need to know the rollout default.
    """
    settings = get_settings()
    retention_days = int(
        getattr(settings, "verifier_drift_event_retention_days", 90) or 90
    )
    with get_session() as session:
        result = cleanup_expired_verifier_drift_events(
            session=session,
            retention_days=retention_days,
        )
    return asdict(result)
