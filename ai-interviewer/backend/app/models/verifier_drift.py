"""Verifier-drift persistence models.

PR1 of the drift-feedback persistence track. The in-process
:class:`~app.ml.drift.verifier_drift.VerifierDriftMonitor` is intentionally
a short-lived rolling window — it answers "what does the last 200
turns look like" but loses everything across process restarts and
cannot aggregate by ``failure_category``. These two tables back the
long-horizon path:

* :class:`VerifierDriftEvent` is the **raw event table**, one row per
  ``verification_node`` outcome that crossed the drift-record gate.
  PR2 dual-writes into it alongside ``monitor.record(...)``.
* :class:`VerifierDriftPattern` is the **aggregated read model** PR3
  refreshes from the raw events — bucketed by ``(dimension, check_name,
  failure_category)`` AND by ``(dimension, check_name, "__global__")``
  so the Generator / Evaluator feedback path can look up either layer
  without re-running the SQL aggregation.

Schema constraints
------------------
* The two JSON list columns on the event row (``evaluator_evidence_quotes``,
  ``verifier_reasons``) are already length-bounded upstream by
  ``app/ml/drift/prompt_feedback.py::_truncate``. We keep them as JSON
  for round-trip fidelity rather than re-truncating at the DB layer.
* ``failure_categories`` mirrors the JSON list shape that
  :class:`~app.models.strategy_memory.StrategySignal.failure_categories`
  already uses so the failure-taxonomy work from the previous PR set
  flows through unchanged.
* ``failure_category`` on the **pattern** row is a single string —
  events with N failure categories fan out into N pattern rows plus
  one ``"__global__"`` rollup row (PR3).
"""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class VerifierDriftEvent(Base):
    """One persisted ``DriftEvent`` from ``verification_node``."""

    __tablename__ = "verifier_drift_events"

    id: Mapped[str] = mapped_column(String(96), primary_key=True)

    session_id: Mapped[str] = mapped_column(String(64), index=True)
    trace_id: Mapped[str | None] = mapped_column(String(64), index=True)
    turn_idx: Mapped[int] = mapped_column(Integer)

    dimension: Mapped[str] = mapped_column(String(64), index=True)
    job_level: Mapped[str | None] = mapped_column(String(32), index=True)

    evaluator_passed: Mapped[bool] = mapped_column(Boolean, default=False)
    verifier_verdict: Mapped[str] = mapped_column(String(16))
    verifier_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    verifier_abstained: Mapped[bool] = mapped_column(Boolean, default=False)
    overruled: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    span_miss_count: Mapped[int] = mapped_column(Integer, default=0)
    span_total: Mapped[int] = mapped_column(Integer, default=0)

    overruled_check_name: Mapped[str | None] = mapped_column(
        String(160), index=True
    )
    evaluator_evidence_quotes: Mapped[list] = mapped_column(JSON, default=list)
    verifier_reasons: Mapped[list] = mapped_column(JSON, default=list)
    failure_categories: Mapped[list] = mapped_column(JSON, default=list)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        index=True,
    )


class VerifierDriftPattern(Base):
    """Aggregated drift health by ``(dimension, check, failure_category)``.

    PR3's refresh job upserts rows here so the Generator / Evaluator
    feedback path can render the top-N overruled patterns without
    scanning the raw event table on every turn.
    """

    __tablename__ = "verifier_drift_patterns"

    id: Mapped[str] = mapped_column(String(160), primary_key=True)
    dimension: Mapped[str] = mapped_column(String(64), index=True)
    check_name: Mapped[str] = mapped_column(String(160), index=True)
    failure_category: Mapped[str] = mapped_column(String(64), index=True)

    uses: Mapped[int] = mapped_column(Integer, default=0)
    overruled_count: Mapped[int] = mapped_column(Integer, default=0)
    overrule_rate: Mapped[float] = mapped_column(Float, default=0.0)

    sample_evidence: Mapped[list] = mapped_column(JSON, default=list)
    reasons_sample: Mapped[list] = mapped_column(JSON, default=list)

    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )
