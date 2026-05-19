"""Import YAML question seeds into the structured question-bank tables.

Usage:
    python -m app.scripts.import_question_seeds
    python -m app.scripts.import_question_seeds --archive-missing
"""
from __future__ import annotations

import argparse
from pathlib import Path

from app.core.logging import get_logger
from app.core.settings import get_settings
from app.models import get_session, init_db
from app.services.question_seed_import import import_question_seed_dir

log = get_logger(__name__)


def main(*, archive_missing: bool = False) -> None:
    settings = get_settings()
    seed_dir = Path(settings.knowledge_dir) / "question_seeds"
    init_db()
    with get_session() as session:
        result = import_question_seed_dir(
            seed_dir,
            session=session,
            archive_missing=archive_missing,
        )
    log.info(
        (
            "question seed import complete: imported_seeds=%d updated_seeds=%d "
            "unchanged_seeds=%d imported_variants=%d updated_variants=%d "
            "unchanged_variants=%d archived_seeds=%d archived_variants=%d"
        ),
        result.imported_seeds,
        result.updated_seeds,
        result.unchanged_seeds,
        result.imported_variants,
        result.updated_variants,
        result.unchanged_variants,
        result.archived_seeds,
        result.archived_variants,
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--archive-missing",
        action="store_true",
        help="Archive DB seeds/variants that are absent from YAML.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    main(archive_missing=bool(args.archive_missing))
