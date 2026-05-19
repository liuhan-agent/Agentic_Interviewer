from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker

from app.api.v1 import admin as admin_api
from app.memory import strategy_store
from app.models.base import Base
from app.models.generation_trace import GenerationTrace
from app.models.strategy_memory import (
    StrategyMemory,
    StrategyMemoryUsage,
    StrategySignal,
)


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
    strategy_store.get_settings = lambda: SimpleNamespace(strategy_memory_backend="db")
    strategy_store.get_session = get_session
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
            StrategyMemory(
                id="seed:senior_system_design",
                slug="senior_system_design",
                name="Senior System Design",
                description="Deep probes.",
                source="seed",
                memory_key="seed:system_design:senior",
                dimensions=["system_design"],
                job_levels=["senior"],
                body_markdown="Body",
                status="active",
                promotion_stage="seed",
                confidence=0.8,
                support_count=20,
            )
        )
        sess.add(
            StrategySignal(
                id="signal-1",
                signal_key="sess-1:qa:score_recovery:senior:system_design:plan_hint",
                group_key="qa:score_recovery:senior:system_design:plan_hint",
                session_id="sess-1",
                turn_idx=1,
                dimension="system_design",
                job_level="senior",
                action_id="plan_hint",
                plan_template="simple",
                failure_categories=["missing_metrics"],
                score_after=8.0,
                immediate_reward=0.8,
                verifier_overruled=False,
                signal_type="score_recovery",
                status="observed",
            )
        )
        sess.add(
            StrategyMemoryUsage(
                id="usage-1",
                strategy_id="seed:senior_system_design",
                session_id="sess-1",
                turn_idx=1,
                trace_id="trace-1",
                context_key="senior:system_design",
                action_id="plan_hint",
                immediate_reward=0.8,
                score=8.0,
                passed=True,
                verifier_overruled=False,
            )
        )
        sess.commit()
    return Session


def test_admin_strategies_include_db_metadata_and_status_actions() -> None:
    Session = _session_factory()
    client = _client(Session)

    listed = client.get("/admin/strategies")
    assert listed.status_code == 200
    strategy = listed.json()["strategies"][0]
    assert strategy["id"] == "seed:senior_system_design"
    assert strategy["source"] == "seed"
    assert strategy["status"] == "active"
    assert strategy["promotion_stage"] == "seed"
    assert strategy["confidence"] == 0.8
    assert strategy["support_count"] == 20

    disabled = client.post("/admin/strategies/seed%3Asenior_system_design/disable")
    assert disabled.status_code == 200
    assert disabled.json() == {"id": "seed:senior_system_design", "status": "disabled"}

    listed_after_disable = client.get("/admin/strategies")
    assert listed_after_disable.status_code == 200
    disabled_strategy = listed_after_disable.json()["strategies"][0]
    assert disabled_strategy["id"] == "seed:senior_system_design"
    assert disabled_strategy["status"] == "disabled"

    archived = client.post("/admin/strategies/seed%3Asenior_system_design/archive")
    assert archived.status_code == 200
    assert archived.json() == {"id": "seed:senior_system_design", "status": "archived"}

    listed_after_archive = client.get("/admin/strategies")
    assert listed_after_archive.status_code == 200
    archived_strategy = listed_after_archive.json()["strategies"][0]
    assert archived_strategy["id"] == "seed:senior_system_design"
    assert archived_strategy["status"] == "archived"


def test_admin_strategy_signals_and_usages_are_listed() -> None:
    Session = _session_factory()
    client = _client(Session)

    signals = client.get("/admin/strategy-signals")
    usages = client.get("/admin/strategy-usages")

    assert signals.status_code == 200
    assert signals.json()["count"] == 1
    signal_row = signals.json()["signals"][0]
    assert signal_row["group_key"].startswith("qa:score_recovery")
    # PR5: failure_categories surfaces the structured taxonomy so
    # admins can group signals by failure type without re-running
    # the keyword inference. ``[]`` is also acceptable (no category).
    assert "failure_categories" in signal_row
    assert signal_row["failure_categories"] == ["missing_metrics"]

    assert usages.status_code == 200
    assert usages.json()["count"] == 1
    assert usages.json()["usages"][0]["strategy_id"] == "seed:senior_system_design"


def test_admin_failure_category_overlap_endpoint_returns_counts() -> None:
    """PR6: ``/admin/failure-category-stats`` returns the 4 mutually
    exclusive buckets plus the sample size that fed the comparison."""
    Session = _session_factory()
    with Session() as sess:
        sess.add(
            GenerationTrace(
                trace_id="trace-overlap-both",
                session_id="sess-overlap",
                turn_idx=0,
                node="evaluator",
                evaluation={
                    "failure_categories": ["missing_metrics"],
                    "failure_reason": "缺少量化指标",
                    "weaknesses": ["缺少量化指标"],
                },
            )
        )
        sess.add(
            GenerationTrace(
                trace_id="trace-overlap-neither",
                session_id="sess-overlap",
                turn_idx=1,
                node="evaluator",
                evaluation={
                    "failure_categories": [],
                    "failure_reason": None,
                    "weaknesses": [],
                },
            )
        )
        sess.commit()
    client = _client(Session)

    res = client.get("/admin/failure-category-stats")

    assert res.status_code == 200
    payload = res.json()
    assert payload["sample_size"] == 2
    assert payload["both"] == 1
    assert payload["neither"] == 1
    assert payload["llm_only"] == 0
    assert payload["normalize_only"] == 0
    assert payload["limit"] == 200
