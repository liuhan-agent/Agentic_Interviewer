"""Tests for the new ``GET /admin/trace-rollup`` aggregation endpoint.

The rollup powers the admin panel's roll-up card and the upcoming
24h sparkline. Tests focus on the *shape* of the response and the
input validation rules; the actual SQL aggregation is exercised by
``_compute_trace_rollup`` with hand-rolled fake DB rows so we never
need to spin up Postgres.
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.main import app

# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------


def _client() -> TestClient:
    return TestClient(app)


def test_rejects_unknown_since_window(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.core.settings.get_settings", lambda: _settings_with_open_admin()
    )
    resp = _client().get("/admin/trace-rollup", params={"since": "100y"})
    assert resp.status_code == 400
    assert "since" in resp.text


def test_rejects_unknown_groupby(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.core.settings.get_settings", lambda: _settings_with_open_admin()
    )
    resp = _client().get(
        "/admin/trace-rollup", params={"since": "24h", "groupby": "wrong"}
    )
    assert resp.status_code == 400
    assert "groupby" in resp.text


# ---------------------------------------------------------------------------
# Aggregation logic via fake DB rows
# ---------------------------------------------------------------------------


class _FakeSessionRow:
    def __init__(
        self,
        *,
        session_id: str,
        status: str,
        final_report: dict[str, Any] | None = None,
    ) -> None:
        self.session_id = session_id
        self.status = status
        self.final_report = final_report


class _FakeQuery:
    """Minimal stand-in for the SQLAlchemy query chain used in the route."""

    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def filter(self, *_args: Any, **_kwargs: Any) -> _FakeQuery:
        return self

    def limit(self, _n: int) -> _FakeQuery:
        return self

    def all(self) -> list[Any]:
        return list(self._rows)


class _FakeSession:
    def __init__(
        self,
        *,
        session_rows: list[Any],
        node_rows: list[tuple[str, str]],
    ) -> None:
        self._session_rows = session_rows
        self._node_rows = node_rows
        self._calls = 0

    def query(self, *args: Any) -> _FakeQuery:
        self._calls += 1
        return _FakeQuery(self._session_rows if self._calls == 1 else self._node_rows)


def _patch_db(
    monkeypatch: pytest.MonkeyPatch,
    *,
    session_rows: list[Any],
    node_rows: list[tuple[str, str]],
) -> None:
    @contextmanager
    def _fake_get_session():
        yield _FakeSession(session_rows=session_rows, node_rows=node_rows)

    monkeypatch.setattr("app.models.get_session", _fake_get_session)


def _settings_with_open_admin() -> Any:
    """Return a settings stub that lets the admin auth dependency pass."""
    import os

    os.environ["ALLOW_OPEN_ADMIN"] = "true"
    from app.core.settings import Settings

    return Settings(api_token="")


def test_health_groupby_merges_node_coverage_and_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.core.settings.get_settings", lambda: _settings_with_open_admin()
    )
    session_rows = [
        _FakeSessionRow(session_id="ok-1", status="completed"),
        _FakeSessionRow(session_id="ok-2", status="completed"),
        _FakeSessionRow(session_id="cx-1", status="cancelled"),
        _FakeSessionRow(session_id="empty", status="running"),
    ]
    node_rows = [
        ("ok-1", "evaluator"),
        ("ok-1", "reward_update"),
        ("ok-2", "evaluator"),
        ("ok-2", "final_report"),
        ("cx-1", "evaluator"),
        ("cx-1", "reward_update"),
    ]
    _patch_db(monkeypatch, session_rows=session_rows, node_rows=node_rows)

    resp = _client().get("/admin/trace-rollup", params={"since": "24h"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["total_sessions"] == 4
    assert body["groupby"] == "health"
    bucket_map = {b["key"]: b["count"] for b in body["buckets"]}
    assert bucket_map == {"complete": 2, "partial": 1, "missing": 1}


def test_node_groupby_returns_per_node_counts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.core.settings.get_settings", lambda: _settings_with_open_admin()
    )
    session_rows = [_FakeSessionRow(session_id="s1", status="completed")]
    node_rows = [
        ("s1", "evaluator"),
        ("s1", "evaluator"),
        ("s1", "reward_update"),
        ("s1", "final_report"),
    ]
    _patch_db(monkeypatch, session_rows=session_rows, node_rows=node_rows)

    resp = _client().get(
        "/admin/trace-rollup", params={"since": "24h", "groupby": "node"}
    )

    assert resp.status_code == 200
    bucket_map = {b["key"]: b["count"] for b in resp.json()["buckets"]}
    assert bucket_map == {"evaluator": 2, "reward_update": 1, "final_report": 1}


def test_verdict_groupby_reads_from_final_report(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.core.settings.get_settings", lambda: _settings_with_open_admin()
    )
    session_rows = [
        _FakeSessionRow(
            session_id="s1",
            status="completed",
            final_report={"overall_verdict": "hire"},
        ),
        _FakeSessionRow(
            session_id="s2",
            status="completed",
            final_report={"overall_verdict": "no_hire"},
        ),
        _FakeSessionRow(
            session_id="s3",
            status="completed",
            final_report={"verdict": "hire"},  # legacy field name
        ),
    ]
    _patch_db(monkeypatch, session_rows=session_rows, node_rows=[])

    resp = _client().get(
        "/admin/trace-rollup", params={"since": "24h", "groupby": "verdict"}
    )

    bucket_map = {b["key"]: b["count"] for b in resp.json()["buckets"]}
    assert bucket_map == {"hire": 2, "no_hire": 1}


def test_fallback_groupby_surfaces_turn_and_session_rates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.core.settings.get_settings", lambda: _settings_with_open_admin()
    )
    session_rows = [
        _FakeSessionRow(
            session_id="s1",
            status="completed",
            final_report={"total_turns": 10, "evaluator_fallback_count": 3},
        ),
        _FakeSessionRow(
            session_id="s2",
            status="completed",
            final_report={"total_turns": 5, "evaluator_fallback_count": 0},
        ),
        _FakeSessionRow(
            session_id="s3",
            status="completed",
            final_report={"total_turns": 0, "evaluator_fallback_count": 0},
        ),
    ]
    _patch_db(monkeypatch, session_rows=session_rows, node_rows=[])

    resp = _client().get(
        "/admin/trace-rollup", params={"since": "24h", "groupby": "fallback"}
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["groupby"] == "fallback"
    assert body["total_sessions"] == 3
    assert body["affected_sessions"] == 1
    assert body["fallback_turns"] == 3
    assert body["total_turns"] == 15
    assert body["fallback_rate"] == 0.2
    bucket_map = {b["key"]: b["count"] for b in body["buckets"]}
    assert bucket_map == {"clean": 2, "with_fallback": 1}


def test_empty_window_returns_clean_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.core.settings.get_settings", lambda: _settings_with_open_admin()
    )
    _patch_db(monkeypatch, session_rows=[], node_rows=[])

    resp = _client().get("/admin/trace-rollup", params={"since": "24h"})

    body = resp.json()
    assert body["total_sessions"] == 0
    assert body["buckets"] == []
    assert body["groupby"] == "health"


def test_db_outage_degrades_gracefully_to_empty_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.core.settings.get_settings", lambda: _settings_with_open_admin()
    )

    @contextmanager
    def _broken_session():
        raise RuntimeError("simulated DB outage")
        yield  # pragma: no cover

    monkeypatch.setattr("app.models.get_session", _broken_session)

    resp = _client().get("/admin/trace-rollup", params={"since": "24h"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["total_sessions"] == 0
    assert body["buckets"] == []


def test_share_rounding_is_stable_across_buckets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``share`` rounds to 4 decimals so the panel does not flicker
    on tiny float drift; the sum is allowed to be slightly off as
    long as no bucket reports a negative or > 1 share."""
    monkeypatch.setattr(
        "app.core.settings.get_settings", lambda: _settings_with_open_admin()
    )
    session_rows = [
        _FakeSessionRow(session_id=f"s{i}", status="completed") for i in range(7)
    ]
    node_rows = []
    for i in range(7):
        node_rows.append((f"s{i}", "evaluator"))
        node_rows.append((f"s{i}", "reward_update"))
    _patch_db(monkeypatch, session_rows=session_rows, node_rows=node_rows)

    resp = _client().get("/admin/trace-rollup", params={"since": "24h"})

    body = resp.json()
    for bucket in body["buckets"]:
        assert 0 <= bucket["share"] <= 1
    assert sum(b["count"] for b in body["buckets"]) == 7
