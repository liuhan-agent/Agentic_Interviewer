"""Roll ``verifier_drift_events`` into the ``verifier_drift_patterns`` read model.

PR3 of the drift-feedback persistence track. The raw event log is
fine-grained (one row per overruled / abstained verification), but the
Generator and Evaluator feedback paths only need the aggregated picture:
"how often did this check fail on this dimension, broken down by
failure_category?"

This service builds that aggregation:

* Scans the last ``window_days`` days of :class:`VerifierDriftEvent`
  rows that ``overruled=True`` AND have a non-null
  ``overruled_check_name`` (we cannot say anything useful about a
  pattern without a check name).
* For each event, contributes to one row per ``failure_category``
  declared by the underlying evaluation, PLUS one row in the
  ``"__global__"`` rollup so a failure-category-free filter still
  surfaces the hottest checks.
* ``sample_evidence`` and ``reasons_sample`` are de-duplicated and
  capped at 5 entries each, matching the
  :class:`VerifierDriftMonitor.snapshot` semantics so renderers can be
  swapped between sources without diff.
* Idempotent: re-running with the same input produces the same row set;
  patterns whose source events all disappeared are deleted.
"""
from __future__ import annotations

import hashlib
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.verifier_drift import VerifierDriftEvent, VerifierDriftPattern

GLOBAL_FAILURE_CATEGORY = "__global__"
_MAX_SAMPLE_EVIDENCE = 5
_MAX_REASONS_SAMPLE = 5


@dataclass(frozen=True)
class DriftPatternRefreshResult:
    refreshed: int = 0
    deleted: int = 0


def refresh_verifier_drift_patterns(
    *,
    session: Session,
    window_days: int = 30,
) -> DriftPatternRefreshResult:
    """Aggregate recent drift events into the pattern read model.

    ``window_days`` defaults to 30 because that is the rollout default
    (see ``Settings.drift_pattern_aggregation_window_days``). Smaller
    windows make the aggregation more reactive to recent shifts but
    risk dropping signal during slow weeks; tune it via the setting
    rather than per-call so all callers stay in sync.
    """
    session.flush()
    cutoff = datetime.now(UTC) - timedelta(days=max(int(window_days), 1))

    events = list(
        session.scalars(
            select(VerifierDriftEvent)
            .where(VerifierDriftEvent.overruled.is_(True))
            .where(VerifierDriftEvent.overruled_check_name.isnot(None))
            .where(VerifierDriftEvent.created_at >= cutoff)
            .order_by(
                VerifierDriftEvent.created_at.asc(),
                VerifierDriftEvent.id.asc(),
            )
        )
    )

    buckets: dict[tuple[str, str, str], _Bucket] = defaultdict(_Bucket)

    for event in events:
        dimension = event.dimension
        check_name = event.overruled_check_name or "unknown"
        evidence = list(event.evaluator_evidence_quotes or [])
        reasons = list(event.verifier_reasons or [])
        created_at = event.created_at or datetime.now(UTC)

        per_category = [
            str(value)
            for value in (event.failure_categories or [])
            if isinstance(value, str) and value.strip()
        ]

        for failure_category in per_category:
            buckets[(dimension, check_name, failure_category)].add(
                evidence=evidence,
                reasons=reasons,
                created_at=created_at,
            )
        buckets[(dimension, check_name, GLOBAL_FAILURE_CATEGORY)].add(
            evidence=evidence,
            reasons=reasons,
            created_at=created_at,
        )

    seen_ids: set[str] = set()
    for (dimension, check_name, failure_category), bucket in buckets.items():
        pattern_id = _pattern_id(dimension, check_name, failure_category)
        seen_ids.add(pattern_id)
        row = session.get(VerifierDriftPattern, pattern_id)
        if row is None:
            row = VerifierDriftPattern(
                id=pattern_id,
                dimension=dimension,
                check_name=check_name,
                failure_category=failure_category,
            )
            session.add(row)
        row.uses = bucket.uses
        row.overruled_count = bucket.uses
        row.overrule_rate = 1.0
        row.sample_evidence = list(bucket.sample_evidence)
        row.reasons_sample = list(bucket.reasons_sample)
        row.first_seen_at = bucket.first_seen_at or datetime.now(UTC)
        row.last_seen_at = bucket.last_seen_at or datetime.now(UTC)
        row.updated_at = datetime.now(UTC)

    deleted = 0
    for stale in session.scalars(select(VerifierDriftPattern)):
        if stale.id not in seen_ids:
            session.delete(stale)
            deleted += 1

    if buckets or deleted:
        session.flush()

    return DriftPatternRefreshResult(refreshed=len(seen_ids), deleted=deleted)


@dataclass
class _Bucket:
    uses: int = 0
    sample_evidence: list[str] = None  # type: ignore[assignment]
    reasons_sample: list[str] = None  # type: ignore[assignment]
    first_seen_at: datetime | None = None
    last_seen_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.sample_evidence is None:
            self.sample_evidence = []
        if self.reasons_sample is None:
            self.reasons_sample = []

    def add(
        self,
        *,
        evidence: list[str],
        reasons: list[str],
        created_at: datetime,
    ) -> None:
        self.uses += 1
        if self.first_seen_at is None or created_at < self.first_seen_at:
            self.first_seen_at = created_at
        if self.last_seen_at is None or created_at > self.last_seen_at:
            self.last_seen_at = created_at

        for quote in evidence:
            if not quote:
                continue
            if quote in self.sample_evidence:
                continue
            if len(self.sample_evidence) >= _MAX_SAMPLE_EVIDENCE:
                continue
            self.sample_evidence.append(quote)

        for reason in reasons:
            if not reason:
                continue
            if reason in self.reasons_sample:
                continue
            if len(self.reasons_sample) >= _MAX_REASONS_SAMPLE:
                continue
            self.reasons_sample.append(reason)


def _pattern_id(dimension: str, check_name: str, failure_category: str) -> str:
    digest = hashlib.sha1(
        f"{dimension}|{check_name}|{failure_category}".encode("utf-8"),
        usedforsecurity=False,
    ).hexdigest()
    return f"drift-pattern:{digest[:32]}"
