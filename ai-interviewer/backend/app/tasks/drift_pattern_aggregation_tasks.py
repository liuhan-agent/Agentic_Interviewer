"""Task entrypoint for verifier-drift pattern aggregation.

Wraps :func:`refresh_verifier_drift_patterns` so the admin route and any
future scheduler can fire one aggregation pass with a one-line call,
without having to manage the DB session themselves. Mirrors the shape
of ``strategy_promotion_tasks.run_strategy_promotion_now``.
"""
from __future__ import annotations

from dataclasses import asdict

from app.core.settings import get_settings
from app.models import get_session
from app.services.drift_pattern_aggregation import refresh_verifier_drift_patterns


def run_drift_pattern_aggregation_now() -> dict[str, int]:
    """Run one drift-pattern aggregation pass and return counters.

    Reads ``drift_pattern_aggregation_window_days`` from settings so
    operators can re-tune the window without redeploying.
    """
    settings = get_settings()
    window_days = int(
        getattr(settings, "drift_pattern_aggregation_window_days", 30) or 30
    )
    with get_session() as session:
        result = refresh_verifier_drift_patterns(
            session=session,
            window_days=window_days,
        )
    return asdict(result)
