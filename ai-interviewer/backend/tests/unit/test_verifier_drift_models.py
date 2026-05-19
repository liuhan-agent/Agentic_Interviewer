"""Tests for the persisted verifier-drift ORM models.

PR1 of the drift-feedback persistence track: stand up two new tables so
later PRs can dual-write events from ``verification_node``, aggregate
them by ``(dimension, check, failure_category)``, and surface them to
the Generator / Evaluator / admin readers.

What this file pins:

1. ``VerifierDriftEvent`` round-trips every primitive field, the three
   JSON list payloads (``failure_categories``,
   ``evaluator_evidence_quotes``, ``verifier_reasons``), and the
   ``created_at`` timestamp.
2. ``VerifierDriftPattern`` round-trips the two-level aggregation slots
   that PR3 will fill in: per-failure-category buckets AND the
   ``__global__`` rollup, including the bounded ``sample_evidence`` /
   ``reasons_sample`` lists.
"""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
from app.models.verifier_drift import VerifierDriftEvent, VerifierDriftPattern


def _session_factory():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)


def test_verifier_drift_event_round_trips_payload() -> None:
    Session = _session_factory()
    with Session() as sess:
        sess.add(
            VerifierDriftEvent(
                id="evt-sess1-2-system_design-architecture",
                session_id="sess-1",
                trace_id="trace-1",
                turn_idx=2,
                dimension="system_design",
                job_level="senior",
                evaluator_passed=True,
                verifier_verdict="partial",
                verifier_confidence=0.78,
                verifier_abstained=False,
                overruled=True,
                span_miss_count=1,
                span_total=3,
                overruled_check_name="Mentions concrete failure modes",
                evaluator_evidence_quotes=["we used Redis", "cache layer scales"],
                verifier_reasons=["evidence is generic boilerplate"],
                failure_categories=["missing_metrics", "unclear_architecture"],
            )
        )
        sess.commit()

        row = sess.scalar(select(VerifierDriftEvent))

    assert row is not None
    assert row.id == "evt-sess1-2-system_design-architecture"
    assert row.session_id == "sess-1"
    assert row.trace_id == "trace-1"
    assert row.turn_idx == 2
    assert row.dimension == "system_design"
    assert row.job_level == "senior"
    assert row.evaluator_passed is True
    assert row.verifier_verdict == "partial"
    assert row.verifier_confidence == 0.78
    assert row.verifier_abstained is False
    assert row.overruled is True
    assert row.span_miss_count == 1
    assert row.span_total == 3
    assert row.overruled_check_name == "Mentions concrete failure modes"
    assert row.evaluator_evidence_quotes == [
        "we used Redis",
        "cache layer scales",
    ]
    assert row.verifier_reasons == ["evidence is generic boilerplate"]
    assert row.failure_categories == ["missing_metrics", "unclear_architecture"]
    assert isinstance(row.created_at, datetime)


def test_verifier_drift_event_defaults_collapse_to_empty_lists() -> None:
    """Optional JSON list payloads default to ``[]`` so consumers can
    blindly iterate. Mirrors the defensive shape used by
    ``StrategySignal.failure_categories``."""
    Session = _session_factory()
    with Session() as sess:
        sess.add(
            VerifierDriftEvent(
                id="evt-minimal",
                session_id="sess-2",
                trace_id=None,
                turn_idx=0,
                dimension="communication",
                job_level="mid",
                evaluator_passed=False,
                verifier_verdict="pass",
                verifier_confidence=0.5,
                verifier_abstained=True,
                overruled=False,
                span_miss_count=0,
                span_total=0,
            )
        )
        sess.commit()

        row = sess.scalar(select(VerifierDriftEvent))

    assert row is not None
    assert row.evaluator_evidence_quotes == []
    assert row.verifier_reasons == []
    assert row.failure_categories == []
    assert row.overruled_check_name is None
    assert row.trace_id is None


def test_verifier_drift_pattern_round_trips_two_layer_aggregation() -> None:
    """PR3 will roll events into both a per-failure-category bucket and
    a ``__global__`` rollup; the schema must already accept both shapes
    in P0 so PR3 can implement without revisiting the model."""
    Session = _session_factory()
    now = datetime.now(UTC)
    with Session() as sess:
        sess.add(
            VerifierDriftPattern(
                id="pat-sd-arch-missing_metrics",
                dimension="system_design",
                check_name="Mentions concrete failure modes",
                failure_category="missing_metrics",
                uses=12,
                overruled_count=9,
                overrule_rate=0.75,
                sample_evidence=[
                    "we used Redis",
                    "cache layer scales",
                    "Kafka handled it",
                ],
                reasons_sample=[
                    "evidence is generic boilerplate",
                    "no quantified scale argument",
                ],
                first_seen_at=now,
                last_seen_at=now,
            )
        )
        sess.add(
            VerifierDriftPattern(
                id="pat-sd-arch-__global__",
                dimension="system_design",
                check_name="Mentions concrete failure modes",
                failure_category="__global__",
                uses=20,
                overruled_count=14,
                overrule_rate=0.7,
                sample_evidence=["we used Redis"],
                reasons_sample=["evidence is generic boilerplate"],
                first_seen_at=now,
                last_seen_at=now,
            )
        )
        sess.commit()

        rows = list(
            sess.scalars(
                select(VerifierDriftPattern).order_by(VerifierDriftPattern.id)
            )
        )

    assert len(rows) == 2
    by_category = {row.failure_category: row for row in rows}
    bucket = by_category["missing_metrics"]
    assert bucket.dimension == "system_design"
    assert bucket.check_name == "Mentions concrete failure modes"
    assert bucket.uses == 12
    assert bucket.overruled_count == 9
    assert bucket.overrule_rate == 0.75
    assert bucket.sample_evidence == [
        "we used Redis",
        "cache layer scales",
        "Kafka handled it",
    ]
    assert bucket.reasons_sample == [
        "evidence is generic boilerplate",
        "no quantified scale argument",
    ]

    global_row = by_category["__global__"]
    assert global_row.uses == 20
    assert global_row.overruled_count == 14
    assert global_row.overrule_rate == 0.7


def test_verifier_drift_pattern_defaults_empty_lists() -> None:
    Session = _session_factory()
    now = datetime.now(UTC)
    with Session() as sess:
        sess.add(
            VerifierDriftPattern(
                id="pat-empty",
                dimension="product_sense",
                check_name="Quantifies trade-offs",
                failure_category="__global__",
                uses=0,
                overruled_count=0,
                overrule_rate=0.0,
                first_seen_at=now,
                last_seen_at=now,
            )
        )
        sess.commit()

        row = sess.scalar(select(VerifierDriftPattern))

    assert row is not None
    assert row.sample_evidence == []
    assert row.reasons_sample == []
