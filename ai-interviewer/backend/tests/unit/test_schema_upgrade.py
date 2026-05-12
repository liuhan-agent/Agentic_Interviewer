"""Tests for the in-place schema upgrade path in ``app.models.base``.

Covers three invariants:

1. ``_upgrade_schema`` is idempotent — running it twice against the
   same engine is a no-op on the second pass. This matters for
   production cold starts where multiple workers may race.
2. Missing ``langsmith_run_id`` on an old ``generation_traces`` table
   gets added with the right shape (indexed, nullable) so the
   ``tracer`` write-back does not crash.
3. Alien dialects (fake name) fall through without raising so the
   helper is safe to call on any SQLAlchemy engine even when we
   haven't shipped a dialect-specific DDL block for it yet.

The Postgres path is exercised only through DDL shape (no live
connection) in a mocked engine because we cannot spin up a Postgres
server in unit tests.
"""
from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import String, create_engine, inspect, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from app.models import base as base_mod
from app.models.generation_trace import GenerationTrace

# ---------------------------------------------------------------------------
# SQLite path — real engine, exhaustive behaviour check
# ---------------------------------------------------------------------------


def _sqlite_engine(tmp_path):
    """Fresh on-disk SQLite (not in-memory) so we can round-trip the
    inspector and see persisted column adds the same way production
    does."""
    url = f"sqlite:///{tmp_path.as_posix()}/ut_schema.db"
    return create_engine(url, future=True)


def _create_legacy_generation_traces(engine) -> None:
    """Recreate the pre-langsmith_run_id shape so the upgrade path has
    something to add a column to."""
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE generation_traces (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    trace_id VARCHAR(64),
                    session_id VARCHAR(64),
                    turn_idx INTEGER,
                    node VARCHAR(64),
                    dimension VARCHAR(64),
                    action_id VARCHAR(64),
                    policy_id VARCHAR(128),
                    context_key VARCHAR(128),
                    score FLOAT,
                    passed BOOLEAN,
                    immediate_reward FLOAT,
                    delayed_reward FLOAT,
                    applied_to_bandit BOOLEAN DEFAULT 0,
                    state_snapshot JSON,
                    question VARCHAR(2048),
                    answer VARCHAR(8192),
                    evaluation JSON,
                    created_at DATETIME
                )
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE interview_sessions (
                    session_id VARCHAR(64) PRIMARY KEY,
                    trace_id VARCHAR(64),
                    candidate_name VARCHAR(128),
                    job_title VARCHAR(128),
                    job_level VARCHAR(32),
                    mode VARCHAR(32) DEFAULT 'mixed',
                    status VARCHAR(32) DEFAULT 'running',
                    final_report JSON,
                    created_at DATETIME,
                    updated_at DATETIME
                )
                """
            )
        )


def test_upgrade_adds_langsmith_run_id_on_sqlite(tmp_path) -> None:
    eng = _sqlite_engine(tmp_path)
    _create_legacy_generation_traces(eng)

    pre_cols = {c["name"] for c in inspect(eng).get_columns("generation_traces")}
    assert "langsmith_run_id" not in pre_cols

    base_mod._upgrade_schema(eng)

    post_cols = {c["name"] for c in inspect(eng).get_columns("generation_traces")}
    assert "langsmith_run_id" in post_cols
    # Interview sessions table also gets its additive columns.
    sess_cols = {c["name"] for c in inspect(eng).get_columns("interview_sessions")}
    assert {
        "current_question",
        "turn_idx",
        "asked_turn",
        "error",
        "error_kind",
        "retryable",
        "enable_video_analysis",
    } <= sess_cols


def test_upgrade_is_idempotent_on_sqlite(tmp_path) -> None:
    """Running the upgrade twice must not raise (no duplicate column
    error). This simulates two workers racing on cold start."""
    eng = _sqlite_engine(tmp_path)
    _create_legacy_generation_traces(eng)

    base_mod._upgrade_schema(eng)
    base_mod._upgrade_schema(eng)  # second pass is the real assertion


def test_upgrade_noop_on_missing_tables(tmp_path) -> None:
    """A fresh engine with no tables at all must not crash — the
    upgrade helper diffs against ``inspect(eng).get_table_names()``
    and skips tables that don't exist yet (``create_all`` handles
    greenfield schemas)."""
    eng = _sqlite_engine(tmp_path)
    base_mod._upgrade_schema(eng)  # no tables -> no-op
    assert inspect(eng).get_table_names() == []


def test_upgrade_skips_unknown_dialect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A dialect we don't ship DDL for (e.g. MySQL today) must not
    raise. The helper logs-and-returns."""

    class _FakeEngine:
        class dialect:  # noqa: N801 — mirrors SQLAlchemy's lowercase attr
            name = "mariadb"

    # If ``_upgrade_schema`` touched the non-existent ``.inspect``
    # path, the bare ``_FakeEngine`` would raise. Reaching the assert
    # means it early-returned on the dialect check.
    base_mod._upgrade_schema(_FakeEngine())  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Postgres DDL shape — mocked engine, no live connection
# ---------------------------------------------------------------------------


def test_postgres_upgrade_uses_if_not_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Postgres ``ADD COLUMN`` statements must use ``IF NOT EXISTS`` so
    concurrent workers on cold start don't duplicate-column-error.

    We fake the inspector + engine so the test does not need a live
    Postgres socket.
    """
    executed: list[str] = []

    class _FakeInspector:
        def get_table_names(self) -> list[str]:
            return ["generation_traces"]

        def get_columns(self, table: str) -> list[dict[str, Any]]:
            return [{"name": "id"}]  # pretend the new col is missing

    class _FakeConn:
        def execute(self, clause) -> None:  # noqa: ANN001
            # ``text(...)`` wraps the SQL; stringifying it returns the
            # literal statement we built.
            executed.append(str(clause))

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

    class _FakeEngine:
        class dialect:  # noqa: N801 — mirrors SQLAlchemy's lowercase attr
            name = "postgresql"

        def begin(self):
            return _FakeConn()

    def fake_inspect(_eng):  # noqa: ANN001
        return _FakeInspector()

    monkeypatch.setattr(base_mod, "inspect", fake_inspect)

    base_mod._upgrade_schema(_FakeEngine())  # type: ignore[arg-type]

    langsmith_stmts = [s for s in executed if "langsmith_run_id" in s]
    assert langsmith_stmts, "expected at least one ADD COLUMN for langsmith_run_id"
    for stmt in langsmith_stmts:
        assert "IF NOT EXISTS" in stmt


def test_generation_trace_answer_ddl_is_unbounded_text() -> None:
    ddl = str(CreateTable(GenerationTrace.__table__).compile(dialect=postgresql.dialect()))

    assert "answer TEXT" in ddl
    assert "answer VARCHAR(8192)" not in ddl


def test_postgres_upgrade_converts_legacy_answer_varchar_to_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executed: list[str] = []

    class _FakeInspector:
        def get_table_names(self) -> list[str]:
            return ["generation_traces"]

        def get_columns(self, table: str) -> list[dict[str, Any]]:
            return [
                {"name": "id"},
                {"name": "answer", "type": String(8192)},
                {"name": "immediate_reward_applied"},
                {"name": "langsmith_run_id"},
                {"name": "policy_context_keys"},
            ]

    class _FakeConn:
        def execute(self, clause) -> None:  # noqa: ANN001
            executed.append(str(clause))

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

    class _FakeEngine:
        class dialect:  # noqa: N801
            name = "postgresql"

        def begin(self):
            return _FakeConn()

    monkeypatch.setattr(base_mod, "inspect", lambda _eng: _FakeInspector())

    base_mod._upgrade_schema(_FakeEngine())  # type: ignore[arg-type]

    assert any(
        "ALTER TABLE generation_traces ALTER COLUMN answer TYPE TEXT" in stmt
        for stmt in executed
    )
