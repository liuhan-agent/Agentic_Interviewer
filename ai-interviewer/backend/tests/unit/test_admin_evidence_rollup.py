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


def _patch_open_admin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.core.settings.get_settings", lambda: _settings_with_open_admin()
    )
    monkeypatch.setattr(
        "app.api.v1.admin.get_settings", lambda: _settings_with_open_admin()
    )


class _FakeTraceRow:
    def __init__(
        self,
        *,
        node: str,
        evaluation: dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
        has_session: bool = True,
    ) -> None:
        self.node = node
        self.evaluation = evaluation
        self.state_snapshot = {"payload": payload or {}}
        self.has_session = has_session


class _FakeQuery:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows
        self._joined_to_sessions = False

    def join(self, *_args: Any, **_kwargs: Any) -> _FakeQuery:
        self._joined_to_sessions = True
        return self

    def filter(self, *_args: Any, **_kwargs: Any) -> _FakeQuery:
        return self

    def limit(self, _n: int) -> _FakeQuery:
        return self

    def all(self) -> list[Any]:
        if self._joined_to_sessions:
            return [row for row in self._rows if getattr(row, "has_session", True)]
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
    _patch_open_admin(monkeypatch)
    rows = [
        _FakeTraceRow(
            node="evaluator",
            evaluation={
                "source": "llm",
                "acceptance_check_results": {
                    "Orphan trace": {
                        "verdict": "yes",
                        "evidence": ["should not count"],
                        "evidence_spans": [{"match": "exact"}],
                    }
                },
            },
            has_session=False,
        ),
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
            node="evaluator",
            evaluation={
                "source": "llm",
                "acceptance_check_results": {
                    "Unsupported yes": {
                        "verdict": "yes",
                        "evidence": [],
                        "evidence_spans": [],
                    },
                    "None span yes": {
                        "verdict": "yes",
                        "evidence": ["phantom quote"],
                        "evidence_spans": [{"match": "none"}],
                    },
                },
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
    assert body["total_evaluator_traces"] == 4
    assert body["with_acceptance_checks"] == 3
    assert body["with_evidence_spans"] == 2
    assert body["fallback_traces"] == 1
    assert body["acceptance_check_rate"] == 0.75
    assert body["evidence_span_rate"] == 0.5
    assert body["fallback_rate"] == 0.25
    assert body["total_acceptance_checks"] == 4
    assert body["yes_checks"] == 3
    assert body["unsupported_yes_checks"] == 1
    assert body["unsupported_yes_rate"] == 0.3333
    assert body["evidence_span_total"] == 2
    assert body["evidence_span_none_count"] == 1
    assert body["evidence_span_none_rate"] == 0.5
    assert body["evidence_quote_total"] == 3
    assert body["avg_evidence_quotes_per_check"] == 0.75
    assert body["verification_traces"] == 2
    assert body["verification_triggered"] == 1
    assert body["verification_changed"] == 1
    assert body["verification_change_rate"] == 1.0
