"""Verifier drift monitor.

Tracks a rolling window of verifier invocations so operators can spot
evaluator drift (Verifier repeatedly overruling Evaluator, evidence
quote alignment failing, etc.) without wiring a full metrics backend.

Design constraints
------------------
- **Pure observation.** The monitor is called *after* the verifier's
  verdict is already folded into ``state.evaluation``; nothing here
  influences routing, rewards, or the generated question stream.
- **Opt-in.** Gated by
  :attr:`app.core.settings.Settings.enable_verifier_drift_monitor`.
  When off, ``verification_node`` never constructs events nor touches
  the monitor, keeping the hot path byte-identical to pre-rollout.
- **In-process rolling window.** Events live in a
  ``collections.deque`` with a fixed ``maxlen``. No DB writes, no
  cross-process aggregation (see ``docs/PLAN_VERIFIER_DRIFT.md §11``
  for the follow-ups that would require persistence / Redis).
- **Thread safety.** The same double-checked locking pattern as
  ``ThompsonBandit.get_bandit`` protects the singleton, and a
  per-instance lock guards the deque so the HTTP admin endpoint and
  the graph-thread can snapshot / record concurrently.

Typical usage
-------------
>>> from app.ml.drift.verifier_drift import (
...     DriftEvent, get_verifier_drift_monitor,
... )
>>> monitor = get_verifier_drift_monitor()
>>> monitor.record(DriftEvent(
...     dimension="system_design", job_level="senior",
...     evaluator_passed=True, verifier_verdict="partial",
...     verifier_confidence=0.7, verifier_abstained=False,
...     overruled=True, span_miss_count=1, span_total=4,
...     timestamp=datetime.now(timezone.utc),
... ))
>>> monitor.snapshot()
{'window_size': 200, 'samples': 1, ...}
"""
from __future__ import annotations

import json
import threading
from collections import deque
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from app.core.logging import get_logger
from app.core.metrics import (
    record_verifier_drift_event,
    record_verifier_drift_store_error,
)

log = get_logger(__name__)

VerifierVerdict = Literal["pass", "partial", "fail"]
DriftBackend = Literal["memory", "redis"]


@dataclass(frozen=True)
class DriftEvent:
    """One verifier invocation observation.

    Every field is a plain primitive or ISO-friendly ``datetime`` so
    the admin endpoint can ``json.dumps`` the snapshot without
    bespoke serialisers.

    Attributes
    ----------
    dimension, job_level
        Context keys — match the bandit's ``f"{job_level}:{dimension}"``
        convention so per-dimension drift can be cross-referenced with
        bandit posteriors.
    evaluator_passed
        What the Evaluator said before the Verifier looked at it.
    verifier_verdict
        What the Verifier concluded. ``"pass"`` means no challenge;
        ``"partial"`` / ``"fail"`` mean the Verifier disagreed with
        a passing call.
    verifier_confidence
        Verifier's self-rated confidence in its verdict; below
        ``MIN_OVERRIDE_CONFIDENCE`` in :mod:`engine.workflow.nodes.verification`
        leads to the abstain path.
    verifier_abstained
        True when the Verifier disagreed but its confidence was too
        low to overrule. Tracked separately from ``overruled`` because
        abstains signal Verifier *uncertainty* rather than Evaluator
        wrongness.
    overruled
        True when the Verifier's high-confidence disagreement actually
        forced a refine round (``evaluator.passed=True`` ->
        ``updated.passed=False``). This is the primary drift signal.
    span_miss_count, span_total
        Sum of ``evidence_spans[*].match == "none"`` and total span
        count across every acceptance check on this turn. Only
        meaningful when :attr:`Settings.evidence_span_alignment` is
        enabled upstream; pass ``0 / 0`` when spans are off and the
        ``span_miss_rate`` aggregation treats them as ``0/0 -> 0.0``.
    timestamp
        UTC timestamp at record time (recorded once per event, stable
        under snapshot replays).
    overruled_check_name
        When ``overruled`` is True, this is the name of the single
        acceptance_check the verifier most strongly disagreed with
        (heuristic: the "yes"-verdict check the evaluator backed with
        the most evidence quotes). ``None`` when ``overruled`` is
        False or the evaluation carried no acceptance_check_results.
        Consumed by the drift-feedback pipeline (``PLAN_DRIFT_FEEDBACK``)
        to cluster patterns per check.
    evaluator_evidence_quotes
        The evidence quotes the evaluator used for
        ``overruled_check_name``. Empty tuple when the check has no
        evidence or when ``overruled_check_name`` is None. Tuple (not
        list) so ``DriftEvent`` stays hashable / frozen-safe.
    verifier_reasons
        The verifier's ``reasons_to_doubt`` list (first 5 entries,
        stringified). Empty tuple when the verifier returned no
        reasons.
    """

    dimension: str
    job_level: str
    evaluator_passed: bool
    verifier_verdict: VerifierVerdict
    verifier_confidence: float
    verifier_abstained: bool
    overruled: bool
    span_miss_count: int
    span_total: int
    timestamp: datetime
    # PLAN_DRIFT_FEEDBACK additions. All fields carry defaults so
    # existing call-sites that construct ``DriftEvent`` with only the
    # original positional / keyword arguments stay source-compatible
    # (the pre-feedback ``_record_drift_event`` shape is valid).
    overruled_check_name: str | None = None
    evaluator_evidence_quotes: tuple[str, ...] = ()
    verifier_reasons: tuple[str, ...] = ()


class VerifierDriftMonitor:
    """Rolling-window aggregator over :class:`DriftEvent` observations.

    The monitor is intentionally minimal: events in, aggregates out,
    no persistence, no background jobs. Snapshot output is shaped so
    a Grafana (or equivalent) panel can key off stable JSON fields
    across releases.
    """

    def __init__(
        self,
        *,
        window_size: int = 200,
        backend: DriftBackend = "memory",
        redis_client: Any | None = None,
        redis_url: str | None = None,
        redis_prefix: str = "agentic_interviewer:verifier_drift",
    ) -> None:
        if window_size < 1:
            raise ValueError("window_size must be >= 1")
        if backend not in {"memory", "redis"}:
            raise ValueError("backend must be 'memory' or 'redis'")
        self._window_size = int(window_size)
        self._backend: DriftBackend = backend
        self._redis_client = redis_client
        self._redis_url = redis_url
        self._redis_prefix = redis_prefix.rstrip(":")
        self._events_by_dimension: dict[str, deque[DriftEvent]] = {}
        self._lock = threading.Lock()

    def record(self, event: DriftEvent) -> None:
        """Append an event to the window.

        The deque's ``maxlen`` handles truncation automatically, so
        the oldest event is discarded once ``window_size`` is full.
        Safe to call from any thread.
        """
        if self._backend == "redis":
            try:
                self._record_redis(event)
                _record_event_metric(event)
            except Exception as e:  # pragma: no cover - backend outage
                record_verifier_drift_store_error("redis")
                log.warning("verifier drift redis record failed: %s", e)
            return

        with self._lock:
            bucket = self._events_by_dimension.setdefault(
                event.dimension,
                deque(maxlen=self._window_size),
            )
            bucket.append(event)
        _record_event_metric(event)

    def reset(self) -> None:
        """Clear the window. Used by unit tests + operators who want
        to start a fresh observation batch without restarting the
        process.
        """
        if self._backend == "redis":
            try:
                redis_client = self._redis()
                dimensions = self._redis_dimensions(redis_client)
                keys = [self._dimension_key(d) for d in dimensions]
                keys.append(self._dimensions_key())
                if hasattr(redis_client, "delete"):
                    redis_client.delete(*keys)
            except Exception as e:  # pragma: no cover - operator helper
                record_verifier_drift_store_error("redis")
                log.warning("verifier drift redis reset failed: %s", e)
            return

        with self._lock:
            self._events_by_dimension.clear()

    def snapshot(self) -> dict[str, Any]:
        """Return aggregate metrics for the current window.

        Shape (stable across releases; additions are additive only):

        - ``window_size``, ``samples``
        - top-level counters: ``calls / overrides / abstains``
        - top-level rates: ``override_rate / abstain_rate / span_miss_rate``
        - ``per_dimension[<dim>]``: calls / overrides / abstains / rates
        - ``per_verdict``: ``{"pass": n, "partial": n, "fail": n}``
        - ``overruled_patterns`` (PLAN_DRIFT_FEEDBACK): list of
          ``{dimension, check, count, sample_evidence, reasons_sample}``
          aggregated over every event with ``overruled=True`` and a
          non-null ``overruled_check_name``. Sorted by ``count`` DESC,
          with ties broken lexicographically by ``(dimension, check)``
          so snapshots are deterministic. Evidence and reasons are
          de-duplicated (preserving first-seen order) and capped at
          5 entries each.

        Rates are floats in ``[0, 1]``; ``0.0`` when the denominator
        is zero (no samples / no spans yet).
        """
        if self._backend == "redis":
            try:
                events = self._read_redis_events()
            except Exception as e:
                record_verifier_drift_store_error("redis")
                log.warning("verifier drift redis snapshot failed: %s", e)
                return self._empty_snapshot(backend_unavailable=True)
            return self._snapshot_from_events(events, backend_unavailable=False)

        with self._lock:
            events = [
                event
                for bucket in self._events_by_dimension.values()
                for event in bucket
            ]
        return self._snapshot_from_events(events, backend_unavailable=False)

    def _empty_snapshot(self, *, backend_unavailable: bool) -> dict[str, Any]:
        return {
            "window_size": self._window_size,
            "samples": 0,
            "calls": 0,
            "overrides": 0,
            "abstains": 0,
            "override_rate": 0.0,
            "abstain_rate": 0.0,
            "span_miss_rate": 0.0,
            "per_dimension": {},
            "per_verdict": {"pass": 0, "partial": 0, "fail": 0},
            "overruled_patterns": [],
            "backend": self._backend,
            "backend_unavailable": backend_unavailable,
            "window_semantics": "per_dimension",
        }

    def _snapshot_from_events(
        self,
        events: list[DriftEvent],
        *,
        backend_unavailable: bool,
    ) -> dict[str, Any]:
        if not events:
            return self._empty_snapshot(backend_unavailable=backend_unavailable)

        total = len(events)
        overrides = sum(1 for e in events if e.overruled)
        abstains = sum(1 for e in events if e.verifier_abstained)
        span_miss_total = sum(e.span_miss_count for e in events)
        span_total_total = sum(e.span_total for e in events)

        per_dim: dict[str, dict[str, Any]] = {}
        per_verdict: dict[str, int] = {"pass": 0, "partial": 0, "fail": 0}

        # Accumulator for the overruled-pattern aggregation. Keyed on
        # (dimension, check_name) so the same evaluator mistake on the
        # same dimension rolls into one bucket across many turns.
        patterns: dict[tuple[str, str], dict[str, Any]] = {}

        for e in events:
            d = per_dim.setdefault(
                e.dimension,
                {
                    "calls": 0,
                    "overrides": 0,
                    "abstains": 0,
                    "span_miss": 0,
                    "span_total": 0,
                },
            )
            d["calls"] += 1
            d["overrides"] += int(e.overruled)
            d["abstains"] += int(e.verifier_abstained)
            d["span_miss"] += e.span_miss_count
            d["span_total"] += e.span_total
            # ``verifier_verdict`` is typed but arrives from an LLM, so
            # defend against an unexpected label here just like the
            # agent layer does.
            key = e.verifier_verdict if e.verifier_verdict in per_verdict else "fail"
            per_verdict[key] += 1

            # Aggregate overruled patterns. Events that did NOT
            # overrule (pure confirmation / abstain) and events that
            # overruled without capturing a check name are skipped;
            # the feedback pipeline has nothing to show for them.
            if e.overruled and e.overruled_check_name:
                pkey = (e.dimension, e.overruled_check_name)
                bucket = patterns.setdefault(
                    pkey,
                    {
                        "dimension": e.dimension,
                        "check": e.overruled_check_name,
                        "count": 0,
                        "sample_evidence": [],
                        "reasons_sample": [],
                    },
                )
                bucket["count"] += 1
                for quote in e.evaluator_evidence_quotes:
                    if quote and quote not in bucket["sample_evidence"]:
                        bucket["sample_evidence"].append(quote)
                for reason in e.verifier_reasons:
                    if reason and reason not in bucket["reasons_sample"]:
                        bucket["reasons_sample"].append(reason)

        # Cap each pattern's evidence / reasons lists at 5 to keep
        # the snapshot JSON bounded even when the window holds many
        # turns of the same mistake.
        for bucket in patterns.values():
            bucket["sample_evidence"] = bucket["sample_evidence"][:5]
            bucket["reasons_sample"] = bucket["reasons_sample"][:5]

        overruled_patterns = sorted(
            patterns.values(),
            key=lambda b: (-b["count"], b["dimension"], b["check"]),
        )

        for d in per_dim.values():
            calls = d["calls"]
            span_total = d["span_total"]
            d["override_rate"] = d["overrides"] / calls if calls else 0.0
            d["abstain_rate"] = d["abstains"] / calls if calls else 0.0
            d["span_miss_rate"] = (
                d["span_miss"] / span_total if span_total else 0.0
            )

        return {
            "window_size": self._window_size,
            "samples": total,
            "calls": total,
            "overrides": overrides,
            "abstains": abstains,
            "override_rate": overrides / total if total else 0.0,
            "abstain_rate": abstains / total if total else 0.0,
            "span_miss_rate": (
                span_miss_total / span_total_total if span_total_total else 0.0
            ),
            "per_dimension": per_dim,
            "per_verdict": per_verdict,
            "overruled_patterns": overruled_patterns,
            "backend": self._backend,
            "backend_unavailable": backend_unavailable,
            "window_semantics": "per_dimension",
        }

    def _redis(self) -> Any:
        if self._redis_client is not None:
            return self._redis_client
        from redis import Redis

        from app.core.settings import get_settings

        url = self._redis_url or get_settings().redis_url
        self._redis_client = Redis.from_url(url, decode_responses=True)
        return self._redis_client

    def _dimensions_key(self) -> str:
        return f"{self._redis_prefix}:dimensions"

    def _dimension_key(self, dimension: str) -> str:
        return f"{self._redis_prefix}:dim:{dimension}"

    def _redis_dimensions(self, redis_client: Any) -> list[str]:
        raw = redis_client.smembers(self._dimensions_key())
        out: list[str] = []
        for item in raw:
            if isinstance(item, bytes):
                item = item.decode("utf-8")
            out.append(str(item))
        return sorted(out)

    def _record_redis(self, event: DriftEvent) -> None:
        redis_client = self._redis()
        dimension = event.dimension
        redis_client.sadd(self._dimensions_key(), dimension)
        key = self._dimension_key(dimension)
        redis_client.lpush(key, _event_to_json(event))
        redis_client.ltrim(key, 0, self._window_size - 1)

    def _read_redis_events(self) -> list[DriftEvent]:
        redis_client = self._redis()
        events: list[DriftEvent] = []
        for dimension in self._redis_dimensions(redis_client):
            for raw in redis_client.lrange(self._dimension_key(dimension), 0, -1):
                events.append(_event_from_json(raw))
        return events


def _record_event_metric(event: DriftEvent) -> None:
    record_verifier_drift_event(
        dimension=event.dimension,
        verdict=event.verifier_verdict,
        overruled=event.overruled,
        abstained=event.verifier_abstained,
    )


def _event_to_json(event: DriftEvent) -> str:
    payload = asdict(event)
    payload["timestamp"] = event.timestamp.isoformat()
    payload["evaluator_evidence_quotes"] = list(event.evaluator_evidence_quotes)
    payload["verifier_reasons"] = list(event.verifier_reasons)
    return json.dumps(payload, ensure_ascii=False, default=str)


def _event_from_json(raw: str | bytes) -> DriftEvent:
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    payload = json.loads(raw)
    ts = datetime.fromisoformat(str(payload["timestamp"]))
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    verdict = str(payload.get("verifier_verdict") or "fail")
    if verdict not in {"pass", "partial", "fail"}:
        verdict = "fail"
    return DriftEvent(
        dimension=str(payload.get("dimension") or "unknown"),
        job_level=str(payload.get("job_level") or "mid"),
        evaluator_passed=bool(payload.get("evaluator_passed")),
        verifier_verdict=verdict,  # type: ignore[arg-type]
        verifier_confidence=float(payload.get("verifier_confidence") or 0.0),
        verifier_abstained=bool(payload.get("verifier_abstained")),
        overruled=bool(payload.get("overruled")),
        span_miss_count=int(payload.get("span_miss_count") or 0),
        span_total=int(payload.get("span_total") or 0),
        timestamp=ts,
        overruled_check_name=payload.get("overruled_check_name"),
        evaluator_evidence_quotes=tuple(payload.get("evaluator_evidence_quotes") or ()),
        verifier_reasons=tuple(payload.get("verifier_reasons") or ()),
    )


_singleton: VerifierDriftMonitor | None = None
_singleton_lock = threading.Lock()


def get_verifier_drift_monitor() -> VerifierDriftMonitor:
    """Return the process-wide monitor, constructing it lazily.

    Uses the double-checked-locking pattern (mirroring
    ``ThompsonBandit.get_bandit``) so the hot path stays lock-free
    once the singleton is up; concurrent construction attempts still
    converge on a single instance, preventing split-state between
    ``verification_node`` callers and the ``/admin/drift/verifier``
    HTTP thread.
    """
    global _singleton
    if _singleton is None:
        with _singleton_lock:
            if _singleton is None:
                from app.core.settings import get_settings

                settings = get_settings()
                _singleton = VerifierDriftMonitor(
                    window_size=getattr(settings, "verifier_drift_window_size", 200),
                    backend=getattr(settings, "verifier_drift_backend", "memory"),
                    redis_url=getattr(settings, "redis_url", None),
                    redis_prefix=getattr(
                        settings,
                        "verifier_drift_redis_prefix",
                        "agentic_interviewer:verifier_drift",
                    ),
                )
    return _singleton


def reset_verifier_drift_monitor_for_tests() -> None:
    """Drop the module-level singleton so the next access rebuilds it.

    Intended for unit tests only — production code should never call
    this because a mid-request reset would silently lose observations
    across the ``record -> snapshot`` hand-off.
    """
    global _singleton
    with _singleton_lock:
        _singleton = None
