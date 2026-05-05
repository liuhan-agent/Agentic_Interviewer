"""Load the ``knowledge/`` folder into the vector store.

Text is split with a simple fixed-size window; the Plan earmarks
LangChain's ``RecursiveCharacterTextSplitter`` for Phase 4 once we
have real multi-page PDFs. For MVP seed files we only need the naive
splitter.
"""
from __future__ import annotations

from pathlib import Path

from app.core.logging import get_logger

from .vectorstore import get_vectorstore

log = get_logger(__name__)

CHUNK_SIZE = 600
CHUNK_OVERLAP = 80


def _split(text: str) -> list[str]:
    text = text.strip()
    if not text:
        return []
    if len(text) <= CHUNK_SIZE:
        return [text]
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + CHUNK_SIZE, len(text))
        chunks.append(text[start:end])
        if end == len(text):
            break
        start = end - CHUNK_OVERLAP
    return chunks


def _iter_documents(root: Path) -> list[tuple[str, dict]]:
    docs: list[tuple[str, dict]] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in {".md", ".txt", ".json"}:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            log.warning("Skipping %s: %s", path, e)
            continue
        rel = path.relative_to(root).as_posix()
        if rel == "job_templates.json":
            continue
        source_type = rel.split("/", 1)[0] if "/" in rel else "misc"
        for idx, chunk in enumerate(_split(text)):
            docs.append(
                (
                    chunk,
                    {"source": rel, "chunk": idx, "source_type": source_type},
                )
            )
    return docs


def ingest_folder(root: Path) -> int:
    """Walk ``root`` and insert every chunk into the store. Returns count."""
    store = get_vectorstore()
    items = _iter_documents(root)
    if not items:
        log.info("No ingestible files under %s", root)
        return 0
    texts = [t for t, _ in items]
    metas = [m for _, m in items]
    store.add(texts, metas)
    log.info("Ingested %d chunks from %s", len(texts), root)
    return len(texts)
