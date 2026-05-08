"""Periodic privacy retention cleanup scheduling."""
from __future__ import annotations

from typing import Any

from apscheduler.schedulers.background import BackgroundScheduler

from app.core.logging import get_logger
from app.services.privacy_cleanup import cleanup_expired_data

log = get_logger(__name__)


def run_privacy_cleanup_now(*, batch_size: int | None = None) -> dict[str, Any]:
    """One-shot privacy cleanup entrypoint for schedulers and tests."""
    return cleanup_expired_data(dry_run=False, batch_size=batch_size)


def start_privacy_cleanup_scheduler(
    *,
    interval_minutes: int,
    batch_size: int | None = None,
) -> BackgroundScheduler:
    """Start periodic hard-delete cleanup for expired persisted interview data."""

    def _tick() -> None:
        try:
            report = run_privacy_cleanup_now(batch_size=batch_size)
            log.info("privacy cleanup completed: %s", report)
        except Exception as e:  # pragma: no cover
            log.warning("privacy cleanup failed: %s", e)

    scheduler = BackgroundScheduler(daemon=True)
    scheduler.add_job(
        _tick,
        "interval",
        minutes=interval_minutes,
        id="privacy_cleanup",
        replace_existing=True,
    )
    scheduler.start()
    log.info("privacy cleanup scheduler started (every %d min)", interval_minutes)
    return scheduler
