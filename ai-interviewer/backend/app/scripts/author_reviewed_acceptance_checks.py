"""Generate draft reviewed acceptance checks for question seed YAML.

Usage:
    python -m app.scripts.author_reviewed_acceptance_checks PATH
    python -m app.scripts.author_reviewed_acceptance_checks PATH --write
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.services.question_reviewed_acceptance_authoring import (
    author_reviewed_acceptance_checks,
)


def main(path: str | None = None, *, write: bool = False) -> None:
    if path is None:
        args = _parse_args()
        target = args.path
        write = bool(args.write)
    else:
        target = Path(path)
    result = author_reviewed_acceptance_checks(target, write=write)
    print(json.dumps(result.as_dict(), ensure_ascii=False, indent=2))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "path",
        type=Path,
        help="Explicit question seed YAML file or directory to scan.",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Append missing draft checks to YAML. Default is dry-run.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    main(str(args.path), write=bool(args.write))
