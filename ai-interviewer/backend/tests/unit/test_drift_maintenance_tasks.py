from __future__ import annotations

from app.core import settings as settings_mod


def test_default_settings_keep_drift_maintenance_scheduler_off(monkeypatch) -> None:
    for key in (
        "ENABLE_DRIFT_MAINTENANCE_SCHEDULER",
        "DRIFT_PATTERN_AGGREGATION_INTERVAL_MINUTES",
        "DRIFT_EVENT_RETENTION_INTERVAL_HOURS",
    ):
        monkeypatch.delenv(key, raising=False)
    settings_mod.get_settings.cache_clear()

    settings = settings_mod.get_settings()

    assert settings.enable_drift_maintenance_scheduler is False
    assert settings.drift_pattern_aggregation_interval_minutes == 30
    assert settings.drift_event_retention_interval_hours == 24

    settings_mod.get_settings.cache_clear()


def test_start_drift_maintenance_scheduler_registers_two_jobs() -> None:
    from app.tasks.drift_maintenance_tasks import (
        start_drift_maintenance_scheduler,
    )

    scheduler = start_drift_maintenance_scheduler(
        aggregation_interval_minutes=7,
        retention_interval_hours=5,
    )
    try:
        job_ids = {job.id for job in scheduler.get_jobs()}
        assert job_ids == {
            "drift_pattern_aggregation",
            "drift_event_retention",
        }
    finally:
        scheduler.shutdown(wait=False)


def test_tracked_drift_aggregation_updates_status(monkeypatch) -> None:
    from app.tasks import drift_maintenance_tasks as mod

    mod.reset_drift_maintenance_status()
    monkeypatch.setattr(
        mod,
        "run_drift_pattern_aggregation_now",
        lambda: {"refreshed": 2, "deleted": 1},
    )

    result = mod.run_drift_pattern_aggregation_tracked()
    status = mod.get_drift_maintenance_status()

    assert result == {"refreshed": 2, "deleted": 1}
    assert status["aggregation"]["last_result"] == {"refreshed": 2, "deleted": 1}
    assert status["aggregation"]["last_error"] is None
    assert status["aggregation"]["last_started_at"] is not None
    assert status["aggregation"]["last_finished_at"] is not None
