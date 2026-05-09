"""Periodic privacy cleanup via APScheduler.

Deletes expired interview sessions, generation traces, and outcome
records according to the retention windows configured in Settings.
The scheduler is opt-in (``enable_privacy_cleanup=True``) so CI and
local dev never accidentally purge test data.
"""
from __future__ import annotations

from apscheduler.schedulers.background import BackgroundScheduler

from app.core.logging import get_logger

log = get_logger(__name__)


def _run_cleanup() -> None:
    from app.services.privacy_cleanup import cleanup_expired_data

    try:
        result = cleanup_expired_data(dry_run=False)
        total = (
            result["sessions_deleted"]
            + result["traces_deleted"]
            + result["outcomes_deleted"]
        )
        if total > 0:
            log.info(
                "privacy cleanup: sessions=%d traces=%d outcomes=%d",
                result["sessions_deleted"],
                result["traces_deleted"],
                result["outcomes_deleted"],
            )
    except Exception:
        log.exception("privacy cleanup tick failed")


def start_privacy_cleanup_scheduler(
    interval_hours: int = 24,
) -> BackgroundScheduler:
    """Kick off a background scheduler for privacy cleanup."""
    scheduler = BackgroundScheduler(daemon=True)
    scheduler.add_job(
        _run_cleanup,
        "interval",
        hours=max(1, interval_hours),
        id="privacy_cleanup",
        replace_existing=True,
    )
    scheduler.start()
    log.info(
        "privacy cleanup scheduler started (every %d hour(s))",
        interval_hours,
    )
    return scheduler
