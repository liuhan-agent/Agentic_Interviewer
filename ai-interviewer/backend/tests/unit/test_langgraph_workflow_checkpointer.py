"""Checkpointer hardening hooks for LangGraph workflow tests."""
from __future__ import annotations

import sys
import types
from types import SimpleNamespace

from app.engine.workflow import langgraph_workflow


def test_reset_default_checkpointer_clears_cached_postgres_saver() -> None:
    langgraph_workflow._POSTGRES_SAVER = object()

    langgraph_workflow.reset_default_checkpointer()

    assert langgraph_workflow._POSTGRES_SAVER is None


def test_postgres_saver_init_failure_logs_stack_for_non_prod(monkeypatch) -> None:
    class FakePostgresSaver:
        def __init__(self, pool) -> None:
            self.pool = pool

        def setup(self) -> None:
            raise RuntimeError("setup failed")

    postgres_mod = types.ModuleType("langgraph.checkpoint.postgres")
    postgres_mod.PostgresSaver = FakePostgresSaver
    pool_mod = types.ModuleType("psycopg_pool")
    pool_mod.ConnectionPool = lambda **_kwargs: object()

    monkeypatch.setitem(sys.modules, "langgraph.checkpoint.postgres", postgres_mod)
    monkeypatch.setitem(sys.modules, "psycopg_pool", pool_mod)
    monkeypatch.setattr(
        langgraph_workflow,
        "get_settings",
        lambda: SimpleNamespace(
            app_env="dev",
            database_url="postgresql://example/db",
            checkpoint_backend="postgres",
        ),
    )
    langgraph_workflow._POSTGRES_SAVER = None
    warnings: list[tuple[str, tuple, dict]] = []
    monkeypatch.setattr(
        langgraph_workflow.log,
        "warning",
        lambda msg, *args, **kwargs: warnings.append((msg, args, kwargs)),
    )

    langgraph_workflow._postgres_saver()

    assert warnings
    assert warnings[-1][2].get("exc_info") is True


def test_postgres_saver_pool_explicitly_opens_pool(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakePostgresSaver:
        def __init__(self, pool) -> None:
            self.pool = pool

        def setup(self) -> None:
            return None

    def fake_connection_pool(**kwargs):
        captured.update(kwargs)
        return object()

    postgres_mod = types.ModuleType("langgraph.checkpoint.postgres")
    postgres_mod.PostgresSaver = FakePostgresSaver
    pool_mod = types.ModuleType("psycopg_pool")
    pool_mod.ConnectionPool = fake_connection_pool

    monkeypatch.setitem(sys.modules, "langgraph.checkpoint.postgres", postgres_mod)
    monkeypatch.setitem(sys.modules, "psycopg_pool", pool_mod)
    monkeypatch.setattr(
        langgraph_workflow,
        "get_settings",
        lambda: SimpleNamespace(
            app_env="dev",
            database_url="postgresql://example/db",
            checkpoint_backend="postgres",
        ),
    )
    langgraph_workflow._POSTGRES_SAVER = None

    langgraph_workflow._postgres_saver()

    assert captured["open"] is True
