"""Tests for GET /admin/credibility-rollup."""
from __future__ import annotations

from contextlib import contextmanager
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


class _FakeTraceRow:
    def __init__(
        self,
        *,
        node: str = "final_report",
        session_id: str = "sess-1",
        payload: dict[str, Any] | None = None,
        state: dict[str, Any] | None = None,
    ) -> None:
        self.node = node
        self.session_id = session_id
        self.state_snapshot = {"payload": payload or {}, "state": state or {}}


class _FakeQuery:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def filter(self, *_args: Any, **_kwargs: Any) -> _FakeQuery:
        return self

    def order_by(self, *_args: Any) -> _FakeQuery:
        return self

    def limit(self, _n: int) -> _FakeQuery:
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


def test_credibility_rollup_with_precomputed_summary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sessions that already have credibility_summary in the trace."""
    monkeypatch.setattr(
        "app.core.settings.get_settings", lambda: _settings_with_open_admin()
    )
    rows = [
        _FakeTraceRow(
            session_id="sess-high",
            payload={
                "credibility_summary": {
                    "credibility_level": "high",
                    "fallback_rate": 0.0,
                    "evidence_span_miss_rate": 0.05,
                    "contract_no_rate": 0.0,
                },
                "total_turns": 8,
            },
        ),
        _FakeTraceRow(
            session_id="sess-medium",
            payload={
                "credibility_summary": {
                    "credibility_level": "medium",
                    "fallback_rate": 0.3,
                    "evidence_span_miss_rate": 0.2,
                    "contract_no_rate": 0.1,
                },
                "total_turns": 6,
            },
        ),
    ]
    _patch_db(monkeypatch, rows)

    resp = _client().get("/admin/credibility-rollup")

    assert resp.status_code == 200
    body = resp.json()
    assert body["total_sessions"] == 2
    assert body["distribution"]["high"] == 1
    assert body["distribution"]["medium"] == 1
    assert body["distribution"]["low"] == 0
    assert len(body["sessions"]) == 2


def test_credibility_rollup_computes_from_raw_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sessions without credibility_summary fall back to computation."""
    monkeypatch.setattr(
        "app.core.settings.get_settings", lambda: _settings_with_open_admin()
    )
    rows = [
        _FakeTraceRow(
            session_id="sess-computed",
            payload={
                "total_turns": 5,
                "evaluator_fallback_count": 0,
                "evidence_summary": {
                    "total_quotes": 10,
                    "unmatched_quotes": 1,
                },
                "contract_summary": {
                    "total_checks": 8,
                    "checks_no": 0,
                },
            },
        ),
    ]
    _patch_db(monkeypatch, rows)

    resp = _client().get("/admin/credibility-rollup")

    assert resp.status_code == 200
    body = resp.json()
    assert body["total_sessions"] == 1
    assert body["distribution"]["high"] == 1
    sessions = body["sessions"]
    assert sessions[0]["session_id"] == "sess-computed"
    assert sessions[0]["credibility_level"] == "high"


def test_credibility_rollup_reads_actual_final_report_trace_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Real final_report traces keep the report under state.final_report.

    The generic node payload only stores a compact event summary, so the
    rollup must not rely solely on state_snapshot.payload.
    """
    monkeypatch.setattr(
        "app.core.settings.get_settings", lambda: _settings_with_open_admin()
    )
    rows = [
        _FakeTraceRow(
            session_id="sess-real-shape",
            payload={
                "verdict": "borderline",
                "overall_score": 6.8,
                "final_status": "completed",
            },
            state={
                "final_report": {
                    "total_turns": 3,
                    "evaluator_fallback_count": 2,
                    "evidence_summary": {"total_quotes": 4, "unmatched_quotes": 3},
                    "contract_summary": {"total_checks": 5, "checks_no": 3},
                }
            },
        )
    ]
    _patch_db(monkeypatch, rows)

    resp = _client().get("/admin/credibility-rollup")

    assert resp.status_code == 200
    body = resp.json()
    assert body["total_sessions"] == 1
    assert body["sessions"][0]["session_id"] == "sess-real-shape"
    assert body["sessions"][0]["credibility_level"] == "low"


def test_credibility_rollup_skips_zero_turn_sessions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sessions with total_turns=0 and no precomputed summary are skipped."""
    monkeypatch.setattr(
        "app.core.settings.get_settings", lambda: _settings_with_open_admin()
    )
    rows = [
        _FakeTraceRow(
            session_id="sess-empty",
            payload={"total_turns": 0, "evaluator_fallback_count": 0},
        ),
    ]
    _patch_db(monkeypatch, rows)

    resp = _client().get("/admin/credibility-rollup")

    assert resp.status_code == 200
    body = resp.json()
    assert body["total_sessions"] == 0


def test_credibility_rollup_empty_db(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.core.settings.get_settings", lambda: _settings_with_open_admin()
    )
    _patch_db(monkeypatch, [])

    resp = _client().get("/admin/credibility-rollup")

    assert resp.status_code == 200
    body = resp.json()
    assert body["total_sessions"] == 0
    assert body["distribution"] == {"high": 0, "medium": 0, "low": 0}
    assert body["sessions"] == []


def test_credibility_rollup_mixed_precomputed_and_raw(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mixed old (raw) and new (precomputed) sessions in same result."""
    monkeypatch.setattr(
        "app.core.settings.get_settings", lambda: _settings_with_open_admin()
    )
    rows = [
        _FakeTraceRow(
            session_id="sess-new",
            payload={
                "credibility_summary": {
                    "credibility_level": "high",
                    "fallback_rate": 0.0,
                    "evidence_span_miss_rate": 0.0,
                    "contract_no_rate": 0.0,
                },
                "total_turns": 8,
            },
        ),
        _FakeTraceRow(
            session_id="sess-old",
            payload={
                "total_turns": 4,
                "evaluator_fallback_count": 3,
                "evidence_summary": {"total_quotes": 5, "unmatched_quotes": 3},
                "contract_summary": {"total_checks": 4, "checks_no": 3},
            },
        ),
    ]
    _patch_db(monkeypatch, rows)

    resp = _client().get("/admin/credibility-rollup")

    assert resp.status_code == 200
    body = resp.json()
    assert body["total_sessions"] == 2
    assert body["distribution"]["high"] == 1
    levels = {s["session_id"]: s["credibility_level"] for s in body["sessions"]}
    assert levels["sess-new"] == "high"
    assert levels["sess-old"] in ("medium", "low")
