"""Service-level tests for :mod:`app.services.drift_feedback_parity`.

The parity service answers a single operator question for the
``drift_feedback_source="db_shadow"`` rollout: how close do the monitor
and DB read paths agree on which ``(dimension, check)`` buckets are hot?
When agreement is consistently high across all live dimensions, the
operator can safely flip ``drift_feedback_source`` from ``"db_shadow"``
to ``"db"`` and let the persisted aggregation drive the actual prompt.

These tests pin the contract:

1. Two-sided empty input yields ``jaccard_similarity=None`` so the
   summary does not silently report ``0/0`` as ``0.0`` (which would be
   indistinguishable from total mismatch).
2. One-sided inputs (monitor-only / db-only) yield ``jaccard=0.0``
   without crashing.
3. Partial overlap respects exact ``|∩| / |∪|`` arithmetic.
4. Full overlap yields ``1.0``.
5. Explicit ``dimensions`` parameter restricts the comparison and skips
   the DB ``SELECT DISTINCT`` scan; auto-scan kicks in only when
   ``dimensions is None``.
6. Auto-scan unions ``monitor.snapshot()["per_dimension"].keys()`` with
   ``SELECT DISTINCT dimension FROM verifier_drift_patterns``.
7. A DB outage on the per-pattern read falls back to "monitor-only" for
   that dimension without 500-ing the whole call (best-effort contract).

Mock strategy (Q5=C from the plan): unit tests monkeypatch the parity
service's already-resolved helper attributes directly. The companion
admin tests use a real in-memory SQLite session through the FastAPI
``TestClient`` so the wiring layer gets a true integration signal.
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest


def _make_pattern(
    dimension: str,
    check: str,
    *,
    count: int = 3,
    sample_evidence: list[str] | None = None,
    reasons_sample: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "dimension": dimension,
        "check": check,
        "count": count,
        "sample_evidence": list(sample_evidence or [f"evidence for {check}"]),
        "reasons_sample": list(reasons_sample or [f"reason for {check}"]),
    }


def _install_helpers(
    monkeypatch,
    *,
    monitor_by_dim: dict[str, list[dict[str, Any]]],
    db_by_dim: dict[str, list[dict[str, Any]]] | None = None,
    db_distinct_dims: list[str] | None = None,
    db_raise: bool = False,
    monitor_snapshot_dims: list[str] | None = None,
    monitor_backend: str = "memory",
    feedback_source: str = "db_shadow",
) -> None:
    """Inject the three helpers + monitor snapshot + settings.

    The parity service imports these names at module level; replacing
    them via ``monkeypatch.setattr`` keeps the production module
    untouched between tests.
    """
    from app.services import drift_feedback_parity as mod

    def _load_monitor(*, dimension, top_n, min_support):
        rows = monitor_by_dim.get(dimension, [])
        return [r for r in rows if int(r.get("count", 0)) >= min_support][:top_n]

    def _load_db(*, dimension, top_n, min_support, failure_categories):
        if db_raise:
            raise RuntimeError("simulated DB outage")
        store = db_by_dim or {}
        rows = store.get(dimension, [])
        return [r for r in rows if int(r.get("count", 0)) >= min_support][:top_n]

    def _keys(patterns):
        return [
            (str(p.get("dimension", "unknown")), str(p.get("check", "unknown")))
            for p in patterns
        ]

    monkeypatch.setattr(mod, "load_monitor_patterns", _load_monitor)
    monkeypatch.setattr(mod, "load_db_patterns", _load_db)
    monkeypatch.setattr(mod, "pattern_keys", _keys)

    snap_dims = monitor_snapshot_dims if monitor_snapshot_dims is not None else list(
        monitor_by_dim.keys()
    )

    class _Monitor:
        def snapshot(self) -> dict[str, Any]:
            return {"per_dimension": {dim: {} for dim in snap_dims}}

    monkeypatch.setattr(mod, "get_verifier_drift_monitor", lambda: _Monitor())

    def _db_distinct():
        if db_raise and db_distinct_dims is None:
            raise RuntimeError("simulated DB outage")
        return list(db_distinct_dims or [])

    monkeypatch.setattr(mod, "_db_distinct_dimensions", _db_distinct)

    monkeypatch.setattr(
        mod,
        "get_settings",
        lambda: SimpleNamespace(
            drift_feedback_source=feedback_source,
            verifier_drift_backend=monitor_backend,
        ),
    )


def test_both_empty_returns_none_jaccard(monkeypatch) -> None:
    from app.services.drift_feedback_parity import compute_drift_feedback_parity

    _install_helpers(monkeypatch, monitor_by_dim={"system_design": []})

    result = compute_drift_feedback_parity(
        dimensions=["system_design"], top_n=5, min_support=2
    )

    assert len(result.per_dimension) == 1
    dim = result.per_dimension[0]
    assert dim.monitor_count == 0
    assert dim.db_count == 0
    assert dim.jaccard_similarity is None
    assert result.summary["dimensions_checked"] == 1
    assert result.summary["avg_jaccard"] is None
    assert result.summary["min_jaccard"] is None
    assert result.summary["max_jaccard"] is None
    assert result.feedback_source == "db_shadow"


def test_monitor_only_yields_zero_jaccard(monkeypatch) -> None:
    from app.services.drift_feedback_parity import compute_drift_feedback_parity

    _install_helpers(
        monkeypatch,
        monitor_by_dim={
            "system_design": [
                _make_pattern("system_design", "Mentions concrete failure modes"),
                _make_pattern("system_design", "Quantifies blast radius"),
                _make_pattern("system_design", "Picks consistency model"),
            ]
        },
        db_by_dim={"system_design": []},
    )

    result = compute_drift_feedback_parity(
        dimensions=["system_design"], top_n=5, min_support=2
    )

    dim = result.per_dimension[0]
    assert dim.monitor_count == 3
    assert dim.db_count == 0
    assert len(dim.monitor_only) == 3
    assert dim.db_only == []
    assert dim.intersection == []
    assert dim.jaccard_similarity == 0.0
    assert result.summary["avg_jaccard"] == 0.0


def test_db_only_yields_zero_jaccard(monkeypatch) -> None:
    from app.services.drift_feedback_parity import compute_drift_feedback_parity

    _install_helpers(
        monkeypatch,
        monitor_by_dim={"coding": []},
        db_by_dim={
            "coding": [
                _make_pattern("coding", "Names a tradeoff"),
                _make_pattern("coding", "Picks a data structure"),
            ]
        },
    )

    result = compute_drift_feedback_parity(
        dimensions=["coding"], top_n=5, min_support=2
    )

    dim = result.per_dimension[0]
    assert dim.monitor_count == 0
    assert dim.db_count == 2
    assert dim.monitor_only == []
    assert len(dim.db_only) == 2
    assert dim.jaccard_similarity == 0.0


def test_partial_overlap_jaccard_precision(monkeypatch) -> None:
    from app.services.drift_feedback_parity import compute_drift_feedback_parity

    monitor = [
        _make_pattern("system_design", "shared_a"),
        _make_pattern("system_design", "shared_b"),
        _make_pattern("system_design", "monitor_only_1"),
        _make_pattern("system_design", "monitor_only_2"),
    ]
    db = [
        _make_pattern("system_design", "shared_a"),
        _make_pattern("system_design", "shared_b"),
        _make_pattern("system_design", "db_only_1"),
        _make_pattern("system_design", "db_only_2"),
        _make_pattern("system_design", "db_only_3"),
    ]
    _install_helpers(
        monkeypatch,
        monitor_by_dim={"system_design": monitor},
        db_by_dim={"system_design": db},
    )

    result = compute_drift_feedback_parity(
        dimensions=["system_design"], top_n=10, min_support=2
    )

    dim = result.per_dimension[0]
    assert dim.monitor_count == 4
    assert dim.db_count == 5
    assert len(dim.intersection) == 2
    assert len(dim.monitor_only) == 2
    assert len(dim.db_only) == 3
    assert dim.jaccard_similarity == pytest.approx(2 / 7, abs=1e-9)


def test_full_overlap_returns_one(monkeypatch) -> None:
    from app.services.drift_feedback_parity import compute_drift_feedback_parity

    patterns = [
        _make_pattern("coding", "a"),
        _make_pattern("coding", "b"),
        _make_pattern("coding", "c"),
    ]
    _install_helpers(
        monkeypatch,
        monitor_by_dim={"coding": patterns},
        db_by_dim={"coding": list(patterns)},
    )

    result = compute_drift_feedback_parity(
        dimensions=["coding"], top_n=5, min_support=2
    )

    dim = result.per_dimension[0]
    assert dim.monitor_count == 3
    assert dim.db_count == 3
    assert len(dim.intersection) == 3
    assert dim.monitor_only == []
    assert dim.db_only == []
    assert dim.jaccard_similarity == 1.0
    assert result.summary["avg_jaccard"] == 1.0
    assert result.summary["min_jaccard"] == 1.0
    assert result.summary["max_jaccard"] == 1.0


def test_explicit_dimensions_filter_skips_auto_scan(monkeypatch) -> None:
    from app.services.drift_feedback_parity import compute_drift_feedback_parity

    _install_helpers(
        monkeypatch,
        monitor_by_dim={
            "system_design": [_make_pattern("system_design", "x")],
            "coding": [_make_pattern("coding", "y")],
            "behavioral": [_make_pattern("behavioral", "z")],
        },
        db_by_dim={
            "system_design": [_make_pattern("system_design", "x")],
            "coding": [],
            "behavioral": [],
        },
        db_distinct_dims=["should_not_appear"],
    )

    result = compute_drift_feedback_parity(
        dimensions=["system_design", "behavioral"], top_n=5, min_support=2
    )

    dims = [d.dimension for d in result.per_dimension]
    assert dims == ["behavioral", "system_design"]
    assert "should_not_appear" not in dims
    assert "coding" not in dims


def test_auto_scan_unions_monitor_and_db_dimensions(monkeypatch) -> None:
    from app.services.drift_feedback_parity import compute_drift_feedback_parity

    _install_helpers(
        monkeypatch,
        monitor_by_dim={
            "system_design": [_make_pattern("system_design", "a")],
            "coding": [_make_pattern("coding", "b")],
            "behavioral": [],
        },
        db_by_dim={
            "coding": [_make_pattern("coding", "b")],
            "behavioral": [_make_pattern("behavioral", "c")],
        },
        monitor_snapshot_dims=["system_design", "coding"],
        db_distinct_dims=["coding", "behavioral"],
    )

    result = compute_drift_feedback_parity(
        dimensions=None, top_n=5, min_support=2
    )

    dims = [d.dimension for d in result.per_dimension]
    assert dims == ["behavioral", "coding", "system_design"]
    assert result.summary["dimensions_checked"] == 3


def test_db_failure_falls_back_to_monitor_only(monkeypatch) -> None:
    from app.services.drift_feedback_parity import compute_drift_feedback_parity

    _install_helpers(
        monkeypatch,
        monitor_by_dim={
            "system_design": [
                _make_pattern("system_design", "x"),
                _make_pattern("system_design", "y"),
            ]
        },
        db_raise=True,
    )

    result = compute_drift_feedback_parity(
        dimensions=["system_design"], top_n=5, min_support=2
    )

    dim = result.per_dimension[0]
    assert dim.monitor_count == 2
    assert dim.db_count == 0
    assert len(dim.monitor_only) == 2
    assert dim.db_only == []
    assert dim.jaccard_similarity == 0.0
