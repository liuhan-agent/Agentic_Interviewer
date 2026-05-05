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
        node: str,
        evaluation: dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        self.node = node
        self.evaluation = evaluation
        self.state_snapshot = {"payload": payload or {}}


class _FakeQuery:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def filter(self, *_args: Any, **_kwargs: Any) -> _FakeQuery:
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


def test_evidence_rollup_counts_evaluator_and_verifier_coverage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.core.settings.get_settings", lambda: _settings_with_open_admin()
    )
    rows = [
        _FakeTraceRow(
            node="evaluator",
            evaluation={
                "source": "llm",
                "acceptance_check_results": {
                    "Names a tradeoff": {
                        "verdict": "yes",
                        "evidence": ["CAP tradeoff"],
                        "evidence_spans": [{"match": "exact"}],
                    }
                },
            },
        ),
        _FakeTraceRow(
            node="evaluator",
            evaluation={
                "source": "llm",
                "acceptance_check_results": {
                    "Mentions rollback": {
                        "verdict": "partial",
                        "evidence": ["rollback"],
                        "evidence_spans": [],
                    }
                },
            },
        ),
        _FakeTraceRow(
            node="evaluator",
            evaluation={
                "source": "fallback",
                "fallback_reason": "llm_failed",
                "acceptance_check_results": {},
            },
        ),
        _FakeTraceRow(
            node="verification",
            payload={"triggered": True, "verdict_changed": True},
        ),
        _FakeTraceRow(
            node="verification",
            payload={"triggered": False, "verdict_changed": False},
        ),
    ]
    _patch_db(monkeypatch, rows)

    resp = _client().get("/admin/evidence-rollup", params={"since": "24h"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["total_evaluator_traces"] == 3
    assert body["with_acceptance_checks"] == 2
    assert body["with_evidence_spans"] == 1
    assert body["fallback_traces"] == 1
    assert body["acceptance_check_rate"] == 0.6667
    assert body["evidence_span_rate"] == 0.3333
    assert body["fallback_rate"] == 0.3333
    assert body["verification_traces"] == 2
    assert body["verification_triggered"] == 1
    assert body["verification_changed"] == 1
    assert body["verification_change_rate"] == 1.0
