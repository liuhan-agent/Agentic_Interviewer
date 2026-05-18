"""SQLAlchemy engine + session factory.

Uses ``DATABASE_URL`` from settings. We fall back to a local SQLite
file when the configured URL is unreachable so that ``run_demo`` still
works in environments without a Postgres container. This pattern
mirrors the vectorstore's "graceful offline" fallback.
"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import Table, Text, create_engine, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.logging import get_logger
from app.core.settings import get_settings

log = get_logger(__name__)
_engine: Engine | None = None


class Base(DeclarativeBase):
    pass


def _redact_database_url(url: str) -> str:
    """Return a log-safe database URL with credentials removed."""
    try:
        from sqlalchemy.engine import make_url

        return str(make_url(url).render_as_string(hide_password=True))
    except Exception:
        return "<redacted-database-url>"


def _resolve_engine() -> Engine:
    """Try the configured URL, fall back to a local sqlite file.

    The SQLite fallback persists under ``backend/.local/interviewer.db``
    so traces survive across demo runs - exactly what Phase 2 needs to
    verify delayed reward back-filling without requiring Docker.
    """
    settings = get_settings()
    url = settings.database_url
    try:
        eng = create_engine(url, future=True, pool_pre_ping=True)
        # Cheap connectivity check so we can fall back before we start handing
        # the engine out to callers. ``connect()`` opens a real socket for
        # postgres; for sqlite it is always fine.
        with eng.connect() as conn:
            conn.exec_driver_sql("SELECT 1")
        return eng
    except OperationalError as e:
        if getattr(settings, "app_env", "dev") == "prod":
            log.error(
                "Primary database %s unreachable; refusing sqlite fallback in prod",
                _redact_database_url(url),
            )
            raise
        log.warning(
            "Primary database %s unreachable (%s); using sqlite fallback",
            _redact_database_url(url),
            e,
        )
    except Exception as e:  # pragma: no cover
        if getattr(settings, "app_env", "dev") == "prod":
            log.error(
                "Primary database %s failed; refusing sqlite fallback in prod",
                _redact_database_url(url),
            )
            raise
        log.warning(
            "Primary database %s failed (%s); using sqlite fallback",
            _redact_database_url(url),
            e,
        )

    fallback_dir = Path(__file__).resolve().parents[2] / ".local"
    fallback_dir.mkdir(exist_ok=True)
    sqlite_url = f"sqlite:///{fallback_dir.as_posix()}/interviewer.db"
    return create_engine(sqlite_url, future=True, connect_args={"check_same_thread": False})


SessionLocal = sessionmaker(expire_on_commit=False, autoflush=False)


def get_engine() -> Engine:
    """Return the process engine, creating it on first real DB use."""
    global _engine
    if _engine is None:
        _engine = _resolve_engine()
        SessionLocal.configure(bind=_engine)
    return _engine


def __getattr__(name: str) -> Engine:
    if name == "engine":
        return get_engine()
    raise AttributeError(name)


_SQLITE_UPGRADES: dict[str, dict[str, str]] = {
    "interview_sessions": {
        "session_token_hash": "VARCHAR(128)",
        "session_token_expires_at": "DATETIME",
        "recovery_token_hash": "VARCHAR(128)",
        "recovery_token_expires_at": "DATETIME",
        "recovery_token_revoked_at": "DATETIME",
        "current_question": "JSON",
        "llm_config_meta": "JSON",
        "setup_snapshot": "JSON",
        "enable_video_analysis": "BOOLEAN DEFAULT 0",
        "turn_idx": "INTEGER DEFAULT 0",
        "asked_turn": "INTEGER DEFAULT -1",
        "error": "TEXT",
        "error_kind": "VARCHAR(32)",
        "retryable": "BOOLEAN DEFAULT 0",
    },
    "generation_traces": {
        "immediate_reward_applied": "BOOLEAN DEFAULT 0",
        "langsmith_run_id": "VARCHAR(64)",
        "policy_context_keys": "JSON",
    },
    "trace_annotations": {
        "generation_trace_id": "INTEGER",
        "node": "VARCHAR(64)",
    },
    "outcome_records": {
        "source": "VARCHAR(32) DEFAULT 'ats_sync'",
        "helpful_score": "REAL",
    },
    "strategy_memories": {
        "quality_reason": "VARCHAR(512)",
    },
    "skill_playbook_cards": {
        "generator_moves": "JSON DEFAULT '[]'",
        "watch_for": "JSON DEFAULT '[]'",
        "avoid": "JSON DEFAULT '[]'",
        "evaluator_rubric_hints": "JSON DEFAULT '[]'",
        "positive_signals": "JSON DEFAULT '[]'",
        "negative_signals": "JSON DEFAULT '[]'",
        "score_bias_rules": "JSON DEFAULT '[]'",
        "evaluator_visibility": "BOOLEAN DEFAULT 0",
    },
}

_POSTGRES_UPGRADES: dict[str, dict[str, str]] = {
    "interview_sessions": {
        "session_token_hash": "VARCHAR(128)",
        "session_token_expires_at": "TIMESTAMP WITH TIME ZONE",
        "recovery_token_hash": "VARCHAR(128)",
        "recovery_token_expires_at": "TIMESTAMP WITH TIME ZONE",
        "recovery_token_revoked_at": "TIMESTAMP WITH TIME ZONE",
        "current_question": "JSONB",
        "llm_config_meta": "JSONB",
        "setup_snapshot": "JSONB",
        "enable_video_analysis": "BOOLEAN DEFAULT FALSE",
        "turn_idx": "INTEGER DEFAULT 0",
        "asked_turn": "INTEGER DEFAULT -1",
        "error": "TEXT",
        "error_kind": "VARCHAR(32)",
        "retryable": "BOOLEAN DEFAULT FALSE",
    },
    "generation_traces": {
        "immediate_reward_applied": "BOOLEAN DEFAULT FALSE",
        "langsmith_run_id": "VARCHAR(64)",
        "policy_context_keys": "JSONB",
    },
    "trace_annotations": {
        "generation_trace_id": "INTEGER",
        "node": "VARCHAR(64)",
    },
    "outcome_records": {
        "source": "VARCHAR(32) DEFAULT 'ats_sync'",
        "helpful_score": "DOUBLE PRECISION",
    },
    "strategy_memories": {
        "quality_reason": "VARCHAR(512)",
    },
    "skill_playbook_cards": {
        "generator_moves": "JSONB DEFAULT '[]'::jsonb",
        "watch_for": "JSONB DEFAULT '[]'::jsonb",
        "avoid": "JSONB DEFAULT '[]'::jsonb",
        "evaluator_rubric_hints": "JSONB DEFAULT '[]'::jsonb",
        "positive_signals": "JSONB DEFAULT '[]'::jsonb",
        "negative_signals": "JSONB DEFAULT '[]'::jsonb",
        "score_bias_rules": "JSONB DEFAULT '[]'::jsonb",
        "evaluator_visibility": "BOOLEAN DEFAULT FALSE",
    },
}

_POSTGRES_TYPE_UPGRADES: dict[str, dict[str, str]] = {
    "generation_traces": {
        "answer": "TEXT",
    },
}

_SQLITE_SKIP_TABLES = {"session_anchor_chunks"}


def _tables_for_create_all(
    eng: Engine,
    *,
    include_session_anchor: bool = True,
) -> list[Table]:
    """Return tables that can be created safely for the active dialect."""

    tables = list(Base.metadata.sorted_tables)
    if eng.dialect.name == "sqlite" or not include_session_anchor:
        return [table for table in tables if table.name not in _SQLITE_SKIP_TABLES]
    return tables


def _ensure_pgvector_extension(eng: Engine) -> bool:
    if eng.dialect.name != "postgresql":
        return False
    try:
        with eng.begin() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        return True
    except SQLAlchemyError as e:
        if getattr(get_settings(), "app_env", "dev") == "prod":
            raise
        log.warning(
            "pgvector extension unavailable on %s; session anchor table skipped (%s)",
            _redact_database_url(str(eng.url)),
            e,
        )
        return False


def _ensure_pgvector_indexes(eng: Engine) -> None:
    if eng.dialect.name != "postgresql":
        return
    with eng.begin() as conn:
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_session_anchor_chunks_embedding_hnsw "
                "ON session_anchor_chunks USING hnsw "
                "(embedding vector_cosine_ops)"
            )
        )


def _upgrade_schema(eng: Engine) -> None:
    """Bring existing tables in line with additive column changes.

    ``create_all`` intentionally does not alter existing tables, so
    this helper fills the gap for both the SQLite fallback used by
    demos / CI and the Postgres backend used by real deployments.

    Both dialects rely on ``ADD COLUMN``-only DDL (no drops, no type
    changes, no backfills) so the upgrade is safe to run on every
    startup. Indexes on the new columns are intentionally left to
    ``create_all`` on greenfield databases; adding them on a hot
    Postgres table would need ``CREATE INDEX CONCURRENTLY`` and an
    out-of-band migration story we don't want to invent here.

    Safety notes
    ------------
    - Every diff is computed against a fresh ``inspect(engine)`` read
      so repeated calls are idempotent.
    - Postgres ``ADD COLUMN`` takes a short ACCESS EXCLUSIVE lock; the
      ``nullable`` columns we add never rewrite the table, so the
      lock window is bounded to catalog update time.
    - Unknown dialects (e.g. MySQL) fall through as a no-op; adding
      support is a two-line change — replicate the ``_POSTGRES_UPGRADES``
      block with dialect-specific DDL.
    """
    dialect = eng.dialect.name
    if dialect == "sqlite":
        tables_to_upgrade = _SQLITE_UPGRADES
    elif dialect == "postgresql":
        tables_to_upgrade = _POSTGRES_UPGRADES
    else:
        log.debug("schema upgrade skipped; dialect %s unsupported", dialect)
        return

    inspector = inspect(eng)
    tables = set(inspector.get_table_names())

    for table, additions in tables_to_upgrade.items():
        _upgrade_table(eng, inspector, tables, table, additions, dialect=dialect)
    if dialect == "postgresql":
        _upgrade_postgres_column_types(eng, inspector, tables)


_upgrade_sqlite_schema = _upgrade_schema  # Back-compat alias for older call sites/tests.


def _upgrade_table(
    eng: Engine,
    inspector,
    tables: set[str],
    table: str,
    additions: dict[str, str],
    *,
    dialect: str,
) -> None:
    if table not in tables:
        return
    existing = {col["name"] for col in inspector.get_columns(table)}
    missing = {name: ddl for name, ddl in additions.items() if name not in existing}
    if not missing:
        return
    with eng.begin() as conn:
        for name, ddl in missing.items():
            # Postgres supports ``ADD COLUMN IF NOT EXISTS`` natively,
            # which turns a concurrent upgrade race (two workers on
            # cold start) into a no-op instead of a duplicate-column
            # error. SQLite has no such clause, but our inspector diff
            # above already filters to missing columns.
            if_not_exists = "IF NOT EXISTS " if dialect == "postgresql" else ""
            conn.execute(
                text(f"ALTER TABLE {table} ADD COLUMN {if_not_exists}{name} {ddl}")
            )
    log.info(
        "%s schema upgraded on %s: added %s",
        dialect,
        table,
        ", ".join(sorted(missing)),
    )


def _upgrade_postgres_column_types(
    eng: Engine,
    inspector,
    tables: set[str],
) -> None:
    for table, alterations in _POSTGRES_TYPE_UPGRADES.items():
        if table not in tables:
            continue
        columns = {col["name"]: col for col in inspector.get_columns(table)}
        statements: list[str] = []
        for name, ddl in alterations.items():
            col = columns.get(name)
            if col is None:
                continue
            if _is_text_column(col.get("type")):
                continue
            statements.append(f"ALTER TABLE {table} ALTER COLUMN {name} TYPE {ddl}")
        if not statements:
            continue
        with eng.begin() as conn:
            for stmt in statements:
                conn.execute(text(stmt))
        log.info(
            "postgresql schema upgraded on %s: altered %s",
            table,
            ", ".join(sorted(alterations)),
        )


def _is_text_column(column_type) -> bool:  # noqa: ANN001
    if isinstance(column_type, Text):
        return True
    return column_type.__class__.__name__.lower() == "text"


@contextmanager
def get_session() -> Iterator[Session]:
    get_engine()
    sess = SessionLocal()
    try:
        yield sess
        sess.commit()
    except Exception:
        sess.rollback()
        raise
    finally:
        sess.close()


def init_db() -> None:
    """Create all tables. Safe to call many times.

    Intentionally lazy-imports the models so that importing ``base``
    doesn't pull them in unless ``init_db`` is actually called.
    """
    from app.models import (  # noqa: F401
        generation_trace,
        interview_session,
        outcome_record,
        question_bank,
        session_anchor,
        skill_playbook,
        strategy_memory,
        verifier_drift,
    )

    eng = get_engine()
    pgvector_available = _ensure_pgvector_extension(eng)
    Base.metadata.create_all(
        eng,
        tables=_tables_for_create_all(
            eng,
            include_session_anchor=pgvector_available,
        ),
    )
    _upgrade_schema(eng)
    if pgvector_available:
        _ensure_pgvector_indexes(eng)
    log.info("db schema ensured on %s", eng.url)
