from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker

from app.api.v1 import admin as admin_api
from app.models.base import Base
from app.models.strategy_memory import StrategyMemoryUsage


def _client(session_factory) -> TestClient:
    app = FastAPI()
    app.include_router(admin_api.router)
    app.include_router(admin_api.api_v1_router)

    @contextmanager
    def get_session():
        with session_factory() as sess:
            yield sess
            sess.commit()

    admin_api.get_settings = lambda: SimpleNamespace(api_token=None, allow_open_admin=True)
    admin_api.get_session = get_session
    return TestClient(app)


def _session_factory():
    engine = create_engine(
        "sqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    with Session() as sess:
        sess.add(
            StrategyMemoryUsage(
                id="usage-1",
                strategy_id="seed:senior_system_design",
                session_id="sess-1",
                turn_idx=1,
                trace_id="trace-1",
                context_key="senior:system_design",
                action_id="plan_hint",
                immediate_reward=0.4,
                delayed_reward=0.9,
                score=8.0,
                passed=True,
                verifier_overruled=False,
                helpful_score=0.8,
            )
        )
        sess.commit()
    return Session


def test_admin_strategy_stats_can_refresh_and_list_stats() -> None:
    Session = _session_factory()
    client = _client(Session)

    refreshed = client.post("/admin/strategy-stats/refresh")
    assert refreshed.status_code == 200
    assert refreshed.json() == {"refreshed": 2, "deleted": 0}

    listed = client.get("/admin/strategy-stats")
    assert listed.status_code == 200
    body = listed.json()
    assert body["count"] == 2
    stats = {row["context_key"]: row for row in body["stats"]}

    global_stats = stats["__global__"]
    assert global_stats["strategy_id"] == "seed:senior_system_design"
    assert global_stats["uses"] == 1
    assert global_stats["avg_blended_reward"] == 0.9
    assert global_stats["overrule_rate"] == 0.0
    assert global_stats["helpful_avg"] == 0.8

    context_stats = stats["senior:system_design"]
    assert context_stats["pass_rate"] == 1.0
    assert context_stats["last_used_at"] is not None
