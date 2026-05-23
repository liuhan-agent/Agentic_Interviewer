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
        node: str = "ask_question",
        question: str = "How would you design this?",
        payload: dict[str, Any] | None = None,
        state: dict[str, Any] | None = None,
        has_session: bool = True,
    ) -> None:
        self.node = node
        self.question = question
        self.state_snapshot = {"payload": payload or {}, "state": state or {}}
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


def test_question_quality_rollup_counts_grounding_and_contract_signals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.core.settings.get_settings", lambda: _settings_with_open_admin()
    )
    rows = [
        _FakeTraceRow(
            payload={
                "plan_template": "deep_probe",
                "signed_by": ["generator", "evaluator"],
                "contract_acceptance_check_count": 5,
                "target_skills": ["orphan"],
                "skill_focus": {"primary": "ignored"},
            },
            state={"retrieval_block": "Should not count"},
            has_session=False,
        ),
        _FakeTraceRow(
            payload={
                "plan_template": "deep_probe",
                "signed_by": ["generator", "evaluator"],
                "contract_acceptance_check_count": 3,
                "target_skills": ["redis"],
                "skill_focus": {"primary": "cache invalidation"},
            },
            state={"retrieval_block": "Relevant JD and resume context"},
        ),
        _FakeTraceRow(
            payload={
                "plan_template": "simple",
                "signed_by": ["generator"],
                "contract_acceptance_check_count": 0,
                "target_skills": [],
                "skill_focus": {},
            },
            state={},
        ),
        _FakeTraceRow(node="evaluator"),
    ]
    _patch_db(monkeypatch, rows)

    resp = _client().get("/admin/question-quality-rollup", params={"since": "24h"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["total_ask_question_traces"] == 2
    assert body["with_acceptance_contract"] == 1
    assert body["with_evaluator_signed_contract"] == 1
    assert body["with_retrieval_context"] == 1
    assert body["with_target_skills"] == 1
    assert body["with_skill_focus"] == 1
    assert body["deep_probe_questions"] == 1
    assert body["contract_rate"] == 0.5
    assert body["retrieval_grounding_rate"] == 0.5
    assert body["avg_acceptance_checks"] == 1.5
