"""Tests for the persisted-drift admin routes.

PR6 of the drift-feedback persistence track. PR1-PR5 stand up the
``verifier_drift_events`` / ``verifier_drift_patterns`` tables, dual-write
from ``verification_node``, aggregate / retention services, and the
``drift_feedback_source`` switch in ``prompt_feedback``. PR6 exposes
those reads / triggers to admin operators so the rollout can actually
be monitored without raw SQL.

Pinned contract:

1. ``GET /admin/drift/events``: returns event rows with persistence_enabled
   meta; ``overruled_only=True`` is the default so the hot pattern view
   stays the headline; ``since_hours`` is clamped to a positive window
   to prevent zero / negative typos from returning empty data.
2. ``GET /admin/drift/patterns``: returns the aggregated read model with
   the active ``feedback_source`` meta; supports ``dimension`` and
   ``failure_category`` filters so dashboards can pivot without
   re-querying.
3. ``POST /admin/drift/aggregation/run``: idempotently triggers
   :func:`refresh_verifier_drift_patterns` and returns its counters.
4. ``POST /admin/drift/retention/run``: idempotently triggers
   :func:`cleanup_expired_verifier_drift_events` and returns its
   counters.
5. ``require_admin_token`` is wired on every route so a misconfigured
   deployment can't surface the drift event log without a bearer token.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.v1 import admin as admin_api
from app.models.base import Base
from app.models.verifier_drift import VerifierDriftEvent, VerifierDriftPattern


def _session_factory():
    engine = create_engine(
        "sqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)


def _client(
    Session,
    *,
    api_token: str | None = None,
    allow_open_admin: bool = True,
    enable_verifier_drift_persistence: bool = True,
    drift_feedback_source: str = "db_shadow",
    verifier_drift_event_retention_days: int = 90,
    drift_pattern_aggregation_window_days: int = 30,
) -> TestClient:
    """Build a FastAPI TestClient bound to the in-memory drift DB.

    Mirrors :func:`tests.unit.test_admin_strategy_memory._client` so the
    overall admin fixture story stays uniform; the only delta is we
    pin a richer settings stub because the drift routes need to surface
    ``persistence_enabled`` / ``feedback_source`` / retention / window
    metadata in their payloads.
    """
    app = FastAPI()
    app.include_router(admin_api.router)
    app.include_router(admin_api.api_v1_router)

    @contextmanager
    def get_session():
        with Session() as sess:
            yield sess
            sess.commit()

    fake_settings = SimpleNamespace(
        api_token=api_token,
        allow_open_admin=allow_open_admin,
        app_env="dev",
        enable_verifier_drift_persistence=enable_verifier_drift_persistence,
        drift_feedback_source=drift_feedback_source,
        verifier_drift_event_retention_days=verifier_drift_event_retention_days,
        drift_pattern_aggregation_window_days=drift_pattern_aggregation_window_days,
    )
    admin_api.get_settings = lambda: fake_settings
    admin_api.get_session = get_session

    from app.services import drift_event_retention as retention_mod
    from app.services import drift_pattern_aggregation as aggregation_mod
    from app.tasks import drift_event_retention_tasks as retention_tasks
    from app.tasks import drift_pattern_aggregation_tasks as aggregation_tasks

    retention_tasks.get_session = get_session
    aggregation_tasks.get_session = get_session
    retention_tasks.get_settings = lambda: fake_settings
    aggregation_tasks.get_settings = lambda: fake_settings
    # Keep the service module symbols stable so the tasks' lazy lookups
    # see the patched ``get_session`` instead of the real one.
    retention_mod.cleanup_expired_verifier_drift_events  # noqa: B018 - keep ref
    aggregation_mod.refresh_verifier_drift_patterns  # noqa: B018 - keep ref

    return TestClient(app)


def _seed_event(
    sess,
    *,
    id_: str = "evt-1",
    dimension: str = "system_design",
    check_name: str | None = "Mentions concrete failure modes",
    overruled: bool = True,
    failure_categories: list[str] | None = None,
    days_ago: int = 0,
    turn_idx: int = 1,
    verifier_verdict: str = "partial",
    verifier_confidence: float = 0.78,
) -> None:
    sess.add(
        VerifierDriftEvent(
            id=id_,
            session_id="sess-x",
            trace_id="trace-x",
            turn_idx=turn_idx,
            dimension=dimension,
            job_level="senior",
            evaluator_passed=True,
            verifier_verdict=verifier_verdict,
            verifier_confidence=verifier_confidence,
            verifier_abstained=False,
            overruled=overruled,
            span_miss_count=0,
            span_total=0,
            overruled_check_name=check_name,
            evaluator_evidence_quotes=["we used Redis"],
            verifier_reasons=["evidence is generic boilerplate"],
            failure_categories=list(failure_categories or []),
            created_at=datetime.now(UTC) - timedelta(days=days_ago),
        )
    )


def _seed_pattern(
    sess,
    *,
    id_: str,
    dimension: str = "system_design",
    check_name: str = "Mentions concrete failure modes",
    failure_category: str = "__global__",
    uses: int = 5,
) -> None:
    now = datetime.now(UTC)
    sess.add(
        VerifierDriftPattern(
            id=id_,
            dimension=dimension,
            check_name=check_name,
            failure_category=failure_category,
            uses=uses,
            overruled_count=uses,
            overrule_rate=1.0,
            sample_evidence=["we used Redis"],
            reasons_sample=["evidence is generic boilerplate"],
            first_seen_at=now,
            last_seen_at=now,
        )
    )


def test_admin_drift_events_requires_admin_auth() -> None:
    """No bearer token + configured ``api_token`` → 401.

    Pins ``require_admin_token`` on the events route so the
    drift event log (which includes evidence quotes from real
    candidate answers) cannot leak from a misconfigured deployment.
    """
    Session = _session_factory()
    client = _client(Session, api_token="secret-token", allow_open_admin=False)

    res = client.get("/admin/drift/events")

    assert res.status_code == 401


def test_admin_drift_events_returns_persistence_meta_when_empty() -> None:
    """Empty table → ``count=0`` plus the active persistence flag so
    dashboards can distinguish "feature off" from "feature on, no
    data yet"."""
    Session = _session_factory()
    client = _client(
        Session, enable_verifier_drift_persistence=False
    )

    res = client.get("/admin/drift/events")

    assert res.status_code == 200
    body = res.json()
    assert body["count"] == 0
    assert body["events"] == []
    assert body["persistence_enabled"] is False
    assert body["overruled_only"] is True


def test_admin_drift_events_overruled_only_default_filters_clean_events() -> None:
    """Default ``overruled_only=True`` hides clean / abstain events so
    the headline view only shows hot patterns."""
    Session = _session_factory()
    with Session() as sess:
        _seed_event(sess, id_="evt-overruled", overruled=True)
        _seed_event(
            sess,
            id_="evt-clean",
            overruled=False,
            check_name=None,
            turn_idx=2,
        )
        sess.commit()

    client = _client(Session)
    res = client.get("/admin/drift/events")

    assert res.status_code == 200
    body = res.json()
    assert body["count"] == 1
    assert body["events"][0]["id"] == "evt-overruled"
    assert body["events"][0]["overruled"] is True


def test_admin_drift_events_overruled_only_false_returns_all() -> None:
    Session = _session_factory()
    with Session() as sess:
        _seed_event(sess, id_="evt-overruled", overruled=True)
        _seed_event(
            sess,
            id_="evt-clean",
            overruled=False,
            check_name=None,
            turn_idx=2,
        )
        sess.commit()

    client = _client(Session)
    res = client.get("/admin/drift/events?overruled_only=false")

    assert res.status_code == 200
    body = res.json()
    assert body["count"] == 2
    ids = {event["id"] for event in body["events"]}
    assert ids == {"evt-overruled", "evt-clean"}


def test_admin_drift_events_since_hours_clamps_to_positive_window() -> None:
    """``since_hours=0`` would otherwise return zero results (cutoff
    equals now); clamping to 1 hour matches the retention helper's
    "don't let an operator typo nuke observability" guarantee."""
    Session = _session_factory()
    with Session() as sess:
        _seed_event(sess, id_="evt-fresh", days_ago=0)
        sess.commit()

    client = _client(Session)
    res = client.get("/admin/drift/events?since_hours=0")

    assert res.status_code == 200
    body = res.json()
    assert body["since_hours"] == 1
    assert body["count"] == 1


def test_admin_drift_patterns_returns_feedback_source_meta() -> None:
    """Empty table → ``count=0`` + ``feedback_source`` meta so the
    admin can tell which renderer the running deployment is using
    (monitor / db_shadow / db)."""
    Session = _session_factory()
    client = _client(Session, drift_feedback_source="db_shadow")

    res = client.get("/admin/drift/patterns")

    assert res.status_code == 200
    body = res.json()
    assert body["count"] == 0
    assert body["patterns"] == []
    assert body["feedback_source"] == "db_shadow"


def test_admin_drift_patterns_filter_by_dimension() -> None:
    Session = _session_factory()
    with Session() as sess:
        _seed_pattern(sess, id_="pat-sd", dimension="system_design")
        _seed_pattern(sess, id_="pat-db", dimension="debugging")
        sess.commit()

    client = _client(Session)
    res = client.get("/admin/drift/patterns?dimension=system_design")

    assert res.status_code == 200
    body = res.json()
    assert body["count"] == 1
    assert body["patterns"][0]["dimension"] == "system_design"


def test_admin_drift_patterns_filter_by_failure_category() -> None:
    Session = _session_factory()
    with Session() as sess:
        _seed_pattern(
            sess,
            id_="pat-missing",
            failure_category="missing_metrics",
        )
        _seed_pattern(
            sess,
            id_="pat-global",
            failure_category="__global__",
        )
        sess.commit()

    client = _client(Session)
    res = client.get("/admin/drift/patterns?failure_category=missing_metrics")

    assert res.status_code == 200
    body = res.json()
    assert body["count"] == 1
    assert body["patterns"][0]["failure_category"] == "missing_metrics"


def test_admin_drift_aggregation_run_aggregates_events() -> None:
    """End-to-end trigger: seed an event, hit ``aggregation/run``,
    confirm the patterns table is populated with the two-layer fan
    out (one per failure_category + one ``__global__`` rollup)."""
    Session = _session_factory()
    with Session() as sess:
        _seed_event(
            sess,
            id_="evt-trigger",
            failure_categories=["missing_metrics"],
        )
        sess.commit()

    client = _client(Session)

    triggered = client.post("/admin/drift/aggregation/run")
    assert triggered.status_code == 200
    body = triggered.json()
    assert body["refreshed"] == 2  # missing_metrics bucket + __global__ rollup
    assert body["deleted"] == 0

    listed = client.get("/admin/drift/patterns")
    assert listed.status_code == 200
    failure_categories = {
        row["failure_category"] for row in listed.json()["patterns"]
    }
    assert failure_categories == {"missing_metrics", "__global__"}


def test_admin_drift_retention_run_deletes_old_events() -> None:
    Session = _session_factory()
    with Session() as sess:
        # ``days_ago=0`` keeps the survivor comfortably inside the
        # default 24h admin window; ``days_ago=1`` would sit *exactly*
        # at the boundary and leak microsecond drift into the assertion.
        _seed_event(sess, id_="evt-fresh", days_ago=0)
        _seed_event(
            sess,
            id_="evt-stale",
            days_ago=200,
            turn_idx=2,
        )
        sess.commit()

    client = _client(
        Session, verifier_drift_event_retention_days=90
    )

    triggered = client.post("/admin/drift/retention/run")
    assert triggered.status_code == 200
    assert triggered.json() == {"deleted": 1}

    listed = client.get("/admin/drift/events?overruled_only=false")
    assert listed.status_code == 200
    ids = {event["id"] for event in listed.json()["events"]}
    assert ids == {"evt-fresh"}
