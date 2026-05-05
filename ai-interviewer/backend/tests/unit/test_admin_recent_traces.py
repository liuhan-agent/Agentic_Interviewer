"""Tests for ``GET /admin/recent-traces`` reverse-lookup endpoint.

The reverse-lookup powers the admin panel's "what did node X just do
across every session" view. We pin three behaviours:

1. Unknown node names are rejected with 400 so a typo cannot
   accidentally fan out a full table scan.
2. Limit is clamped (1..200) so a curious operator cannot shoot
   themselves in the foot with ``?limit=999999``.
3. The payload shape mirrors the structure the panel renders
   without needing further transformation.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.main import app


def _client() -> TestClient:
    return TestClient(app)


def _settings_with_open_admin() -> Any:
    import os

    os.environ["ALLOW_OPEN_ADMIN"] = "true"
    from app.core.settings import Settings

    return Settings(api_token="")


class _FakeRow:
    def __init__(self, *, sid: str, node: str, score: float | None = None) -> None:
        self.id = hash(sid) & 0xFFFF
        self.session_id = sid
        self.node = node
        self.dimension = "system_design"
        self.turn_idx = 1
        self.score = score
        self.passed = bool(score and score >= 7.0)
        self.immediate_reward = 0.5
        self.action_id = "plan_adaptive"
        self.context_key = "senior:system_design"
        self.langsmith_run_id = None
        self.created_at = datetime.now(UTC)


class _FakeQuery:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def filter(self, *_args: Any, **_kwargs: Any) -> "_FakeQuery":
        return self

    def order_by(self, *_args: Any) -> "_FakeQuery":
        return self

    def limit(self, _n: int) -> "_FakeQuery":
        return self

    def all(self) -> list[Any]:
        return list(self._rows)


class _FakeSession:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def query(self, *_args: Any) -> _FakeQuery:
        return _FakeQuery(self._rows)


def _patch_db(monkeypatch: pytest.MonkeyPatch, rows: list[Any]) -> None:
    @contextmanager
    def _fake_get_session():
        yield _FakeSession(rows)

    monkeypatch.setattr("app.models.get_session", _fake_get_session)


def test_rejects_unknown_node(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.core.settings.get_settings", lambda: _settings_with_open_admin()
    )
    resp = _client().get(
        "/admin/recent-traces", params={"node": "ghost", "limit": 10}
    )
    assert resp.status_code == 400
    assert "node" in resp.text


def test_accepts_training_plan_node(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.core.settings.get_settings", lambda: _settings_with_open_admin()
    )
    _patch_db(monkeypatch, [_FakeRow(sid="sess-plan", node="training_plan")])

    resp = _client().get(
        "/admin/recent-traces", params={"node": "training_plan", "limit": 10}
    )

    assert resp.status_code == 200
    assert resp.json()["node"] == "training_plan"


def test_caps_limit_to_200(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.core.settings.get_settings", lambda: _settings_with_open_admin()
    )
    rows = [
        _FakeRow(sid=f"sess-{i}", node="evaluator", score=7.0 + (i % 3) * 0.1)
        for i in range(5)
    ]
    _patch_db(monkeypatch, rows)

    resp = _client().get(
        "/admin/recent-traces", params={"node": "evaluator", "limit": 9999}
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["limit"] == 200
    assert body["node"] == "evaluator"
    assert len(body["items"]) == 5
    item = body["items"][0]
    for key in (
        "id",
        "session_id",
        "node",
        "dimension",
        "turn_idx",
        "score",
        "passed",
        "immediate_reward",
        "action_id",
        "context_key",
        "langsmith_run_id",
        "created_at",
    ):
        assert key in item


def test_db_failure_returns_empty_items(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.core.settings.get_settings", lambda: _settings_with_open_admin()
    )

    @contextmanager
    def _broken():
        raise RuntimeError("simulated outage")
        yield  # pragma: no cover

    monkeypatch.setattr("app.models.get_session", _broken)

    resp = _client().get(
        "/admin/recent-traces", params={"node": "evaluator", "limit": 10}
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["items"] == []
    assert body["node"] == "evaluator"
