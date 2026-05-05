"""Periodic tasks that pull outcomes in and back-fill rewards.

MVP implementation uses APScheduler (in-process). Production would
swap this for Celery/Temporal/etc. - the scheduling surface is
intentionally one-function-wide so callers only care about "run X
every N minutes".
"""
from __future__ import annotations

from apscheduler.schedulers.background import BackgroundScheduler

from app.core.logging import get_logger
from app.ml.rl.outcome_reward_bridge import backfill_once
from app.ml.rl.thompson import get_bandit

log = get_logger(__name__)


def start_background_scheduler(interval_minutes: int = 5) -> BackgroundScheduler:
    """Kick off a background scheduler. Idempotent per process."""
    scheduler = BackgroundScheduler(daemon=True)
    scheduler.add_job(
        backfill_once,
        "interval",
        minutes=interval_minutes,
        id="outcome_backfill",
        replace_existing=True,
    )
    scheduler.start()
    log.info("outcome backfill scheduler started (every %d min)", interval_minutes)
    return scheduler


def start_decay_scheduler(
    *,
    interval_days: int,
    factor: float,
    floor: float,
) -> BackgroundScheduler:
    """Kick off a scheduler that periodically decays bandit posteriors.

    Separate from the outcome backfill scheduler because the two
    cadences are very different (backfill: every few minutes; decay:
    once per day).  Using two schedulers keeps each knob independent
    so ``enable_outcome_sync`` and ``enable_bandit_decay`` don't have
    to be toggled together.
    """

    def _tick() -> None:
        get_bandit().decay(factor=factor, floor=floor)

    scheduler = BackgroundScheduler(daemon=True)
    scheduler.add_job(
        _tick,
        "interval",
        days=interval_days,
        id="bandit_decay",
        replace_existing=True,
    )
    scheduler.start()
    log.info(
        "bandit decay scheduler started (every %d day(s), factor=%.3f floor=%.2f)",
        interval_days,
        factor,
        floor,
    )
    return scheduler


def run_backfill_now() -> dict[str, int]:
    """One-shot for scripts / admin endpoints."""
    return backfill_once()
