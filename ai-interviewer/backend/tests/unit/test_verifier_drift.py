"""Tests for the verifier drift monitor (``PLAN_VERIFIER_DRIFT.md``).

Covers three layers:

1. ``VerifierDriftMonitor`` unit behaviour — rolling window, locks,
   aggregation math.
2. ``verification_node`` integration — the monitor is opt-in and
   must stay completely silent when
   ``enable_verifier_drift_monitor`` is OFF.
3. The ``_count_span_misses`` helper — bridges evidence-span shape
   (L2) into the drift metric (L1).

The admin endpoint is covered by a smoke test that hits FastAPI
with a TestClient — we want to catch routing / serialisation
regressions, not just the underlying aggregator.
"""
from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.ml.drift.verifier_drift import (
    DriftEvent,
    VerifierDriftMonitor,
    get_verifier_drift_monitor,
    reset_verifier_drift_monitor_for_tests,
)


@pytest.fixture(autouse=True)
def _reset_singleton() -> None:
    """Every test starts with a fresh monitor; the process-wide
    singleton must not leak state across ordered test runs.
    """
    reset_verifier_drift_monitor_for_tests()
    yield
    reset_verifier_drift_monitor_for_tests()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_event(
    *,
    dimension: str = "system_design",
    overruled: bool = False,
    verifier_verdict: str = "pass",
    verifier_abstained: bool = False,
    span_miss_count: int = 0,
    span_total: int = 0,
    evaluator_passed: bool = True,
) -> DriftEvent:
    return DriftEvent(
        dimension=dimension,
        job_level="mid",
        evaluator_passed=evaluator_passed,
        verifier_verdict=verifier_verdict,  # type: ignore[arg-type]
        verifier_confidence=0.8,
        verifier_abstained=verifier_abstained,
        overruled=overruled,
        span_miss_count=span_miss_count,
        span_total=span_total,
        timestamp=datetime.now(UTC),
    )


# ---------------------------------------------------------------------------
# VerifierDriftMonitor — unit layer
# ---------------------------------------------------------------------------


def test_monitor_starts_empty() -> None:
    monitor = VerifierDriftMonitor(window_size=10)

    snap = monitor.snapshot()

    assert snap["samples"] == 0
    assert snap["calls"] == 0
    assert snap["overrides"] == 0
    assert snap["override_rate"] == 0.0
    assert snap["span_miss_rate"] == 0.0
    assert snap["per_dimension"] == {}
    assert snap["per_verdict"] == {"pass": 0, "partial": 0, "fail": 0}
    assert snap["window_size"] == 10


def test_monitor_rejects_invalid_window_size() -> None:
    """A zero / negative window is almost certainly a misconfiguration
    (e.g. operator flips the setting and forgets the unit). Fail loud
    rather than silently degrade to "record nothing, snapshot zeros"
    which looks indistinguishable from a healthy system with no
    traffic.
    """
    with pytest.raises(ValueError):
        VerifierDriftMonitor(window_size=0)
    with pytest.raises(ValueError):
        VerifierDriftMonitor(window_size=-5)


def test_record_single_event_populates_per_dim() -> None:
    monitor = VerifierDriftMonitor(window_size=10)

    monitor.record(_make_event(dimension="system_design", overruled=True))

    snap = monitor.snapshot()
    assert snap["samples"] == 1
    assert snap["overrides"] == 1
    assert snap["override_rate"] == 1.0
    assert snap["per_dimension"]["system_design"]["calls"] == 1
    assert snap["per_dimension"]["system_design"]["overrides"] == 1
    assert snap["per_dimension"]["system_design"]["override_rate"] == 1.0


def test_override_rate_aggregates_across_mixed_events() -> None:
    """Classic rate-of-override check: 3 overrides out of 10
    verifier calls should yield a top-level override_rate of 0.3.
    """
    monitor = VerifierDriftMonitor(window_size=20)

    for _ in range(7):
        monitor.record(_make_event(overruled=False, verifier_verdict="pass"))
    for _ in range(3):
        monitor.record(
            _make_event(overruled=True, verifier_verdict="partial")
        )

    snap = monitor.snapshot()

    assert snap["calls"] == 10
    assert snap["overrides"] == 3
    assert snap["override_rate"] == pytest.approx(0.3)
    assert snap["per_verdict"] == {"pass": 7, "partial": 3, "fail": 0}


def test_span_miss_rate_uses_global_totals_not_per_event() -> None:
    """``span_miss_rate`` is (Σ miss) / (Σ total) across the window,
    NOT the average of per-event rates. This avoids the classic
    Simpson's-paradox trap where one event with 1/1 miss swings the
    mean far more than its share of the evidence.
    """
    monitor = VerifierDriftMonitor(window_size=10)

    monitor.record(_make_event(span_miss_count=1, span_total=2))
    monitor.record(_make_event(span_miss_count=0, span_total=4))
    monitor.record(_make_event(span_miss_count=3, span_total=6))

    snap = monitor.snapshot()
    # total = 2 + 4 + 6 = 12; miss = 1 + 0 + 3 = 4; 4 / 12 ~ 0.333
    assert snap["span_miss_rate"] == pytest.approx(4 / 12)


def test_window_truncates_oldest_events() -> None:
    """``deque(maxlen=N)`` should drop old events once the window is
    full; snapshot must reflect only the most recent N.
    """
    monitor = VerifierDriftMonitor(window_size=3)

    # Oldest 2 overruled; after window rollover they should vanish.
    monitor.record(_make_event(overruled=True))
    monitor.record(_make_event(overruled=True))
    # Push 3 clean passes; total window now = 3 passes, 0 overrides.
    monitor.record(_make_event(overruled=False))
    monitor.record(_make_event(overruled=False))
    monitor.record(_make_event(overruled=False))

    snap = monitor.snapshot()
    assert snap["samples"] == 3
    assert snap["overrides"] == 0
    assert snap["override_rate"] == 0.0


def test_window_truncates_per_dimension_not_globally() -> None:
    """A hot dimension must not evict a low-traffic dimension's window."""
    monitor = VerifierDriftMonitor(window_size=3)

    monitor.record(_make_event(dimension="system_design", overruled=True))
    for _ in range(5):
        monitor.record(_make_event(dimension="api_design", overruled=False))

    snap = monitor.snapshot()
    assert snap["window_semantics"] == "per_dimension"
    assert snap["samples"] == 4
    assert snap["per_dimension"]["system_design"]["calls"] == 1
    assert snap["per_dimension"]["system_design"]["override_rate"] == 1.0
    assert snap["per_dimension"]["api_design"]["calls"] == 3


def test_abstain_rate_tracks_abstains_independently_of_overrides() -> None:
    monitor = VerifierDriftMonitor(window_size=10)

    monitor.record(_make_event(verifier_abstained=True, overruled=False))
    monitor.record(_make_event(verifier_abstained=True, overruled=False))
    monitor.record(_make_event(overruled=True))
    monitor.record(_make_event())

    snap = monitor.snapshot()
    assert snap["abstains"] == 2
    assert snap["abstain_rate"] == pytest.approx(0.5)
    assert snap["overrides"] == 1
    assert snap["override_rate"] == pytest.approx(0.25)


def test_per_dimension_rates_computed_independently() -> None:
    monitor = VerifierDriftMonitor(window_size=20)

    # 2/2 override in system_design, 0/3 override in behavioural.
    for _ in range(2):
        monitor.record(
            _make_event(dimension="system_design", overruled=True)
        )
    for _ in range(3):
        monitor.record(
            _make_event(dimension="behavioural", overruled=False)
        )

    snap = monitor.snapshot()
    sys = snap["per_dimension"]["system_design"]
    beh = snap["per_dimension"]["behavioural"]
    assert sys["override_rate"] == 1.0
    assert beh["override_rate"] == 0.0


def test_reset_clears_window() -> None:
    monitor = VerifierDriftMonitor(window_size=10)
    monitor.record(_make_event())
    monitor.record(_make_event())
    assert monitor.snapshot()["samples"] == 2

    monitor.reset()

    assert monitor.snapshot()["samples"] == 0


def test_unknown_verdict_collapses_to_fail() -> None:
    """Defensive path: if upstream wiring ever produces an unexpected
    verdict label (e.g. LLM returned "maybe"), the aggregation must
    not KeyError mid-snapshot. Fall back to "fail" so the operator
    still sees something in the panel.
    """
    monitor = VerifierDriftMonitor(window_size=10)
    bad = DriftEvent(
        dimension="x",
        job_level="mid",
        evaluator_passed=True,
        verifier_verdict="maybe",  # type: ignore[arg-type]
        verifier_confidence=0.5,
        verifier_abstained=False,
        overruled=False,
        span_miss_count=0,
        span_total=0,
        timestamp=datetime.now(UTC),
    )

    monitor.record(bad)
    snap = monitor.snapshot()

    assert snap["per_verdict"]["fail"] == 1


class _FakeRedis:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.sets: dict[str, set[str]] = {}
        self.lists: dict[str, list[str]] = {}

    def _maybe_fail(self) -> None:
        if self.fail:
            raise RuntimeError("redis down")

    def sadd(self, key: str, value: str) -> None:
        self._maybe_fail()
        self.sets.setdefault(key, set()).add(value)

    def smembers(self, key: str) -> set[str]:
        self._maybe_fail()
        return set(self.sets.get(key, set()))

    def lpush(self, key: str, value: str) -> None:
        self._maybe_fail()
        self.lists.setdefault(key, []).insert(0, value)

    def ltrim(self, key: str, start: int, end: int) -> None:
        self._maybe_fail()
        self.lists[key] = self.lists.get(key, [])[start : end + 1]

    def lrange(self, key: str, start: int, end: int) -> list[str]:
        self._maybe_fail()
        values = self.lists.get(key, [])
        stop = None if end == -1 else end + 1
        return values[start:stop]


def test_redis_backend_aggregates_per_dimension_window() -> None:
    fake = _FakeRedis()
    monitor = VerifierDriftMonitor(
        window_size=2,
        backend="redis",
        redis_client=fake,
        redis_prefix="test-drift",
    )

    monitor.record(_make_event(dimension="system_design", overruled=True))
    for _ in range(3):
        monitor.record(_make_event(dimension="api_design", overruled=False))

    snap = monitor.snapshot()
    assert snap["backend"] == "redis"
    assert snap["backend_unavailable"] is False
    assert snap["window_semantics"] == "per_dimension"
    assert snap["samples"] == 3
    assert snap["per_dimension"]["system_design"]["calls"] == 1
    assert snap["per_dimension"]["api_design"]["calls"] == 2


def test_redis_backend_unavailable_returns_empty_snapshot() -> None:
    monitor = VerifierDriftMonitor(
        window_size=2,
        backend="redis",
        redis_client=_FakeRedis(fail=True),
        redis_prefix="test-drift",
    )

    monitor.record(_make_event(dimension="system_design", overruled=True))
    snap = monitor.snapshot()

    assert snap["backend"] == "redis"
    assert snap["backend_unavailable"] is True
    assert snap["samples"] == 0


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------


def test_get_verifier_drift_monitor_is_singleton(monkeypatch) -> None:
    """Two lookups should return the same instance so ``record`` from
    the graph thread and ``snapshot`` from the admin HTTP thread
    operate on a shared deque.
    """
    # ``verifier_drift`` imports ``get_settings`` lazily *inside* the
    # function (mirrors ``thompson.get_bandit`` to sidestep circular
    # imports at boot), so we patch the symbol at its source module
    # rather than on ``vd_mod`` itself.
    from app.core import settings as settings_mod

    monkeypatch.setattr(
        settings_mod,
        "get_settings",
        lambda: SimpleNamespace(verifier_drift_window_size=50),
    )

    a = get_verifier_drift_monitor()
    b = get_verifier_drift_monitor()

    assert a is b
    assert a.snapshot()["window_size"] == 50


# ---------------------------------------------------------------------------
# verification_node integration
# ---------------------------------------------------------------------------


def _mk_state(*, acceptance: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "current_question": {"question": "q", "dimension": "system_design"},
        "current_dimension": "system_design",
        "current_answer": "candidate answer",
        "current_answer_raw": "candidate answer",
        "current_contract": {
            "must_cover": ["x"],
            "acceptance_checks": ["Names X."],
            "bar_level": "deep_probe",  # force verifier to trigger
        },
        "job_spec": {"level": "mid"},
        "quality_threshold": 7.5,
        "evaluation": {
            "score": 8.0,
            "passed": True,
            "strengths": [],
            "weaknesses": [],
            "rubric_coverage": {"x": "covered"},
            "acceptance_check_results": acceptance or {},
            "recommended_next": "advance",
            "recommended_next_plan": "adaptive",
            "rationale": "ok",
        },
    }


def _stub_settings(*, drift_enabled: bool) -> SimpleNamespace:
    """Return a settings stub that the verification node can read.

    Only populates the fields verification_node actually touches so
    unrelated settings drift (new knobs in other PRs) can't break
    these tests unexpectedly.
    """
    return SimpleNamespace(
        enable_verifier_drift_monitor=drift_enabled,
        verifier_margin=1.0,
        verifier_senior_always=True,
        verifier_dimensions_bluff_prone=[],
        verifier_drift_window_size=200,
    )


def test_verification_node_records_drift_event_when_enabled(monkeypatch) -> None:
    """When the knob is ON and the verifier actually fired (passed is
    True + deep_probe contract), we should see exactly one event in
    the monitor after the node returns.
    """
    from app.engine.workflow.nodes import verification as vnode_mod

    # Stub verify_answer to avoid a real LLM call; return a high-conf
    # partial so _apply_verification downgrades -> overruled=True.
    def fake_verify_answer(**_: Any) -> dict[str, Any]:
        return {
            "verdict": "partial",
            "reasons_to_doubt": ["weak evidence"],
            "would_ask_next": "",
            "confidence": 0.8,
            "rationale": "shaky",
            "verifier_available": True,
        }

    monkeypatch.setattr(vnode_mod, "verify_answer", fake_verify_answer)
    monkeypatch.setattr(
        vnode_mod, "get_settings", lambda: _stub_settings(drift_enabled=True)
    )
    # The inner agent module also reads settings (for
    # ``verifier_margin`` etc). Keep its view consistent with the
    # outer stub so ``should_trigger`` math is deterministic.
    from app.engine.agents import verification as vagents_mod

    monkeypatch.setattr(
        vagents_mod, "get_settings", lambda: _stub_settings(drift_enabled=True)
    )

    state = _mk_state(
        acceptance={
            "Names X.": {
                "verdict": "yes",
                "evidence": ["hot reads in Redis"],
                "evidence_spans": [
                    {"text": "hot reads in Redis", "start": 10, "end": 28, "match": "exact"}
                ],
            },
            "Names Y.": {
                "verdict": "partial",
                "evidence": ["unrelated"],
                "evidence_spans": [
                    {"text": "unrelated", "start": -1, "end": -1, "match": "none"}
                ],
            },
        }
    )

    out = vnode_mod.verification_node(state)  # type: ignore[arg-type]

    snap = get_verifier_drift_monitor().snapshot()
    assert snap["samples"] == 1
    assert snap["overrides"] == 1  # high-confidence partial -> refine forced
    assert snap["override_rate"] == 1.0
    assert snap["span_miss_rate"] == pytest.approx(0.5)  # 1 none / 2 spans
    assert snap["per_dimension"]["system_design"]["calls"] == 1
    # Node itself still returns the verdict payload unchanged.
    assert out["evaluation"]["passed"] is False


def test_verification_node_silent_when_disabled(monkeypatch) -> None:
    """Default settings (knob OFF): monitor must see ZERO events even
    after a full verifier roundtrip.
    """
    from app.engine.workflow.nodes import verification as vnode_mod

    def fake_verify_answer(**_: Any) -> dict[str, Any]:
        return {
            "verdict": "pass",
            "reasons_to_doubt": [],
            "would_ask_next": "",
            "confidence": 0.9,
            "rationale": "solid",
            "verifier_available": True,
        }

    monkeypatch.setattr(vnode_mod, "verify_answer", fake_verify_answer)
    monkeypatch.setattr(
        vnode_mod, "get_settings", lambda: _stub_settings(drift_enabled=False)
    )
    from app.engine.agents import verification as vagents_mod

    monkeypatch.setattr(
        vagents_mod, "get_settings", lambda: _stub_settings(drift_enabled=False)
    )

    vnode_mod.verification_node(_mk_state())  # type: ignore[arg-type]

    assert get_verifier_drift_monitor().snapshot()["samples"] == 0


# ---------------------------------------------------------------------------
# _count_span_misses — shape bridge between L2 and L1
# ---------------------------------------------------------------------------


def test_count_span_misses_pure_new_shape() -> None:
    from app.engine.workflow.nodes.verification import _count_span_misses

    evaluation = {
        "acceptance_check_results": {
            "c1": {
                "verdict": "yes",
                "evidence_spans": [
                    {"match": "exact"},
                    {"match": "none"},
                ],
            },
            "c2": {
                "verdict": "yes",
                "evidence_spans": [{"match": "fuzzy"}],
            },
        }
    }

    miss, total = _count_span_misses(evaluation)

    assert (miss, total) == (1, 3)


def test_count_span_misses_degrades_safely_on_legacy_shape() -> None:
    """Without the evidence-span upgrade, ``acceptance_check_results``
    has no ``evidence_spans`` key — the counter must return (0, 0)
    rather than raise, because L1 has to keep working while the
    operator has L2's knob OFF.
    """
    from app.engine.workflow.nodes.verification import _count_span_misses

    evaluation = {
        "acceptance_check_results": {
            "c1": "yes",  # legacy flat string
            "c2": {"verdict": "partial", "evidence": ["quote"]},  # dict but no spans
        }
    }

    miss, total = _count_span_misses(evaluation)

    assert (miss, total) == (0, 0)


def test_count_span_misses_tolerates_malformed_spans() -> None:
    """Non-list / non-dict span payloads must be ignored, not crash.
    The drift monitor observability chain has to be *more* robust
    than the main path, not less — if the shape ever drifts we want
    the snapshot to keep serving old data.
    """
    from app.engine.workflow.nodes.verification import _count_span_misses

    evaluation = {
        "acceptance_check_results": {
            "c1": {"evidence_spans": "not a list"},
            "c2": {"evidence_spans": [None, 42, {"match": "none"}]},
            "c3": "legacy string",
            "c4": 42,
        }
    }

    miss, total = _count_span_misses(evaluation)
    # Only the well-formed span in c2 counts.
    assert (miss, total) == (1, 1)


# ---------------------------------------------------------------------------
# Admin endpoint smoke test
# ---------------------------------------------------------------------------


def test_admin_drift_endpoint_returns_snapshot(monkeypatch) -> None:
    """Hit the router through FastAPI TestClient to make sure route +
    dependency wiring are correct (regressions here are invisible to
    unit tests on ``VerifierDriftMonitor`` itself).
    """
    # Seed the monitor with one event so the snapshot isn't trivially empty.
    reset_verifier_drift_monitor_for_tests()
    from app.core import settings as settings_mod

    monkeypatch.setattr(
        settings_mod,
        "get_settings",
        lambda: SimpleNamespace(verifier_drift_window_size=5),
    )
    get_verifier_drift_monitor().record(_make_event(overruled=True))

    # Build a minimal FastAPI app that just mounts the admin router;
    # avoids spinning up DB / startup hooks from ``create_app``.
    from fastapi import FastAPI

    from app.api.v1 import admin as admin_api

    # Stub the admin module's settings accessor so ``enabled`` is True
    # in the response (its value is the only thing the endpoint adds
    # on top of the raw snapshot).
    with patch.object(
        admin_api,
        "get_settings",
        return_value=SimpleNamespace(
            api_token=None,
            allow_open_admin=True,
            enable_verifier_drift_monitor=True,
        ),
    ):
        app = FastAPI()
        app.include_router(admin_api.router)
        client = TestClient(app)

        response = client.get("/admin/drift/verifier")

    assert response.status_code == 200
    payload = response.json()
    assert payload["samples"] == 1
    assert payload["overrides"] == 1
    assert payload["enabled"] is True
