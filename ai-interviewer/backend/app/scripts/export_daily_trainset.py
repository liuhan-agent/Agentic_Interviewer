"""Export a rolling-window slice of ``GenerationTrace`` rows as JSONL.

Typical usage from a cron / scheduler:

.. code-block:: bash

    python -m app.scripts.export_daily_trainset --days 1 --out ./data/trainset/$(date +%Y%m%d).jsonl

Either ``--days`` or ``--since`` is **required** so the script never
accidentally full-dumps the trace table in production.  That failure
mode turned up during v1 review and the explicit guard below exists
specifically to prevent it.  If you *do* want a full dump, call
:func:`app.data.trainset_builder.export_jsonl` directly from a REPL.
"""
from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.core.logging import configure_logging, get_logger
from app.data.trainset_builder import export_jsonl

log = get_logger(__name__)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export an incremental GenerationTrace slice to JSONL.",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=None,
        help="Export traces created within the last N days.",
    )
    parser.add_argument(
        "--since",
        type=str,
        default=None,
        help="ISO-8601 timestamp; export traces with created_at >= this value.",
    )
    parser.add_argument(
        "--out",
        required=True,
        help="Destination JSONL path (parent dirs are created as needed).",
    )
    return parser.parse_args(argv)


def _resolve_since(args: argparse.Namespace) -> datetime:
    if args.days is None and args.since is None:
        raise SystemExit(
            "ERROR: must pass either --days or --since. Refusing to "
            "full-dump the trace table. See docstring for rationale."
        )
    if args.since:
        ts = datetime.fromisoformat(args.since)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        return ts
    return datetime.now(UTC) - timedelta(days=int(args.days))


def main(argv: list[str] | None = None) -> None:
    configure_logging()
    args = _parse_args(argv)
    since = _resolve_since(args)
    out = Path(args.out)
    n = export_jsonl(out, since=since)
    log.info("exported %d rows since %s to %s", n, since.isoformat(), out)
    print(f"exported {n} rows since {since.isoformat()} to {out}")


if __name__ == "__main__":
    main()
