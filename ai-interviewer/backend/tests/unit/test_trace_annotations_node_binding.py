"""Tests for binding human annotations to concrete trace rows."""
from __future__ import annotations

from contextlib import contextmanager
from typing import Any

import pytest
from fastapi import HTTPException


class _TraceRow:
    id = 42
    session_id = "sess-annotate"
    node = "evaluator"


def test_create_annotation_binds_generation_trace_row(monkeypatch) -> None:
    from app.api.v1 import admin as admin_mod

    captured: list[Any] = []

    class _Session:
        def get(self, _model: Any, _pk: int) -> _TraceRow:
            return _TraceRow()

        def add(self, row: Any) -> None:
            row.id = 7
            captured.append(row)

        def flush(self) -> None:
            return None

    @contextmanager
    def _fake_get_session():
        yield _Session()

    monkeypatch.setattr("app.models.get_session", _fake_get_session)

    result = admin_mod.create_annotation(
        {
            "trace_id": "trace-annotate",
            "session_id": "sess-annotate",
            "turn_idx": 0,
            "generation_trace_id": 42,
            "annotation_type": "wrong_score",
            "verdict": "flagged",
            "node": "verification",
        }
    )

    assert result == {"id": 7, "ok": True}
    assert captured[0].generation_trace_id == 42
    assert captured[0].node == "evaluator"


def test_create_annotation_rejects_unknown_generation_trace(monkeypatch) -> None:
    from app.api.v1 import admin as admin_mod

    class _Session:
        def get(self, _model: Any, _pk: int) -> None:
            return None

    @contextmanager
    def _fake_get_session():
        yield _Session()

    monkeypatch.setattr("app.models.get_session", _fake_get_session)

    with pytest.raises(HTTPException) as exc:
        admin_mod.create_annotation(
            {
                "trace_id": "trace-annotate",
                "session_id": "sess-annotate",
                "turn_idx": 0,
                "generation_trace_id": 999,
                "annotation_type": "wrong_score",
            }
        )

    assert exc.value.status_code == 404
