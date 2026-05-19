"""Periodic maintenance for persisted verifier-drift data."""
from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from typing import Any, Callable

from apscheduler.schedulers.background import BackgroundScheduler

from app.core.logging import get_logger
from app.tasks.drift_event_retention_tasks import run_drift_event_retention_now
from app.tasks.drift_pattern_aggregation_tasks import run_drift_pattern_aggregation_now

log = get_logger(__name__)

_EMPTY_JOB_STATUS: dict[str, Any] = {
    "last_started_at": None,
    "last_finished_at": None,
    "last_result": None,
    "last_error": None,
}
_STATUS: dict[str, dict[str, Any]] = {
    "aggregation": deepcopy(_EMPTY_JOB_STATUS),
    "retention": deepcopy(_EMPTY_JOB_STATUS),
}


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def reset_drift_maintenance_status() -> None:
    _STATUS["aggregation"] = deepcopy(_EMPTY_JOB_STATUS)
    _STATUS["retention"] = deepcopy(_EMPTY_JOB_STATUS)


def get_drift_maintenance_status() -> dict[str, dict[str, Any]]:
    return deepcopy(_STATUS)


def _run_tracked(
    name: str,
    runner: Callable[[], dict[str, int]],
) -> dict[str, int]:
    status = _STATUS[name]
    status["last_started_at"] = _now_iso()
    status["last_finished_at"] = None
    status["last_result"] = None
    status["last_error"] = None
    try:
        result = runner()
    except Exception as exc:
        status["last_finished_at"] = _now_iso()
        status["last_error"] = str(exc)
        raise
    status["last_finished_at"] = _now_iso()
    status["last_result"] = dict(result)
    return result


def run_drift_pattern_aggregation_tracked() -> dict[str, int]:
    return _run_tracked("aggregation", run_drift_pattern_aggregation_now)


def run_drift_event_retention_tracked() -> dict[str, int]:
    return _run_tracked("retention", run_drift_event_retention_now)


def start_drift_maintenance_scheduler(
    *,
    aggregation_interval_minutes: int = 30,
    retention_interval_hours: int = 24,
) -> BackgroundScheduler:
    scheduler = BackgroundScheduler(daemon=True)
    scheduler.add_job(
        run_drift_pattern_aggregation_tracked,
        "interval",
        minutes=max(1, int(aggregation_interval_minutes or 30)),
        id="drift_pattern_aggregation",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        run_drift_event_retention_tracked,
        "interval",
        hours=max(1, int(retention_interval_hours or 24)),
        id="drift_event_retention",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()
    log.info(
        "drift maintenance scheduler started "
        "(aggregation every %d min, retention every %d hour(s))",
        max(1, int(aggregation_interval_minutes or 30)),
        max(1, int(retention_interval_hours or 24)),
    )
    return scheduler
