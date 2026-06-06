"""Evaluate reviewed acceptance grey-readiness from question seed YAML.

Usage:
    python -m app.scripts.evaluate_reviewed_acceptance_grey PATH
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.services.question_reviewed_acceptance_grey_eval import (
    build_reviewed_acceptance_rollout_proposal_from_yaml,
)


def main(path: str | None = None) -> None:
    target = Path(path) if path is not None else _parse_args().path
    proposal = build_reviewed_acceptance_rollout_proposal_from_yaml(target)
    print(json.dumps(proposal, ensure_ascii=False, indent=2))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "path",
        type=Path,
        help="Question seed YAML file or directory to evaluate.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    main(str(args.path))
