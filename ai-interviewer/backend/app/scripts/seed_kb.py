"""Seed the vector store from ``backend/knowledge``.

Idempotent: running it again on the same corpus just re-upserts the
same IDs. Safe to wire into CI for integration tests.

Usage::

    python -m app.scripts.seed_kb
"""
from __future__ import annotations

from pathlib import Path

from app.core.logging import get_logger
from app.core.settings import get_settings
from app.engine.rag.ingestion import ingest_folder

log = get_logger(__name__)


def main() -> None:
    settings = get_settings()
    root = Path(settings.knowledge_dir)
    if not root.exists():
        log.error("knowledge dir does not exist: %s", root)
        return
    count = ingest_folder(root)
    log.info("seeded %d chunks from %s", count, root)


if __name__ == "__main__":
    main()
