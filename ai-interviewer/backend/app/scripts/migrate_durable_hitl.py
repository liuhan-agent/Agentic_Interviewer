"""One-shot migration: add durable HITL columns to interview_sessions.

Adds ``current_question``, ``turn_idx``, and ``asked_turn`` to the
existing ``interview_sessions`` table.  Safe to run multiple times —
each ALTER is guarded by an existence check.

Usage::

    python -m app.scripts.migrate_durable_hitl
    python -m app.scripts.migrate_durable_hitl --dry-run
"""
from __future__ import annotations

import argparse

from sqlalchemy import inspect, text

from app.core.logging import get_logger
from app.models.base import get_engine

log = get_logger(__name__)

TABLE = "interview_sessions"

COLUMNS = [
    ("current_question", "JSONB"),
    ("turn_idx", "INTEGER DEFAULT 0 NOT NULL"),
    ("asked_turn", "INTEGER DEFAULT -1 NOT NULL"),
]


def _existing_columns() -> set[str]:
    engine = get_engine()
    insp = inspect(engine)
    return {c["name"] for c in insp.get_columns(TABLE)}


def migrate(*, dry_run: bool = False) -> list[str]:
    existing = _existing_columns()
    stmts: list[str] = []
    for col_name, col_type in COLUMNS:
        if col_name in existing:
            log.info("column %s.%s already exists — skipping", TABLE, col_name)
            continue
        stmt = f"ALTER TABLE {TABLE} ADD COLUMN {col_name} {col_type}"
        stmts.append(stmt)

    if not stmts:
        log.info("nothing to migrate")
        return stmts

    if dry_run:
        for s in stmts:
            print(f"[DRY-RUN] {s}")
        return stmts

    engine = get_engine()
    with engine.begin() as conn:
        for s in stmts:
            log.info("executing: %s", s)
            conn.execute(text(s))

    log.info("migration complete (%d statement(s))", len(stmts))
    return stmts


def main() -> None:
    parser = argparse.ArgumentParser(description="Add durable HITL columns")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    migrate(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
