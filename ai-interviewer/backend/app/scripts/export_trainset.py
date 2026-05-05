"""Export traces + outcomes to a JSONL training file.

Usage::

    python -m app.scripts.export_trainset --out .local/trainset.jsonl
"""
from __future__ import annotations

import argparse
from pathlib import Path

from app.core.logging import get_logger
from app.data.trainset_builder import export_jsonl

log = get_logger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=".local/trainset.jsonl")
    parser.add_argument(
        "--session",
        action="append",
        default=None,
        help="Restrict to specific session IDs (repeatable).",
    )
    args = parser.parse_args()
    path = Path(args.out)
    count = export_jsonl(path, session_ids=args.session)
    print(f"wrote {count} rows to {path}")


if __name__ == "__main__":
    main()
