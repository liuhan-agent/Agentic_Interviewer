from __future__ import annotations

import asyncio
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _reset_checkpoint_metrics() -> None:
    from app.core.metrics import reset_checkpoint_metrics_for_tests

    reset_checkpoint_metrics_for_tests()
    yield
    reset_checkpoint_metrics_for_tests()


def test_checkpoint_write_snapshot_reports_percentiles_and_failures() -> None:
    from app.core.metrics import (
        checkpoint_write_snapshot,
        record_checkpoint_write,
        record_checkpoint_write_failure,
    )

    for elapsed_ms in (10, 20, 30):
        record_checkpoint_write(
            backend="memory",
            operation="put",
            elapsed_ms=elapsed_ms,
        )
    record_checkpoint_write_failure(backend="memory", operation="put")

    snapshot = checkpoint_write_snapshot()

    assert snapshot["memory:put"] == {
        "count": 3,
        "p50_ms": 20.0,
        "p95_ms": 30.0,
        "p99_ms": 30.0,
        "failures": 1,
    }


def test_admin_metrics_exposes_checkpoint_histogram(client: TestClient) -> None:
    from app.core.metrics import record_checkpoint_write

    record_checkpoint_write(
        backend="postgres",
        operation="put_writes",
        elapsed_ms=42,
    )

    resp = client.get("/admin/metrics")

    assert resp.status_code == 200
    assert "checkpoint_write_duration_seconds_bucket" in resp.text
    assert 'backend="postgres"' in resp.text
    assert 'operation="put_writes"' in resp.text


def test_admin_checkpoint_health_exposes_latency_summary(client: TestClient) -> None:
    from app.core.metrics import record_checkpoint_write

    record_checkpoint_write(backend="memory", operation="put", elapsed_ms=15)
    record_checkpoint_write(backend="memory", operation="put", elapsed_ms=25)

    resp = client.get("/admin/checkpoint/health")

    assert resp.status_code == 200
    assert resp.json()["checkpoint_writes"]["memory:put"] == {
        "count": 2,
        "p50_ms": 15.0,
        "p95_ms": 25.0,
        "p99_ms": 25.0,
        "failures": 0,
    }


def test_wrap_saver_with_metrics_records_write_latency(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.engine.workflow import checkpoint_metrics

    writes: list[dict[str, Any]] = []
    latest_events: list[int] = []

    class _Saver:
        def put(self, *args: Any, **kwargs: Any) -> str:
            return "ok"

    monkeypatch.setattr(
        checkpoint_metrics,
        "record_checkpoint_write",
        lambda **kwargs: writes.append(kwargs),
    )
    monkeypatch.setattr(
        checkpoint_metrics,
        "record_checkpoint_write_event",
        lambda *, elapsed_ms: latest_events.append(elapsed_ms),
    )

    saver = checkpoint_metrics.wrap_saver_with_metrics(_Saver(), backend="memory")

    assert saver.put("config", {"state": 1}) == "ok"
    assert writes[0]["backend"] == "memory"
    assert writes[0]["operation"] == "put"
    assert writes[0]["elapsed_ms"] >= 0
    assert latest_events == [writes[0]["elapsed_ms"]]


def test_wrap_saver_with_metrics_records_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.engine.workflow import checkpoint_metrics

    failures: list[dict[str, str]] = []

    class _Saver:
        def put_writes(self, *args: Any, **kwargs: Any) -> None:
            raise RuntimeError("write failed")

    monkeypatch.setattr(
        checkpoint_metrics,
        "record_checkpoint_write_failure",
        lambda **kwargs: failures.append(kwargs),
    )

    saver = checkpoint_metrics.wrap_saver_with_metrics(_Saver(), backend="postgres")

    with pytest.raises(RuntimeError, match="write failed"):
        saver.put_writes("config", [("channel", "value")])
    assert failures == [{"backend": "postgres", "operation": "put_writes"}]


@pytest.mark.asyncio
async def test_wrap_saver_with_metrics_records_awaitable_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.engine.workflow import checkpoint_metrics

    writes: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []

    class _Saver:
        def aput(self, *args: Any, **kwargs: Any) -> asyncio.Future[str]:
            future: asyncio.Future[str] = asyncio.Future()
            future.set_exception(RuntimeError("async write failed"))
            return future

    monkeypatch.setattr(
        checkpoint_metrics,
        "record_checkpoint_write",
        lambda **kwargs: writes.append(kwargs),
    )
    monkeypatch.setattr(
        checkpoint_metrics,
        "record_checkpoint_write_failure",
        lambda **kwargs: failures.append(kwargs),
    )

    saver = checkpoint_metrics.wrap_saver_with_metrics(_Saver(), backend="postgres")

    with pytest.raises(RuntimeError, match="async write failed"):
        await saver.aput("config", {"state": 1})
    assert writes == []
    assert failures == [{"backend": "postgres", "operation": "aput"}]


def test_timing_trace_reset_clears_checkpoint_write_ms() -> None:
    from app.core import timing

    token = timing.start_timing_trace()
    try:
        timing.record_checkpoint_write_event(elapsed_ms=17)
        assert timing.get_latest_db_write_ms() == 17
    finally:
        timing.reset_timing_trace(token)

    assert timing.get_latest_db_write_ms() is None


def test_reward_update_trace_includes_latest_db_write_ms(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core import timing
    from app.engine.workflow.nodes import reward_update as reward_update_mod

    traced_payloads: list[dict[str, Any]] = []

    class _Bandit:
        def update(self, _context_key: str, _action_id: str, _reward: float) -> None:
            return None

    class _Tracer:
        def trace_node_event(
            self,
            _state: dict[str, Any],
            *,
            payload: dict[str, Any],
            **_kwargs: Any,
        ) -> None:
            traced_payloads.append(payload)

    monkeypatch.setattr(reward_update_mod, "get_bandit", lambda: _Bandit())
    monkeypatch.setattr(reward_update_mod, "get_tracer", lambda: _Tracer())
    monkeypatch.setattr(
        reward_update_mod,
        "immediate_reward",
        lambda **_kwargs: 0.5,
    )

    token = timing.start_timing_trace()
    try:
        timing.record_checkpoint_write_event(elapsed_ms=23)
        reward_update_mod.reward_update_node(
            {
                "session_id": "sess-checkpoint-latency",
                "trace_id": "trace-checkpoint-latency",
                "turn_idx": 1,
                "current_dimension": "system_design",
                "current_question": {
                    "question": "Q",
                    "dimension": "system_design",
                },
                "evaluation": {"score": 8.0, "passed": True},
                "selected_action": {
                    "id": "deep_probe",
                    "policy_context_keys": ["senior:system_design"],
                },
                "job_spec": {"level": "senior"},
            }
        )  # type: ignore[arg-type]
    finally:
        timing.reset_timing_trace(token)

    assert traced_payloads[-1]["db_write_ms"] == 23


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    from app.api.v1 import admin as admin_api
    from app.core import settings as settings_mod

    class _Settings:
        app_env = "dev"
        api_token = None
        allow_open_admin = True
        database_url = "sqlite:///:memory:"
        policy_mode = "template"
        thompson_exploration_rate = 0.15
        enable_bandit_decay = False
        bandit_decay_factor = 0.99
        bandit_decay_floor = 1.0
        bandit_decay_interval_days = 1
        langsmith_tracing = False
        langsmith_endpoint = "https://api.smith.langchain.com"
        effective_langsmith_project = "agentic-interviewer-test"

    monkeypatch.setattr(admin_api, "get_settings", lambda: _Settings())
    monkeypatch.setattr(settings_mod, "get_settings", lambda: _Settings())

    app = FastAPI()
    app.include_router(admin_api.router)
    return TestClient(app)
