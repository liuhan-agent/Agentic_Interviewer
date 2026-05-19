"""Tests for lazy database engine initialization."""
from __future__ import annotations

import importlib
from typing import Any

import pytest
import sqlalchemy
from sqlalchemy.exc import OperationalError


def test_models_base_import_does_not_connect_to_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def fail_if_called(*args: Any, **kwargs: Any) -> Any:
        calls.append((args, kwargs))
        raise AssertionError("create_engine should be lazy at import time")

    import app.models.base as base

    try:
        monkeypatch.setattr(sqlalchemy, "create_engine", fail_if_called)
        importlib.reload(base)

        assert calls == []
    finally:
        monkeypatch.undo()
        importlib.reload(base)
        import app.models as models
        for module_name in (
            "app.models.generation_trace",
            "app.models.interview_session",
            "app.models.outcome_record",
            "app.models.question_bank",
            "app.models.skill_playbook",
            "app.models.strategy_memory",
            "app.models.trace_annotation",
            "app.models.verifier_drift",
        ):
            importlib.reload(importlib.import_module(module_name))
        importlib.reload(models)


def test_prod_database_failure_does_not_fallback_to_sqlite(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.models.base as base

    class _Settings:
        app_env = "prod"
        database_url = "postgresql://user:secret@db.example/prod"

    class _FailingEngine:
        def connect(self):
            raise OperationalError("SELECT 1", {}, RuntimeError("boom"))

    calls: list[str] = []

    def fake_create_engine(url: str, **_: Any) -> Any:
        calls.append(url)
        if url.startswith("sqlite:///"):
            raise AssertionError("prod must not create sqlite fallback engine")
        return _FailingEngine()

    monkeypatch.setattr(base, "get_settings", lambda: _Settings())
    monkeypatch.setattr(base, "create_engine", fake_create_engine)

    with pytest.raises(OperationalError):
        base._resolve_engine()

    assert calls == ["postgresql://user:secret@db.example/prod"]
