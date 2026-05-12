from __future__ import annotations

import math
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from app.engine.rag import retriever, vectorstore
from app.engine.rag.ingestion import _iter_documents, ingest_folder


class _FakeCollection:
    def __init__(self) -> None:
        self.rows: dict[str, tuple[str, dict[str, Any], list[float]]] = {}

    def upsert(
        self,
        *,
        ids: list[str],
        documents: list[str],
        metadatas: list[dict[str, Any]],
        embeddings: list[list[float]],
    ) -> None:
        for doc_id, text, meta, embedding in zip(
            ids, documents, metadatas, embeddings, strict=True
        ):
            self.rows[doc_id] = (text, meta, embedding)

    def query(self, *, query_embeddings: list[list[float]], n_results: int):
        query = query_embeddings[0]

        def cosine(vec: list[float]) -> float:
            denom = math.sqrt(sum(v * v for v in query)) * math.sqrt(
                sum(v * v for v in vec)
            )
            if denom == 0:
                return 0.0
            return sum(a * b for a, b in zip(query, vec, strict=True)) / denom

        ranked = sorted(
            self.rows.values(),
            key=lambda row: cosine(row[2]),
            reverse=True,
        )[:n_results]
        return {
            "documents": [[text for text, _, _ in ranked]],
            "metadatas": [[meta for _, meta, _ in ranked]],
            "distances": [[1.0 - cosine(embedding) for _, _, embedding in ranked]],
        }

    def count(self) -> int:
        return len(self.rows)


def _install_fake_chroma(monkeypatch) -> _FakeCollection:
    collection = _FakeCollection()

    class FakeClient:
        def get_or_create_collection(self, _name: str) -> _FakeCollection:
            return collection

    monkeypatch.setitem(
        sys.modules,
        "chromadb",
        types.SimpleNamespace(HttpClient=lambda host, port: FakeClient()),
    )
    monkeypatch.setattr(
        vectorstore,
        "get_settings",
        lambda: SimpleNamespace(
            chroma_host="localhost",
            chroma_port=8100,
            chroma_collection="interviewer_kb",
            embedding_provider="stub",
            embedding_model="text-embedding-3-small",
            openai_api_key=None,
        ),
    )
    return collection


def test_stub_embeddings_persist_seeded_docs_in_chroma(monkeypatch):
    _install_fake_chroma(monkeypatch)

    seed_process_store = vectorstore.ChromaVectorStore()
    seed_process_store.add(
        [
            "Senior Backend Engineer question bank covering Python services, "
            "system design, distributed databases, and idempotency."
        ],
        [{"source": "tech_questions/backend_systems.md", "chunk": 0}],
    )

    uvicorn_process_store = vectorstore.ChromaVectorStore()
    docs = uvicorn_process_store.similarity_search(
        "Senior Backend Engineer technical_depth python system_design databases",
        k=2,
    )

    assert uvicorn_process_store.count() == 1
    assert docs
    assert docs[0].metadata["source"] == "tech_questions/backend_systems.md"


def test_non_rag_runtime_catalogs_are_not_ingested(tmp_path: Path):
    (tmp_path / "interview_waiting_tips.json").write_text(
        '{"tips": [{"text": "runtime waiting copy"}]}',
        encoding="utf-8",
    )
    (tmp_path / "job_templates.json").write_text(
        '{"templates": [{"title": "runtime setup catalog"}]}',
        encoding="utf-8",
    )
    (tmp_path / "interview_directions.json").write_text(
        '{"directions": [{"id": "backend"}]}',
        encoding="utf-8",
    )

    sources = {meta["source"] for _, meta in _iter_documents(tmp_path)}

    assert "interview_waiting_tips.json" not in sources
    assert "job_templates.json" not in sources
    assert "interview_directions.json" in sources


def test_seeded_default_senior_backend_query_retrieves_relevant_knowledge(monkeypatch):
    _install_fake_chroma(monkeypatch)
    knowledge_root = Path(__file__).resolve().parents[2] / "knowledge"

    seed_process_store = vectorstore.ChromaVectorStore()
    monkeypatch.setattr(vectorstore, "get_vectorstore", lambda: seed_process_store)
    assert ingest_folder(knowledge_root) > 0

    uvicorn_process_store = vectorstore.ChromaVectorStore()
    monkeypatch.setattr(retriever, "get_vectorstore", lambda: uvicorn_process_store)

    result = retriever.retrieve_for_question(
        job_spec={
            "title": "Senior Backend Engineer",
            "required_skills": ["python", "system_design", "databases"],
        },
        dimension="technical_depth",
        top_k=5,
    )

    sources = {doc.metadata["source"] for doc in result.docs}
    assert result.docs
    assert sources & {
        "tech_questions/backend_systems.md",
        "sample_resumes/alex_chen_backend.md",
        "tech_questions/system_design.md",
    }
