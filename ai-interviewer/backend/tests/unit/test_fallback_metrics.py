"""Unit tests for the question/evaluator fallback metrics + admin endpoint.

The metrics module is the single source of truth for
``question_fallbacks_total``: every fallback call site
(``ask_question_node`` / ``evaluator_node``) goes through
``record_question_fallback`` and the admin endpoint reads back
``question_fallbacks_snapshot`` verbatim.

What we cover here:

1. ``record_question_fallback`` is silent for unknown kinds and
   resilient to None / empty inputs (interview hot-path safety).
2. ``question_fallbacks_snapshot`` always emits a row for every
   ``QUESTION_FALLBACK_KINDS`` entry — even zero-count ones — so
   the admin dashboard can render a stable layout.
3. ``GET /admin/fallback-rates`` returns the snapshot in a
   ``{"fallback_counts": {...}}`` envelope, behind the same
   ``require_admin_token`` gate as every other ``/admin/*`` route.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1 import admin as admin_api
from app.core import metrics, settings as settings_mod


@pytest.fixture(autouse=True)
def _reset_fallback_counters():
    metrics.reset_question_fallback_metrics_for_tests()
    yield
    metrics.reset_question_fallback_metrics_for_tests()


def test_snapshot_zero_baseline_has_all_known_kinds():
    """Every known kind must appear with 0 even when nothing fired."""
    snap = metrics.question_fallbacks_snapshot()
    for kind in metrics.QUESTION_FALLBACK_KINDS:
        assert snap[kind] == 0, f"missing zero baseline for {kind!r}"


def test_record_increments_per_kind_independently():
    metrics.record_question_fallback("language")
    metrics.record_question_fallback("language")
    metrics.record_question_fallback("safety")
    metrics.record_question_fallback("evaluator_fallback")

    snap = metrics.question_fallbacks_snapshot()
    assert snap["language"] == 2
    assert snap["safety"] == 1
    assert snap["evaluator_fallback"] == 1
    assert snap["duplicate"] == 0
    assert snap["contract_unsigned"] == 0


def test_unknown_kind_is_still_recorded():
    """Unknown kinds (typos, future labels) accumulate under raw label.

    They are visible in the snapshot so the operator can spot a
    drift / typo without it silently disappearing.
    """
    metrics.record_question_fallback("totally_made_up")

    snap = metrics.question_fallbacks_snapshot()
    assert snap["totally_made_up"] == 1
    # Known kinds untouched
    for kind in metrics.QUESTION_FALLBACK_KINDS:
        assert snap[kind] == 0


def test_record_is_resilient_to_none_and_empty():
    """Hot-path safety: empty / None never crashes the caller."""
    metrics.record_question_fallback(None)  # type: ignore[arg-type]
    metrics.record_question_fallback("")

    snap = metrics.question_fallbacks_snapshot()
    # Both collapse to ``unknown`` per the helper's contract.
    assert snap.get("unknown", 0) == 2


def test_reset_clears_all_counters():
    metrics.record_question_fallback("language")
    metrics.record_question_fallback("safety")
    metrics.reset_question_fallback_metrics_for_tests()

    snap = metrics.question_fallbacks_snapshot()
    for value in snap.values():
        assert value == 0


# ---------- /admin/fallback-rates endpoint ----------


def _stub_admin_settings(monkeypatch, *, api_token=None, allow_open_admin=True):
    class _S:
        app_env = "dev"
        api_token = None
        allow_open_admin = True
        database_url = "sqlite:///:memory:"

    _S.api_token = api_token  # type: ignore[assignment]
    _S.allow_open_admin = allow_open_admin  # type: ignore[assignment]

    monkeypatch.setattr(admin_api, "get_settings", lambda: _S())
    monkeypatch.setattr(settings_mod, "get_settings", lambda: _S())


@pytest.fixture()
def admin_client(monkeypatch) -> TestClient:
    app = FastAPI()
    app.include_router(admin_api.router)
    return TestClient(app)


def test_admin_fallback_rates_returns_snapshot(admin_client, monkeypatch):
    _stub_admin_settings(monkeypatch, allow_open_admin=True)

    metrics.record_question_fallback("language")
    metrics.record_question_fallback("contract_unsigned")
    metrics.record_question_fallback("contract_unsigned")

    resp = admin_client.get("/admin/fallback-rates")
    assert resp.status_code == 200
    body = resp.json()
    assert "fallback_counts" in body
    counts = body["fallback_counts"]
    assert counts["language"] == 1
    assert counts["contract_unsigned"] == 2
    # Zero-count rows present for stable shape
    for kind in metrics.QUESTION_FALLBACK_KINDS:
        assert kind in counts


def test_admin_fallback_rates_rejects_when_token_missing(admin_client, monkeypatch):
    """Production misconfig must not silently expose this surface."""
    _stub_admin_settings(monkeypatch, api_token=None, allow_open_admin=False)

    resp = admin_client.get("/admin/fallback-rates")
    assert resp.status_code == 503
