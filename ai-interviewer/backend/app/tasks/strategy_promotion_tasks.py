"""Task entrypoints for strategy signal promotion."""
from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler

from app.core.logging import get_logger
from app.models import get_session
from app.services.strategy_promotion import (
    apply_strategy_quality_transitions,
    promote_strategy_signals,
)
from app.services.strategy_memory_stats import refresh_strategy_memory_stats

log = get_logger(__name__)


def run_strategy_promotion_now() -> dict[str, int]:
    """Run one promotion pass and return simple counters."""
    with get_session() as session:
        refresh_strategy_memory_stats(session=session)
        promotion = asdict(promote_strategy_signals(session=session))
        quality = asdict(apply_strategy_quality_transitions(session=session))
    return {
        "promoted": promotion["promoted"],
        "unchanged": promotion["unchanged"] + quality["unchanged"],
        "skipped": promotion["skipped"] + quality["skipped"],
        "disabled": quality["disabled"],
        "stabilized": quality["stabilized"],
    }


def _run_strategy_promotion_tick() -> dict[str, int] | None:
    try:
        result = run_strategy_promotion_now()
    except Exception:
        log.exception("strategy promotion tick failed")
        return None
    log.info("strategy promotion tick completed: %s", result)
    return result


def start_strategy_promotion_scheduler(
    *,
    interval_minutes: int = 60,
    startup_delay_minutes: int = 5,
) -> BackgroundScheduler:
    """Start the in-process scheduler for strategy promotion."""
    interval = max(1, int(interval_minutes or 60))
    startup_delay = max(0, int(startup_delay_minutes or 0))
    first_run_at = datetime.now(UTC) + timedelta(minutes=startup_delay)

    scheduler = BackgroundScheduler(daemon=True)
    scheduler.add_job(
        _run_strategy_promotion_tick,
        "interval",
        minutes=interval,
        start_date=first_run_at,
        id="strategy_promotion",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()
    log.info(
        "strategy promotion scheduler started "
        "(every %d min, first run in %d min)",
        interval,
        startup_delay,
    )
    return scheduler
