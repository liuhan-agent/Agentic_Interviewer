"""Periodic privacy cleanup via APScheduler.

Deletes expired interview sessions, generation traces, and outcome
records according to the retention windows configured in Settings.
The scheduler is opt-in (``enable_privacy_cleanup=True``) so CI and
local dev never accidentally purge test data.
"""
from __future__ import annotations

from typing import Any

from apscheduler.schedulers.background import BackgroundScheduler

from app.core.logging import get_logger

log = get_logger(__name__)


def run_privacy_cleanup_now(*, batch_size: int | None = None) -> dict[str, Any]:
    """One-shot privacy cleanup entrypoint for schedulers and tests."""
    from app.services.privacy_cleanup import cleanup_expired_data

    if batch_size is None:
        return cleanup_expired_data(dry_run=False)
    return cleanup_expired_data(dry_run=False, batch_size=batch_size)


def _run_cleanup(*, batch_size: int | None = None) -> None:
    from app.scripts.cleanup_session_anchor_chunks import run_cleanup as run_anchor_cleanup

    try:
        result = run_privacy_cleanup_now(batch_size=batch_size)
        anchor_result = run_anchor_cleanup()
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
        if anchor_result.get("total_deleted", 0) > 0:
            log.info(
                "session anchor cleanup: chunks=%d artifacts=%d resume_cache=%d",
                anchor_result.get("session_anchor_chunks_deleted", 0),
                anchor_result.get("resume_parse_artifacts_deleted", 0),
                anchor_result.get("resume_anchor_cache_chunks_deleted", 0),
            )
    except Exception:
        log.exception("privacy cleanup tick failed")


def start_privacy_cleanup_scheduler(
    interval_hours: int = 24,
    batch_size: int | None = None,
) -> BackgroundScheduler:
    """Kick off a background scheduler for privacy cleanup."""
    scheduler = BackgroundScheduler(daemon=True)
    scheduler.add_job(
        _run_cleanup,
        "interval",
        hours=max(1, interval_hours),
        kwargs={"batch_size": batch_size},
        id="privacy_cleanup",
        replace_existing=True,
    )
    scheduler.start()
    log.info(
        "privacy cleanup scheduler started (every %d hour(s))",
        interval_hours,
    )
    return scheduler
