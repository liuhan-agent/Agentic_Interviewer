"""Report reviewed acceptance coverage for question seed YAML.

Usage:
    python -m app.scripts.report_reviewed_acceptance_coverage PATH
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.services.question_reviewed_acceptance_report import (
    build_reviewed_acceptance_report,
)


def main(path: str | None = None) -> None:
    target = Path(path) if path is not None else _parse_args().path
    result = build_reviewed_acceptance_report(yaml_path=target)
    print(json.dumps(result.as_dict(), ensure_ascii=False, indent=2))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "path",
        type=Path,
        help="Question seed YAML file or directory to scan.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    main(str(args.path))
