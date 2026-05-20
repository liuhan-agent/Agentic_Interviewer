from __future__ import annotations

from types import SimpleNamespace

from app import main as app_main
from app.core.settings import Settings


def test_privacy_cleanup_scheduler_settings_default_disabled() -> None:
    settings = Settings()

    assert settings.enable_privacy_cleanup is False
    assert settings.privacy_cleanup_interval_hours == 24


def test_run_privacy_cleanup_now_applies_cleanup(monkeypatch) -> None:
    from app.tasks import privacy_cleanup_tasks

    calls: list[dict] = []

    def cleanup_expired_data(*, dry_run: bool, batch_size: int | None = None):
        calls.append({"dry_run": dry_run, "batch_size": batch_size})
        return {"dry_run": dry_run, "batch_size": batch_size}

    monkeypatch.setattr("app.services.privacy_cleanup.cleanup_expired_data", cleanup_expired_data)

    result = privacy_cleanup_tasks.run_privacy_cleanup_now(batch_size=25)

    assert result == {"dry_run": False, "batch_size": 25}
    assert calls == [{"dry_run": False, "batch_size": 25}]


def test_start_privacy_cleanup_scheduler_registers_interval_job(monkeypatch) -> None:
    from app.tasks import privacy_cleanup_tasks

    monkeypatch.setattr(
        "app.services.privacy_cleanup.cleanup_expired_data",
        lambda *, dry_run, batch_size=None: {"dry_run": dry_run, "batch_size": batch_size},
    )
    monkeypatch.setattr(
        "app.scripts.cleanup_session_anchor_chunks.run_cleanup",
        lambda: {"total_deleted": 0},
    )

    scheduler = privacy_cleanup_tasks.start_privacy_cleanup_scheduler(
        interval_hours=7,
        batch_size=11,
    )
    try:
        jobs = scheduler.get_jobs()
        assert [job.id for job in jobs] == ["privacy_cleanup"]
        assert "7:00:00" in str(jobs[0].trigger)
    finally:
        scheduler.shutdown(wait=False)


def test_fastapi_lifecycle_starts_and_stops_privacy_cleanup_scheduler(monkeypatch) -> None:
    calls: list[tuple[int, int]] = []

    class _Scheduler:
        def __init__(self) -> None:
            self.shutdown_wait: bool | None = None

        def shutdown(self, *, wait: bool) -> None:
            self.shutdown_wait = wait

    scheduler = _Scheduler()

    def start_privacy_cleanup_scheduler(
        *,
        interval_hours: int,
        batch_size: int,
    ):
        calls.append((interval_hours, batch_size))
        return scheduler

    monkeypatch.setattr(app_main, "run_preflight", lambda settings: {})
    monkeypatch.setattr(app_main, "init_db", lambda: None)
    monkeypatch.setattr(
        app_main,
        "start_privacy_cleanup_scheduler",
        start_privacy_cleanup_scheduler,
        raising=False,
    )
    monkeypatch.setattr(
        "app.services.session_manager.get_session_manager",
        lambda: SimpleNamespace(rehydrate=lambda: 0),
    )

    app = SimpleNamespace(state=SimpleNamespace())
    settings = SimpleNamespace(
        rehydrate_bandit_on_start=False,
        enable_outcome_sync=False,
        enable_bandit_decay=False,
        enable_strategy_dream=False,
        enable_strategy_promotion_scheduler=False,
        enable_drift_maintenance_scheduler=False,
        enable_privacy_cleanup=True,
        privacy_cleanup_interval_hours=7,
        privacy_cleanup_batch_size=11,
    )

    app_main._run_startup(app, settings)
    assert calls == [(7, 11)]
    assert app.state.privacy_cleanup_scheduler is scheduler

    app_main._run_shutdown(app)
    assert scheduler.shutdown_wait is False


def test_fastapi_lifecycle_starts_and_stops_strategy_promotion_scheduler(
    monkeypatch,
) -> None:
    calls: list[tuple[int, int]] = []

    class _Scheduler:
        def __init__(self) -> None:
            self.shutdown_wait: bool | None = None

        def shutdown(self, *, wait: bool) -> None:
            self.shutdown_wait = wait

    scheduler = _Scheduler()

    def start_strategy_promotion_scheduler(
        *,
        interval_minutes: int,
        startup_delay_minutes: int,
    ):
        calls.append((interval_minutes, startup_delay_minutes))
        return scheduler

    monkeypatch.setattr(app_main, "run_preflight", lambda settings: {})
    monkeypatch.setattr(app_main, "init_db", lambda: None)
    monkeypatch.setattr(
        app_main,
        "start_strategy_promotion_scheduler",
        start_strategy_promotion_scheduler,
        raising=False,
    )
    monkeypatch.setattr(
        "app.services.session_manager.get_session_manager",
        lambda: SimpleNamespace(rehydrate=lambda: 0),
    )

    app = SimpleNamespace(state=SimpleNamespace())
    settings = SimpleNamespace(
        rehydrate_bandit_on_start=False,
        enable_outcome_sync=False,
        enable_bandit_decay=False,
        enable_strategy_dream=False,
        enable_strategy_promotion_scheduler=True,
        strategy_promotion_interval_minutes=7,
        strategy_promotion_startup_delay_minutes=2,
        enable_drift_maintenance_scheduler=False,
        enable_privacy_cleanup=False,
    )

    app_main._run_startup(app, settings)
    assert calls == [(7, 2)]
    assert app.state.strategy_promotion_scheduler is scheduler

    app_main._run_shutdown(app)
    assert scheduler.shutdown_wait is False


def test_fastapi_lifecycle_leaves_strategy_promotion_scheduler_off(
    monkeypatch,
) -> None:
    calls: list[str] = []

    monkeypatch.setattr(app_main, "run_preflight", lambda settings: {})
    monkeypatch.setattr(app_main, "init_db", lambda: None)
    monkeypatch.setattr(
        app_main,
        "start_strategy_promotion_scheduler",
        lambda **_kwargs: calls.append("started"),
        raising=False,
    )
    monkeypatch.setattr(
        "app.services.session_manager.get_session_manager",
        lambda: SimpleNamespace(rehydrate=lambda: 0),
    )

    app = SimpleNamespace(state=SimpleNamespace())
    settings = SimpleNamespace(
        rehydrate_bandit_on_start=False,
        enable_outcome_sync=False,
        enable_bandit_decay=False,
        enable_strategy_dream=False,
        enable_strategy_promotion_scheduler=False,
        enable_drift_maintenance_scheduler=False,
        enable_privacy_cleanup=False,
    )

    app_main._run_startup(app, settings)

    assert calls == []
