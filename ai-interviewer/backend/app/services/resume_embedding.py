"""OpenAI-compatible embedding wrapper for session anchor RAG."""
from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict
from typing import Any

import httpx

from app.core.settings import get_settings

log = logging.getLogger(__name__)

_MAX_BATCH_SIZE = 64
_QUERY_CACHE_TTL_SECONDS = 300.0
_QUERY_CACHE_MAX_ITEMS = 256

_embed_semaphore = threading.Semaphore(
    int(get_settings().resume_rag_embedding_concurrency or 4)
)
_query_cache: OrderedDict[tuple[str, str], tuple[list[float], float]] = OrderedDict()


class ResumeEmbeddingError(RuntimeError):
    """Raised when chunk embedding fails after the configured retries."""


def embed_chunks(
    texts: list[str],
    *,
    model: str | None = None,
    timeout_ms: int | None = None,
) -> list[list[float]]:
    """Batch-embed chunk texts and raise on failure."""

    if not texts:
        return []
    clean_texts = [str(text or "") for text in texts]
    selected_model = model or get_settings().resume_rag_embedding_model
    vectors: list[list[float]] = []
    for start in range(0, len(clean_texts), _MAX_BATCH_SIZE):
        batch = clean_texts[start : start + _MAX_BATCH_SIZE]
        vectors.extend(
            _embed_batch_with_retries(
                batch,
                model=selected_model,
                timeout_ms=timeout_ms,
            )
        )
    return vectors


def embed_query(
    text: str,
    *,
    model: str | None = None,
    timeout_ms: int | None = None,
    cache_key: str | None = None,
) -> list[float] | None:
    """Embed a single query string, returning ``None`` on timeout/failure."""

    selected_model = model or get_settings().resume_rag_embedding_model
    cache_token = str(cache_key or "").strip()
    if cache_token:
        cached = _cache_get((selected_model, cache_token))
        if cached is not None:
            return cached
    try:
        vectors = _embed_batch_with_retries(
            [str(text or "")],
            model=selected_model,
            timeout_ms=timeout_ms,
        )
    except ResumeEmbeddingError as e:
        log.warning("resume query embedding failed: %s", e)
        return None
    vector = vectors[0] if vectors else None
    if vector is not None and cache_token:
        _cache_put((selected_model, cache_token), vector)
    return vector


def current_embedding_model_version() -> str:
    """Return the canonical model version string written to anchor rows."""

    return f"{get_settings().resume_rag_embedding_model}@v1"


def _embed_batch_with_retries(
    texts: list[str],
    *,
    model: str,
    timeout_ms: int | None,
) -> list[list[float]]:
    settings = get_settings()
    max_retries = int(settings.resume_rag_embedding_max_retries or 0)
    backoff = float(settings.resume_rag_embedding_retry_backoff_seconds or 0.0)
    attempt = 0
    while True:
        try:
            return _embed_batch_once(texts, model=model, timeout_ms=timeout_ms)
        except Exception as e:
            retryable = _is_retryable_embedding_error(e)
            if not retryable or attempt >= max_retries:
                raise _to_embedding_error(e) from e
            time.sleep(backoff * (2**attempt))
            attempt += 1


def _embed_batch_once(
    texts: list[str],
    *,
    model: str,
    timeout_ms: int | None,
) -> list[list[float]]:
    settings = get_settings()
    timeout_seconds = (timeout_ms or settings.resume_rag_timeout_ms) / 1000.0
    payload = {
        "model": model,
        "input": texts,
    }
    headers = {
        "Content-Type": "application/json",
    }
    api_key = (
        settings.resume_rag_embedding_api_key
        or settings.openai_api_key
        or ""
    ).strip()
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    with _embed_semaphore:
        response = httpx.post(
            _embedding_url(settings.resume_rag_embedding_endpoint),
            json=payload,
            headers=headers,
            timeout=timeout_seconds,
        )
    response.raise_for_status()
    return _vectors_from_response(response.json(), expected_count=len(texts))


def _embedding_url(endpoint: str) -> str:
    return f"{str(endpoint or '').rstrip('/')}/embeddings"


def _vectors_from_response(body: dict[str, Any], *, expected_count: int) -> list[list[float]]:
    data = body.get("data")
    if not isinstance(data, list):
        raise ResumeEmbeddingError("embedding response missing data list")
    ordered = sorted(
        enumerate(data),
        key=lambda item: int(item[1].get("index", item[0]))
        if isinstance(item[1], dict)
        else item[0],
    )
    vectors: list[list[float]] = []
    for _, item in ordered:
        if not isinstance(item, dict) or not isinstance(item.get("embedding"), list):
            raise ResumeEmbeddingError("embedding response contains invalid item")
        vectors.append([float(value) for value in item["embedding"]])
    if len(vectors) != expected_count:
        raise ResumeEmbeddingError(
            f"embedding response count mismatch: expected {expected_count}, got {len(vectors)}"
        )
    return vectors


def _is_retryable_embedding_error(error: Exception) -> bool:
    if isinstance(error, httpx.HTTPStatusError):
        return error.response.status_code == 429
    return isinstance(error, httpx.TimeoutException | httpx.ConnectError)


def _to_embedding_error(error: Exception) -> ResumeEmbeddingError:
    if isinstance(error, ResumeEmbeddingError):
        return error
    if isinstance(error, httpx.HTTPStatusError):
        status_code = error.response.status_code
        return ResumeEmbeddingError(f"embedding request failed with HTTP {status_code}")
    return ResumeEmbeddingError(str(error) or error.__class__.__name__)


def _cache_get(key: tuple[str, str]) -> list[float] | None:
    now = time.monotonic()
    item = _query_cache.get(key)
    if item is None:
        return None
    vector, created_at = item
    if now - created_at > _QUERY_CACHE_TTL_SECONDS:
        _query_cache.pop(key, None)
        return None
    _query_cache.move_to_end(key)
    return list(vector)


def _cache_put(key: tuple[str, str], vector: list[float]) -> None:
    _query_cache[key] = (list(vector), time.monotonic())
    _query_cache.move_to_end(key)
    while len(_query_cache) > _QUERY_CACHE_MAX_ITEMS:
        _query_cache.popitem(last=False)
