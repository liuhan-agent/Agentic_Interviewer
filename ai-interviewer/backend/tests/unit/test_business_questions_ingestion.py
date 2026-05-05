from __future__ import annotations

from collections import Counter
from pathlib import Path

from app.engine.rag.ingestion import _iter_documents


def test_business_questions_are_ingested_from_knowledge_tree() -> None:
    knowledge_root = Path(__file__).resolve().parents[2] / "knowledge"
    expected_sources = {
        path.relative_to(knowledge_root).as_posix()
        for path in (knowledge_root / "business_questions").glob("*.md")
    }

    assert len(expected_sources) == 7

    chunks_by_source = Counter(
        meta["source"]
        for _, meta in _iter_documents(knowledge_root)
        if meta["source_type"] == "business_questions"
    )

    assert set(chunks_by_source) == expected_sources
    assert all(count >= 1 for count in chunks_by_source.values())
