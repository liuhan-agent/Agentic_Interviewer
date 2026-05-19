"""Import markdown skill playbooks into the database runtime store.

Usage:
    python -m app.scripts.import_skill_playbooks
    python -m app.scripts.import_skill_playbooks --archive-missing
"""
from __future__ import annotations

import argparse
from pathlib import Path

from app.core.logging import get_logger
from app.core.settings import get_settings
from app.models import get_session, init_db
from app.services.skill_playbook_import import import_skill_playbook_dir

log = get_logger(__name__)


def main(*, archive_missing: bool = False) -> None:
    settings = get_settings()
    skill_dir = Path(settings.knowledge_dir) / "skills"
    init_db()
    with get_session() as session:
        result = import_skill_playbook_dir(
            skill_dir,
            session=session,
            archive_missing=archive_missing,
        )
    log.info(
        (
            "skill playbook import complete: imported=%d updated=%d "
            "unchanged=%d archived=%d skipped=%d"
        ),
        result.imported,
        result.updated,
        result.unchanged,
        result.archived,
        result.skipped,
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--archive-missing",
        action="store_true",
        help="Archive manual markdown cards that are absent from knowledge/skills.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    main(archive_missing=bool(args.archive_missing))
