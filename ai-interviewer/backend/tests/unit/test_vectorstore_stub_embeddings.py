from __future__ import annotations

import math
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

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
    assert "interview_directions.json" not in sources


def test_non_rag_question_strategy_and_sample_resume_dirs_are_not_ingested(
    tmp_path: Path,
):
    excluded_files = [
        tmp_path / "tech_questions" / "backend.md",
        tmp_path / "business_questions" / "product.md",
        tmp_path / "behavioral_questions" / "communication.md",
        tmp_path / "sample_resumes" / "alex.md",
        tmp_path / "strategy" / "pattern.md",
        tmp_path / "strategy" / ".dream_state.json",
        tmp_path / "skills" / "backend_reliability.md",
    ]
    for path in excluded_files:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("legacy question or sample resume content", encoding="utf-8")
    support = tmp_path / "rag_support" / "backend_reliability.md"
    support.parent.mkdir(parents=True, exist_ok=True)
    support.write_text("supporting skill about backend reliability", encoding="utf-8")

    sources = {meta["source"] for _, meta in _iter_documents(tmp_path)}

    assert sources == {"rag_support/backend_reliability.md"}


def test_seeded_default_knowledge_has_no_rag_documents(monkeypatch):
    _install_fake_chroma(monkeypatch)
    knowledge_root = Path(__file__).resolve().parents[2] / "knowledge"

    seed_process_store = vectorstore.ChromaVectorStore()
    monkeypatch.setattr(vectorstore, "get_vectorstore", lambda: seed_process_store)
    assert ingest_folder(knowledge_root) == 0

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

    assert result.docs == []
    assert result.as_prompt_block == "(no relevant knowledge retrieved)"


def test_prod_chroma_unavailable_raises_instead_of_falling_back(monkeypatch):
    class FailingClient:
        def __init__(self, *, host: str, port: int) -> None:
            raise RuntimeError("chroma down")

    monkeypatch.setitem(
        sys.modules,
        "chromadb",
        types.SimpleNamespace(HttpClient=lambda host, port: FailingClient(host=host, port=port)),
    )
    monkeypatch.setattr(
        vectorstore,
        "get_settings",
        lambda: SimpleNamespace(
            app_env="prod",
            chroma_host="localhost",
            chroma_port=8100,
            chroma_collection="interviewer_kb",
            embedding_provider="stub",
            embedding_model="text-embedding-3-small",
            openai_api_key=None,
        ),
    )

    with pytest.raises(RuntimeError, match="Chroma unavailable in production"):
        vectorstore.ChromaVectorStore()


class TestRuntimeChromaFailover:
    """Verify graceful degradation when Chroma goes down after init."""

    def _make_store_with_failing_ops(self, monkeypatch, *, fail_on: str):
        """Build a ChromaVectorStore whose Chroma backend fails at runtime."""
        collection = _FakeCollection()
        original_upsert = collection.upsert
        original_query = collection.query
        original_count = collection.count

        def exploding_upsert(**kw):
            if fail_on in ("upsert", "all"):
                raise ConnectionError("chroma connection lost")
            return original_upsert(**kw)

        def exploding_query(**kw):
            if fail_on in ("query", "all"):
                raise ConnectionError("chroma connection lost")
            return original_query(**kw)

        def exploding_count():
            if fail_on in ("count", "all"):
                raise ConnectionError("chroma connection lost")
            return original_count()

        collection.upsert = exploding_upsert
        collection.query = exploding_query
        collection.count = exploding_count

        class FakeClient:
            def get_or_create_collection(self, _name: str):
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
                app_env="dev",
                chroma_host="localhost",
                chroma_port=8100,
                chroma_collection="interviewer_kb",
                embedding_provider="stub",
                embedding_model="text-embedding-3-small",
                openai_api_key=None,
            ),
        )
        store = vectorstore.ChromaVectorStore()
        assert store.is_remote
        assert not store.is_degraded
        return store

    def test_add_falls_back_on_runtime_failure(self, monkeypatch):
        store = self._make_store_with_failing_ops(monkeypatch, fail_on="upsert")
        store.add(["test doc"], [{"source": "test.md", "chunk": 0}])
        assert store.is_degraded
        assert store._fallback.count() == 1

    def test_similarity_search_falls_back_on_runtime_failure(self, monkeypatch):
        store = self._make_store_with_failing_ops(monkeypatch, fail_on="query")
        store._fallback.add(["fallback doc about python"], [{"source": "fb.md"}])
        results = store.similarity_search("python", k=1)
        assert store.is_degraded
        assert len(results) == 1
        assert results[0].text == "fallback doc about python"

    def test_count_falls_back_on_runtime_failure(self, monkeypatch):
        store = self._make_store_with_failing_ops(monkeypatch, fail_on="count")
        store._fallback.add(["doc1"], [{"source": "a.md"}])
        assert store.count() == 1
        assert store.is_degraded

    def test_degraded_flag_set_only_once(self, monkeypatch):
        store = self._make_store_with_failing_ops(monkeypatch, fail_on="all")
        store.add(["doc1"], [{"source": "a.md"}])
        assert store.is_degraded
        store.similarity_search("test", k=1)
        store.count()
        assert store.is_degraded


def test_retriever_filters_old_non_rag_sources(monkeypatch):
    class StoreWithStaleSources:
        def similarity_search(self, query: str, k: int):
            return [
                vectorstore.RetrievedDoc(
                    text="stale playbook",
                    metadata={"source": "skills/backend_reliability.md"},
                    score=0.99,
                ),
                vectorstore.RetrievedDoc(
                    text="stale strategy",
                    metadata={"source": "strategy/pattern.md"},
                    score=0.98,
                ),
                vectorstore.RetrievedDoc(
                    text="real support knowledge",
                    metadata={"source": "rag_support/backend_reliability.md"},
                    score=0.5,
                ),
            ]

    monkeypatch.setattr(retriever, "get_vectorstore", lambda: StoreWithStaleSources())

    result = retriever.retrieve_for_question(
        job_spec={"title": "Backend Engineer", "required_skills": ["reliability"]},
        dimension="problem_solving",
        top_k=2,
    )

    assert [doc.metadata["source"] for doc in result.docs] == [
        "rag_support/backend_reliability.md"
    ]
