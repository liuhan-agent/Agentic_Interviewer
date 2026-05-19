"""Tests for ``refresh_verifier_drift_patterns``.

PR3 of the drift-feedback persistence track: roll the raw event table
into the ``verifier_drift_patterns`` read model so PR5 can render the
top-N overruled patterns by ``(dimension, check, failure_category)`` and
``(dimension, check, "__global__")`` without re-scanning the event log
on every turn.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
from app.models.verifier_drift import VerifierDriftEvent, VerifierDriftPattern
from app.services.drift_pattern_aggregation import (
    GLOBAL_FAILURE_CATEGORY,
    refresh_verifier_drift_patterns,
)


def _session_factory():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)


def _add_event(
    sess,
    *,
    id_: str,
    dimension: str = "system_design",
    check_name: str | None = "Mentions concrete failure modes",
    overruled: bool = True,
    failure_categories: list[str] | None = None,
    evidence: list[str] | None = None,
    reasons: list[str] | None = None,
    created_at: datetime | None = None,
    job_level: str = "senior",
    turn_idx: int = 1,
) -> None:
    sess.add(
        VerifierDriftEvent(
            id=id_,
            session_id="sess-x",
            trace_id="trace-x",
            turn_idx=turn_idx,
            dimension=dimension,
            job_level=job_level,
            evaluator_passed=True,
            verifier_verdict="partial",
            verifier_confidence=0.8,
            verifier_abstained=False,
            overruled=overruled,
            span_miss_count=0,
            span_total=0,
            overruled_check_name=check_name,
            evaluator_evidence_quotes=list(evidence or []),
            verifier_reasons=list(reasons or []),
            failure_categories=list(failure_categories or []),
            created_at=created_at or datetime.now(UTC),
        )
    )


def test_refresh_returns_zero_when_no_events() -> None:
    Session = _session_factory()
    with Session() as sess:
        result = refresh_verifier_drift_patterns(session=sess)
        rows = list(sess.scalars(select(VerifierDriftPattern)))

    assert result.refreshed == 0
    assert result.deleted == 0
    assert rows == []


def test_single_event_single_failure_category_produces_two_rows() -> None:
    """One event with one failure_category fans out to:
    - (dim, check, failure_cat) bucket
    - (dim, check, "__global__") rollup"""
    Session = _session_factory()
    with Session() as sess:
        _add_event(
            sess,
            id_="evt-1",
            failure_categories=["missing_metrics"],
            evidence=["we used Redis"],
            reasons=["evidence is generic boilerplate"],
        )
        sess.commit()

        result = refresh_verifier_drift_patterns(session=sess)
        rows = list(sess.scalars(select(VerifierDriftPattern)))

    assert result.refreshed == 2
    assert result.deleted == 0
    assert len(rows) == 2

    by_failure_category = {row.failure_category: row for row in rows}
    assert "missing_metrics" in by_failure_category
    assert GLOBAL_FAILURE_CATEGORY in by_failure_category

    bucket = by_failure_category["missing_metrics"]
    assert bucket.dimension == "system_design"
    assert bucket.check_name == "Mentions concrete failure modes"
    assert bucket.uses == 1
    assert bucket.overruled_count == 1
    assert bucket.overrule_rate == 1.0
    assert bucket.sample_evidence == ["we used Redis"]
    assert bucket.reasons_sample == ["evidence is generic boilerplate"]

    rollup = by_failure_category[GLOBAL_FAILURE_CATEGORY]
    assert rollup.uses == 1
    assert rollup.overruled_count == 1


def test_event_with_no_failure_categories_only_contributes_to_global() -> None:
    """Empty list means we only know it overruled — record it at the
    rollup layer so admin can still see the dimension/check is hot."""
    Session = _session_factory()
    with Session() as sess:
        _add_event(sess, id_="evt-noscat", failure_categories=[])
        sess.commit()

        result = refresh_verifier_drift_patterns(session=sess)
        rows = list(sess.scalars(select(VerifierDriftPattern)))

    assert result.refreshed == 1
    assert len(rows) == 1
    assert rows[0].failure_category == GLOBAL_FAILURE_CATEGORY
    assert rows[0].uses == 1


def test_event_with_multiple_failure_categories_fans_out() -> None:
    """N failure_categories on one event → N per-category buckets + 1
    rollup row. ``uses`` on each per-category bucket is 1 (one event)
    and the rollup is also 1 (also one event, not summed)."""
    Session = _session_factory()
    with Session() as sess:
        _add_event(
            sess,
            id_="evt-multi",
            failure_categories=["missing_metrics", "unclear_architecture"],
        )
        sess.commit()

        result = refresh_verifier_drift_patterns(session=sess)
        rows = list(sess.scalars(select(VerifierDriftPattern)))

    assert result.refreshed == 3
    by_failure_category = {row.failure_category: row for row in rows}
    assert by_failure_category["missing_metrics"].uses == 1
    assert by_failure_category["unclear_architecture"].uses == 1
    assert by_failure_category[GLOBAL_FAILURE_CATEGORY].uses == 1


def test_multiple_events_same_bucket_aggregate_uses() -> None:
    """Two events in (dim, check, missing_metrics) → uses=2 in that bucket."""
    Session = _session_factory()
    with Session() as sess:
        _add_event(
            sess,
            id_="evt-a",
            failure_categories=["missing_metrics"],
            evidence=["we used Redis"],
            reasons=["generic boilerplate"],
        )
        _add_event(
            sess,
            id_="evt-b",
            failure_categories=["missing_metrics"],
            evidence=["we used Kafka"],
            reasons=["no quantified scale"],
            turn_idx=2,
        )
        sess.commit()

        refresh_verifier_drift_patterns(session=sess)
        rows = list(sess.scalars(select(VerifierDriftPattern)))

    by_failure_category = {row.failure_category: row for row in rows}
    bucket = by_failure_category["missing_metrics"]
    assert bucket.uses == 2
    assert bucket.overruled_count == 2
    # Sample evidence deduped + ordered by first-seen.
    assert bucket.sample_evidence == ["we used Redis", "we used Kafka"]
    assert bucket.reasons_sample == ["generic boilerplate", "no quantified scale"]


def test_events_outside_window_are_excluded() -> None:
    """``window_days`` filters out stale events so the patterns stay
    fresh — events older than the window do not influence the totals."""
    Session = _session_factory()
    with Session() as sess:
        _add_event(
            sess,
            id_="evt-fresh",
            failure_categories=["missing_metrics"],
            created_at=datetime.now(UTC) - timedelta(days=5),
        )
        _add_event(
            sess,
            id_="evt-stale",
            failure_categories=["missing_metrics"],
            created_at=datetime.now(UTC) - timedelta(days=120),
        )
        sess.commit()

        refresh_verifier_drift_patterns(session=sess, window_days=30)
        rows = list(sess.scalars(select(VerifierDriftPattern)))

    by_failure_category = {row.failure_category: row for row in rows}
    assert by_failure_category["missing_metrics"].uses == 1
    assert by_failure_category[GLOBAL_FAILURE_CATEGORY].uses == 1


def test_non_overruled_events_are_skipped() -> None:
    """An event without ``overruled=True`` has nothing for the feedback
    pipeline to show — it must not pollute the patterns."""
    Session = _session_factory()
    with Session() as sess:
        _add_event(
            sess,
            id_="evt-overruled",
            overruled=True,
            failure_categories=["missing_metrics"],
        )
        _add_event(
            sess,
            id_="evt-passed",
            overruled=False,
            check_name=None,
            failure_categories=["missing_metrics"],
            turn_idx=2,
        )
        sess.commit()

        refresh_verifier_drift_patterns(session=sess)
        rows = list(sess.scalars(select(VerifierDriftPattern)))

    by_failure_category = {row.failure_category: row for row in rows}
    assert by_failure_category["missing_metrics"].uses == 1
    assert by_failure_category[GLOBAL_FAILURE_CATEGORY].uses == 1


def test_refresh_is_idempotent_across_runs() -> None:
    Session = _session_factory()
    with Session() as sess:
        _add_event(sess, id_="evt-x", failure_categories=["missing_metrics"])
        sess.commit()

        refresh_verifier_drift_patterns(session=sess)
        first = list(sess.scalars(select(VerifierDriftPattern)))
        refresh_verifier_drift_patterns(session=sess)
        second = list(sess.scalars(select(VerifierDriftPattern)))

    assert {(row.id, row.uses) for row in first} == {
        (row.id, row.uses) for row in second
    }


def test_refresh_removes_stale_patterns_when_source_events_disappear() -> None:
    """Patterns whose source events are no longer in the window or
    were deleted are removed so the read model never shows ghost data."""
    Session = _session_factory()
    with Session() as sess:
        _add_event(
            sess,
            id_="evt-keep",
            failure_categories=["missing_metrics"],
        )
        _add_event(
            sess,
            id_="evt-ghost",
            failure_categories=["weak_debugging"],
            turn_idx=2,
            dimension="debugging",
            check_name="Triages a real incident",
        )
        sess.commit()

        refresh_verifier_drift_patterns(session=sess)
        rows_before = list(sess.scalars(select(VerifierDriftPattern)))
        assert {row.failure_category for row in rows_before} >= {
            "missing_metrics",
            "weak_debugging",
        }

        sess.execute(VerifierDriftEvent.__table__.delete().where(
            VerifierDriftEvent.id == "evt-ghost"
        ))
        sess.commit()

        result = refresh_verifier_drift_patterns(session=sess)
        rows_after = list(sess.scalars(select(VerifierDriftPattern)))

    failure_cats = {row.failure_category for row in rows_after}
    assert "weak_debugging" not in failure_cats
    assert "missing_metrics" in failure_cats
    assert result.deleted >= 1


def test_sample_evidence_and_reasons_bounded_to_five_each() -> None:
    Session = _session_factory()
    with Session() as sess:
        for i in range(7):
            _add_event(
                sess,
                id_=f"evt-many-{i}",
                failure_categories=["missing_metrics"],
                evidence=[f"quote-{i}"],
                reasons=[f"reason-{i}"],
                turn_idx=i,
            )
        sess.commit()

        refresh_verifier_drift_patterns(session=sess)
        rows = list(sess.scalars(select(VerifierDriftPattern)))

    by_failure_category = {row.failure_category: row for row in rows}
    bucket = by_failure_category["missing_metrics"]
    assert bucket.uses == 7
    assert len(bucket.sample_evidence) == 5
    assert len(bucket.reasons_sample) == 5
