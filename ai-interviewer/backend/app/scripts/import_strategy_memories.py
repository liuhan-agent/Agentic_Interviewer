"""Import markdown strategy seeds into the database runtime store.

Usage:
    python -m app.scripts.import_strategy_memories
"""
from __future__ import annotations

from pathlib import Path

from app.core.logging import get_logger
from app.core.settings import get_settings
from app.models import get_session, init_db
from app.services.strategy_memory_import import import_strategy_seed_dir

log = get_logger(__name__)


def main() -> None:
    settings = get_settings()
    strategy_dir = Path(settings.knowledge_dir) / "strategy"
    init_db()
    with get_session() as session:
        result = import_strategy_seed_dir(strategy_dir, session=session)
    log.info(
        "strategy memory seed import complete: imported=%d updated=%d unchanged=%d skipped=%d",
        result.imported,
        result.updated,
        result.unchanged,
        result.skipped,
    )


if __name__ == "__main__":
    main()
