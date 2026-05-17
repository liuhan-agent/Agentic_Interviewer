from __future__ import annotations

from pathlib import Path

from app.engine.rag.ingestion import _iter_documents


def test_legacy_question_sources_are_not_ingested_from_knowledge_tree() -> None:
    knowledge_root = Path(__file__).resolve().parents[2] / "knowledge"
    sources = {meta["source"] for _, meta in _iter_documents(knowledge_root)}

    assert any((knowledge_root / "business_questions").glob("*.md"))
    assert any((knowledge_root / "tech_questions").glob("*.md"))
    assert any((knowledge_root / "behavioral_questions").glob("*.md"))
    assert any((knowledge_root / "sample_resumes").glob("*.md"))
    assert not any(source.startswith("business_questions/") for source in sources)
    assert not any(source.startswith("tech_questions/") for source in sources)
    assert not any(source.startswith("behavioral_questions/") for source in sources)
    assert not any(source.startswith("sample_resumes/") for source in sources)
