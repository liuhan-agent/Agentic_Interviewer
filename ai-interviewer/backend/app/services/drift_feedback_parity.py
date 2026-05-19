"""Compare ``drift_feedback_source="monitor"`` and ``"db"`` outputs.

The ``db_shadow`` rollout in :mod:`app.ml.drift.prompt_feedback`
returns the monitor markdown unchanged while logging a per-call diff so
the prompt path stays byte-identical. That log is too low-signal for an
operator who needs to answer "is the persisted aggregation close enough
to the in-process window that I can flip ``drift_feedback_source`` to
``"db"`` without surprising the candidate?"

This service answers that question on demand. For each dimension it
asks both renderers for their would-be top-N pattern lists, projects
them down to ``(dimension, check)`` keys, and reports:

- ``intersection`` / ``monitor_only`` / ``db_only`` (sorted lists)
- ``jaccard_similarity`` = |∩| / |∪|; ``None`` when both sides are
  empty so the summary can distinguish "no data" from "total
  mismatch".

Three contracts make this safe to expose through admin:

1. **Best-effort.** Any DB failure (``SELECT DISTINCT dimension`` or
   per-dimension pattern read) degrades that dimension to a
   monitor-only view rather than 500-ing the whole call.
2. **Zero prompt-side effect.** This service never calls back into
   :func:`build_evaluator_drift_negatives` /
   :func:`build_generator_avoid_patterns`, so an admin poll cannot
   move the visible prompt.
3. **No new tables.** Reads only the existing ``verifier_drift_patterns``
   read model plus the in-process monitor snapshot. Adding a
   ``drift_feedback_shadow_diffs`` history table is deferred to the
   next round once we have enough live data to know what to retain.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from sqlalchemy import distinct, select

from app.core.logging import get_logger
from app.core.settings import get_settings
from app.ml.drift.prompt_feedback import (
    _load_db_patterns as load_db_patterns,
    _load_monitor_patterns as load_monitor_patterns,
    _pattern_keys as pattern_keys,
)
from app.ml.drift.verifier_drift import get_verifier_drift_monitor
from app.models import get_session
from app.models.verifier_drift import VerifierDriftPattern

log = get_logger(__name__)


@dataclass(frozen=True)
class DimensionParity:
    """One dimension's monitor-vs-DB comparison."""

    dimension: str
    monitor_count: int
    db_count: int
    intersection: list[tuple[str, str]] = field(default_factory=list)
    monitor_only: list[tuple[str, str]] = field(default_factory=list)
    db_only: list[tuple[str, str]] = field(default_factory=list)
    jaccard_similarity: float | None = None


@dataclass(frozen=True)
class DriftFeedbackParityResult:
    """Full payload returned to the admin endpoint."""

    top_n: int
    min_support: int
    feedback_source: str
    monitor_backend: str
    per_dimension: list[DimensionParity] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)

    def asdict(self) -> dict[str, Any]:
        payload = asdict(self)
        for dim in payload["per_dimension"]:
            for key in ("intersection", "monitor_only", "db_only"):
                dim[key] = [list(item) for item in dim[key]]
        return payload


def _db_distinct_dimensions() -> list[str]:
    """Return the set of dimensions present in ``verifier_drift_patterns``.

    Best-effort: a DB outage returns an empty list and the caller falls
    back to the monitor snapshot alone.
    """
    try:
        with get_session() as sess:
            rows = sess.scalars(
                select(distinct(VerifierDriftPattern.dimension))
            ).all()
    except Exception as e:  # pragma: no cover - admin path tolerates DB outage
        log.warning("drift parity db distinct query failed: %s", e)
        return []
    return [str(d) for d in rows if d]


def _monitor_snapshot_dimensions() -> list[str]:
    """Return the dimensions the in-process monitor has samples for."""
    try:
        snap = get_verifier_drift_monitor().snapshot()
    except Exception as e:  # pragma: no cover - monitor outage degrades gracefully
        log.warning("drift parity monitor snapshot failed: %s", e)
        return []
    per_dim = snap.get("per_dimension") or {}
    if isinstance(per_dim, dict):
        return [str(d) for d in per_dim.keys()]
    return []


def _resolve_dimensions(dimensions: list[str] | None) -> list[str]:
    if dimensions:
        return sorted({d for d in dimensions if d})
    union: set[str] = set()
    union.update(_monitor_snapshot_dimensions())
    union.update(_db_distinct_dimensions())
    return sorted(union)


def _safe_load_db_patterns(
    *, dimension: str, top_n: int, min_support: int
) -> list[dict[str, Any]]:
    """Read DB patterns for one dimension; never raise to the caller."""
    try:
        return load_db_patterns(
            dimension=dimension,
            top_n=top_n,
            min_support=min_support,
            failure_categories=None,
        )
    except Exception as e:  # pragma: no cover - parity is best-effort
        log.warning(
            "drift parity db pattern read failed for dim=%s: %s", dimension, e
        )
        return []


def _safe_load_monitor_patterns(
    *, dimension: str, top_n: int, min_support: int
) -> list[dict[str, Any]]:
    """Read monitor patterns for one dimension; never raise."""
    try:
        return load_monitor_patterns(
            dimension=dimension, top_n=top_n, min_support=min_support
        )
    except Exception as e:  # pragma: no cover - parity is best-effort
        log.warning(
            "drift parity monitor pattern read failed for dim=%s: %s",
            dimension,
            e,
        )
        return []


def _parity_for_dimension(
    dimension: str, *, top_n: int, min_support: int
) -> DimensionParity:
    monitor_patterns = _safe_load_monitor_patterns(
        dimension=dimension, top_n=top_n, min_support=min_support
    )
    db_patterns = _safe_load_db_patterns(
        dimension=dimension, top_n=top_n, min_support=min_support
    )

    monitor_keys = set(pattern_keys(monitor_patterns))
    db_keys = set(pattern_keys(db_patterns))
    union = monitor_keys | db_keys
    intersection = monitor_keys & db_keys

    if not union:
        jaccard: float | None = None
    else:
        jaccard = len(intersection) / len(union)

    return DimensionParity(
        dimension=dimension,
        monitor_count=len(monitor_keys),
        db_count=len(db_keys),
        intersection=sorted(intersection),
        monitor_only=sorted(monitor_keys - db_keys),
        db_only=sorted(db_keys - monitor_keys),
        jaccard_similarity=jaccard,
    )


def _summarise(
    per_dimension: list[DimensionParity],
) -> dict[str, Any]:
    jaccards = [
        d.jaccard_similarity
        for d in per_dimension
        if d.jaccard_similarity is not None
    ]
    if not jaccards:
        return {
            "dimensions_checked": len(per_dimension),
            "avg_jaccard": None,
            "min_jaccard": None,
            "max_jaccard": None,
        }
    return {
        "dimensions_checked": len(per_dimension),
        "avg_jaccard": sum(jaccards) / len(jaccards),
        "min_jaccard": min(jaccards),
        "max_jaccard": max(jaccards),
    }


def compute_drift_feedback_parity(
    *,
    dimensions: list[str] | None = None,
    top_n: int = 5,
    min_support: int = 2,
) -> DriftFeedbackParityResult:
    """Compare monitor vs DB read paths per dimension.

    Parameters mirror the production renderers so the parity report
    measures the *actual* output an operator would see if they flipped
    ``drift_feedback_source``:

    - ``dimensions``: ``None`` triggers auto-scan; an explicit list
      restricts the comparison and bypasses the ``SELECT DISTINCT``.
    - ``top_n`` / ``min_support``: forwarded to both renderers so
      thresholds match the live ``build_evaluator_drift_negatives`` /
      ``build_generator_avoid_patterns`` defaults.
    """
    settings = get_settings()
    feedback_source = str(
        getattr(settings, "drift_feedback_source", "monitor") or "monitor"
    )
    monitor_backend = str(
        getattr(settings, "verifier_drift_backend", "memory") or "memory"
    )

    resolved_dims = _resolve_dimensions(dimensions)
    per_dimension = [
        _parity_for_dimension(
            dim, top_n=max(int(top_n), 1), min_support=max(int(min_support), 1)
        )
        for dim in resolved_dims
    ]
    summary = _summarise(per_dimension)

    return DriftFeedbackParityResult(
        top_n=max(int(top_n), 1),
        min_support=max(int(min_support), 1),
        feedback_source=feedback_source,
        monitor_backend=monitor_backend,
        per_dimension=per_dimension,
        summary=summary,
    )
