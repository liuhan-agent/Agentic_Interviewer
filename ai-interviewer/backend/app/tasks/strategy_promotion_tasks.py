"""Task entrypoints for strategy signal promotion."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from threading import Lock
from typing import Literal

from apscheduler.schedulers.background import BackgroundScheduler

from app.core.logging import get_logger
from app.models import get_session
from app.services.strategy_promotion import (
    apply_strategy_quality_transitions,
    promote_strategy_signals,
)
from app.services.strategy_memory_stats import refresh_strategy_memory_stats

log = get_logger(__name__)

SCHEDULER_JOB_ID = "strategy_promotion"


@dataclass
class StrategyPromotionState:
    """In-process snapshot of the promotion scheduler/runner.

    Tracked separately from APScheduler because the admin UI also
    needs to surface manual-run results and the most recent error.
    A single process owns the scheduler so a module-level lock is
    sufficient.
    """

    enabled: bool = False
    interval_minutes: int = 0
    startup_delay_minutes: int = 0
    last_run_at: datetime | None = None
    last_run_kind: Literal["scheduled", "manual"] | None = None
    last_result: dict[str, int] | None = None
    last_error: str | None = None
    last_error_at: datetime | None = None


_state = StrategyPromotionState()
_state_lock = Lock()


def get_strategy_promotion_state() -> StrategyPromotionState:
    """Return a snapshot copy of the current promotion state."""
    with _state_lock:
        return StrategyPromotionState(
            enabled=_state.enabled,
            interval_minutes=_state.interval_minutes,
            startup_delay_minutes=_state.startup_delay_minutes,
            last_run_at=_state.last_run_at,
            last_run_kind=_state.last_run_kind,
            last_result=dict(_state.last_result) if _state.last_result else None,
            last_error=_state.last_error,
            last_error_at=_state.last_error_at,
        )


def reset_strategy_promotion_state() -> None:
    """Reset module state. Test-only helper."""
    global _state
    with _state_lock:
        _state = StrategyPromotionState()


def _record_run_success(
    result: dict[str, int],
    *,
    kind: Literal["scheduled", "manual"],
) -> None:
    with _state_lock:
        _state.last_run_at = datetime.now(UTC)
        _state.last_run_kind = kind
        _state.last_result = dict(result)
        _state.last_error = None
        _state.last_error_at = None


def _record_run_failure(error: BaseException) -> None:
    with _state_lock:
        _state.last_error = str(error) or error.__class__.__name__
        _state.last_error_at = datetime.now(UTC)


def run_strategy_promotion_now(
    *, kind: Literal["scheduled", "manual"] = "manual"
) -> dict[str, int]:
    """Run one promotion pass and return simple counters.

    Updates module state so the admin UI sees the freshest run
    outcome regardless of whether the trigger was the scheduler or
    a manual click.
    """
    try:
        with get_session() as session:
            refresh_strategy_memory_stats(session=session)
            promotion = asdict(promote_strategy_signals(session=session))
            quality = asdict(apply_strategy_quality_transitions(session=session))
    except BaseException as exc:
        _record_run_failure(exc)
        raise
    result = {
        "promoted": promotion["promoted"],
        "unchanged": promotion["unchanged"] + quality["unchanged"],
        "skipped": promotion["skipped"] + quality["skipped"],
        "disabled": quality["disabled"],
        "stabilized": quality["stabilized"],
    }
    _record_run_success(result, kind=kind)
    return result


def _run_strategy_promotion_tick() -> dict[str, int] | None:
    try:
        result = run_strategy_promotion_now(kind="scheduled")
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
        id=SCHEDULER_JOB_ID,
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()
    with _state_lock:
        _state.enabled = True
        _state.interval_minutes = interval
        _state.startup_delay_minutes = startup_delay
    log.info(
        "strategy promotion scheduler started "
        "(every %d min, first run in %d min)",
        interval,
        startup_delay,
    )
    return scheduler
