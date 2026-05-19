"""Chroma-backed vector store with offline stub embeddings.

When Chroma is available, both OpenAI and stub embeddings write to the
same remote collection. If Chroma itself is unavailable, the store falls
back to a process-local dict so the rest of the pipeline can still run.
"""
from __future__ import annotations

import hashlib
import math
import os
import re
import threading
from dataclasses import dataclass, field
from typing import Any

from app.core.logging import get_logger
from app.core.settings import get_settings

log = get_logger(__name__)

_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9]+")
_STUB_EMBEDDING_DIMENSIONS = 256


class _StubEmbeddings:
    """Deterministic local embeddings for offline Chroma-backed dev runs."""

    def _tokens(self, text: str) -> list[str]:
        normalized = re.sub(r"[_-]+", " ", text or "")
        return [token.lower() for token in _TOKEN_RE.findall(normalized)]

    def _embed(self, text: str) -> list[float]:
        vec = [0.0] * _STUB_EMBEDDING_DIMENSIONS
        for token in self._tokens(text):
            digest = hashlib.sha1(token.encode("utf-8"), usedforsecurity=False).digest()
            idx = int.from_bytes(digest[:4], "big") % _STUB_EMBEDDING_DIMENSIONS
            vec[idx] += 1.0
        norm = math.sqrt(sum(v * v for v in vec))
        if not norm:
            return vec
        return [v / norm for v in vec]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)


_STUB_EMBEDDINGS = _StubEmbeddings()


@dataclass
class RetrievedDoc:
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)
    score: float = 0.0


def _stable_doc_id(text: str, metadata: dict[str, Any] | None) -> str:
    """Return a deterministic Chroma ID for ``(metadata, text)``.

    Python's builtin ``hash`` is randomised per interpreter (PEP 456
    hash randomisation), so using ``hash(text)`` as the id - as the
    previous implementation did - produced different ids across
    processes or restarts. Re-ingesting the same knowledge folder then
    inserted *new* rows instead of upserting, steadily polluting the
    collection with duplicate chunks and skewing retrieval rankings.

    We use a SHA-1 over ``source||chunk||text`` so:

    - Same metadata + same text  -> same id (true upsert, idempotent).
    - Same text under a different source path still gets a distinct
      id, which matches the semantics of "one chunk per origin".
    - No cryptographic guarantees are needed; SHA-1 is a stable,
      widely-available digest with negligible collision risk for a
      demo-scale KB.
    """
    meta = metadata or {}
    source = str(meta.get("source", "unknown"))
    chunk = str(meta.get("chunk", 0))
    payload = f"{source}|{chunk}|{text}".encode()
    digest = hashlib.sha1(payload, usedforsecurity=False).hexdigest()
    return f"doc-{digest[:24]}"


def _ensure_localhost_proxy_bypass() -> None:
    """Keep local Docker services off Windows/system HTTP proxies."""
    local_hosts = ["localhost", "127.0.0.1", "::1"]
    for key in ("NO_PROXY", "no_proxy"):
        existing = os.environ.get(key, "")
        current = [part.strip() for part in existing.split(",") if part.strip()]
        merged = current + [host for host in local_hosts if host not in current]
        os.environ[key] = ",".join(merged)


class InMemoryVectorStore:
    """Trivial bag-of-docs store for stub/dev runs.

    The similarity function is a BM25-lite bag-of-words overlap. It is
    not production grade but it is deterministic, offline, and good
    enough to demonstrate retrieval wiring in the demo script.
    """

    def __init__(self) -> None:
        self._docs: dict[str, RetrievedDoc] = {}

    def add(self, texts: list[str], metadatas: list[dict[str, Any]] | None = None) -> None:
        metadatas = metadatas or [{} for _ in texts]
        for text, meta in zip(texts, metadatas, strict=True):
            doc_id = _stable_doc_id(text, meta)
            self._docs[doc_id] = RetrievedDoc(text=text, metadata=meta)

    def similarity_search(self, query: str, k: int = 5) -> list[RetrievedDoc]:
        q_tokens = set(_STUB_EMBEDDINGS._tokens(query))
        scored: list[tuple[float, RetrievedDoc]] = []
        for doc in self._docs.values():
            d_tokens = set(_STUB_EMBEDDINGS._tokens(doc.text))
            overlap = len(q_tokens & d_tokens)
            if overlap == 0:
                continue
            score = overlap / (len(d_tokens) ** 0.5 or 1.0)
            scored.append((score, RetrievedDoc(text=doc.text, metadata=doc.metadata, score=score)))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [d for _, d in scored[:k]]

    def count(self) -> int:
        return len(self._docs)


class ChromaVectorStore:
    """Thin wrapper around a remote Chroma collection.

    Embeddings are fetched via ``langchain-openai`` when available. On
    any failure we log and fall back to :class:`InMemoryVectorStore`
    to keep the demo usable.
    """

    def __init__(self) -> None:
        settings = get_settings()
        self._fallback = InMemoryVectorStore()
        self._degraded = False
        self._client = None
        self._collection = None
        self._embeddings = None
        try:
            import chromadb

            _ensure_localhost_proxy_bypass()
            self._client = chromadb.HttpClient(host=settings.chroma_host, port=settings.chroma_port)
            self._collection = self._client.get_or_create_collection(settings.chroma_collection)
        except Exception as e:  # pragma: no cover
            if getattr(settings, "app_env", "dev") == "prod":
                raise RuntimeError("Chroma unavailable in production") from e
            log.warning("Chroma unavailable (%s); falling back to in-memory store", e)

        if self._collection is not None and settings.embedding_provider == "openai":
            try:
                from langchain_openai import OpenAIEmbeddings

                self._embeddings = OpenAIEmbeddings(
                    model=settings.embedding_model,
                    openai_api_key=settings.openai_api_key,
                )
            except Exception as e:  # pragma: no cover
                if getattr(settings, "app_env", "dev") == "prod":
                    raise RuntimeError("OpenAI embeddings unavailable in production") from e
                log.warning("OpenAI embeddings unavailable (%s); using in-memory fallback", e)
                self._collection = None
        elif self._collection is not None and settings.embedding_provider == "stub":
            self._embeddings = _STUB_EMBEDDINGS

    @property
    def is_remote(self) -> bool:
        return self._collection is not None and self._embeddings is not None

    @property
    def is_degraded(self) -> bool:
        """True when remote Chroma was available at init but failed at runtime."""
        return self._degraded

    def _enter_degraded(self, operation: str, exc: Exception) -> None:
        if not self._degraded:
            log.warning(
                "Chroma runtime failure during %s (%s); "
                "switching to in-memory fallback for this process",
                operation, exc,
            )
            self._degraded = True

    def add(self, texts: list[str], metadatas: list[dict[str, Any]] | None = None) -> None:
        if not self.is_remote:
            self._fallback.add(texts, metadatas)
            return
        metadatas = metadatas or [{} for _ in texts]
        ids = [_stable_doc_id(t, m) for t, m in zip(texts, metadatas, strict=True)]
        try:
            vectors = self._embeddings.embed_documents(texts)
            self._collection.upsert(ids=ids, documents=texts, metadatas=metadatas, embeddings=vectors)
        except Exception as exc:
            self._enter_degraded("add", exc)
            self._fallback.add(texts, metadatas)

    def similarity_search(self, query: str, k: int = 5) -> list[RetrievedDoc]:
        if not self.is_remote:
            return self._fallback.similarity_search(query, k=k)
        try:
            vec = self._embeddings.embed_query(query)
            res = self._collection.query(query_embeddings=[vec], n_results=k)
        except Exception as exc:
            self._enter_degraded("similarity_search", exc)
            return self._fallback.similarity_search(query, k=k)
        docs: list[RetrievedDoc] = []
        for text, meta, dist in zip(
            res.get("documents", [[]])[0],
            res.get("metadatas", [[]])[0] or [{}] * k,
            res.get("distances", [[]])[0] or [0.0] * k,
            strict=False,
        ):
            docs.append(RetrievedDoc(text=text, metadata=meta or {}, score=1.0 - float(dist)))
        return docs

    def count(self) -> int:
        if not self.is_remote:
            return self._fallback.count()
        try:
            return self._collection.count()
        except Exception as exc:
            self._enter_degraded("count", exc)
            return self._fallback.count()


_singleton: ChromaVectorStore | None = None
_singleton_lock = threading.Lock()


def get_vectorstore() -> ChromaVectorStore:
    global _singleton
    if _singleton is None:
        with _singleton_lock:
            if _singleton is None:
                _singleton = ChromaVectorStore()
    return _singleton
