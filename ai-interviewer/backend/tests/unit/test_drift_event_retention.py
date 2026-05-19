"""Tests for the verifier-drift event retention sweep.

PR4 of the drift-feedback persistence track: once events live in DB,
something has to garbage-collect them so the table does not grow
without bound. The retention sweep is intentionally minimal — it
deletes rows older than ``retention_days`` and returns the count so the
admin endpoint can surface it.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
from app.models.verifier_drift import VerifierDriftEvent
from app.services.drift_event_retention import (
    cleanup_expired_verifier_drift_events,
)


def _session_factory():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)


def _add(sess, *, id_: str, days_ago: int) -> None:
    sess.add(
        VerifierDriftEvent(
            id=id_,
            session_id="sess-x",
            trace_id="trace-x",
            turn_idx=1,
            dimension="system_design",
            job_level="senior",
            evaluator_passed=True,
            verifier_verdict="partial",
            verifier_confidence=0.7,
            verifier_abstained=False,
            overruled=True,
            span_miss_count=0,
            span_total=0,
            overruled_check_name="Mentions concrete failure modes",
            created_at=datetime.now(UTC) - timedelta(days=days_ago),
        )
    )


def test_retention_returns_zero_when_table_empty() -> None:
    Session = _session_factory()
    with Session() as sess:
        result = cleanup_expired_verifier_drift_events(
            session=sess, retention_days=90
        )

    assert result.deleted == 0


def test_retention_keeps_fresh_and_deletes_stale() -> None:
    Session = _session_factory()
    with Session() as sess:
        _add(sess, id_="evt-fresh", days_ago=5)
        _add(sess, id_="evt-edge", days_ago=89)
        _add(sess, id_="evt-stale-90", days_ago=91)
        _add(sess, id_="evt-stale-365", days_ago=400)
        sess.commit()

        result = cleanup_expired_verifier_drift_events(
            session=sess, retention_days=90
        )
        survivors = sorted(
            row.id for row in sess.scalars(select(VerifierDriftEvent))
        )

    assert result.deleted == 2
    assert survivors == ["evt-edge", "evt-fresh"]


def test_retention_is_idempotent() -> None:
    Session = _session_factory()
    with Session() as sess:
        _add(sess, id_="evt-stale", days_ago=200)
        sess.commit()

        first = cleanup_expired_verifier_drift_events(
            session=sess, retention_days=30
        )
        second = cleanup_expired_verifier_drift_events(
            session=sess, retention_days=30
        )

    assert first.deleted == 1
    assert second.deleted == 0


def test_retention_caps_to_positive_window() -> None:
    """A 0 / negative day window must not nuke the table — clamp to 1
    so an operator typo can never destroy fresh data."""
    Session = _session_factory()
    with Session() as sess:
        _add(sess, id_="evt-fresh", days_ago=0)
        _add(sess, id_="evt-stale", days_ago=200)
        sess.commit()

        result = cleanup_expired_verifier_drift_events(
            session=sess, retention_days=0
        )
        survivors = sorted(
            row.id for row in sess.scalars(select(VerifierDriftEvent))
        )

    assert result.deleted == 1
    assert survivors == ["evt-fresh"]
