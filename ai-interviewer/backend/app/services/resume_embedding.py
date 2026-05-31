"""OpenAI-compatible embedding wrapper for session anchor RAG."""
from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from hashlib import sha1
from typing import Any

import httpx

from app.core.settings import get_settings
from app.services.embedding_providers import (
    UnsupportedEmbeddingProviderError,
    browser_embedding_provider_spec,
    embedding_provider_from_endpoint,
    embedding_provider_spec,
)

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


@dataclass(frozen=True)
class EmbeddingConfig:
    provider: str
    endpoint: str
    model: str
    api_key: str
    dimensions: int
    max_batch_size: int = _MAX_BATCH_SIZE

    @property
    def model_version(self) -> str:
        provider = self.provider
        if provider == "openai_compatible":
            provider = f"openai_compatible:{sha1(self.endpoint.encode('utf-8')).hexdigest()[:10]}"
        return f"{provider}:{self.model}:{self.dimensions}@v1"

    def as_secret_config(self) -> dict[str, Any]:
        return {
            "embedding_override": {
                "provider": self.provider,
                "api_key": self.api_key,
                "model": self.model,
                "base_url": self.endpoint,
                "dimensions": self.dimensions,
            }
        }


def embed_chunks(
    texts: list[str],
    *,
    model: str | None = None,
    timeout_ms: int | None = None,
    embedding_override: dict[str, Any] | None = None,
) -> list[list[float]]:
    """Batch-embed chunk texts and raise on failure."""

    if not texts:
        return []
    clean_texts = [str(text or "") for text in texts]
    config = resolve_embedding_config(embedding_override)
    if model:
        config = EmbeddingConfig(
            provider=config.provider,
            endpoint=config.endpoint,
            model=model,
            api_key=config.api_key,
            dimensions=config.dimensions,
            max_batch_size=config.max_batch_size,
        )
    vectors: list[list[float]] = []
    batch_size = _effective_batch_size(config)
    for start in range(0, len(clean_texts), batch_size):
        batch = clean_texts[start : start + batch_size]
        vectors.extend(
            _embed_batch_with_retries(
                batch,
                config=config,
                timeout_ms=_embedding_timeout_ms(timeout_ms),
            )
        )
    return vectors


def embed_query(
    text: str,
    *,
    model: str | None = None,
    timeout_ms: int | None = None,
    cache_key: str | None = None,
    embedding_override: dict[str, Any] | None = None,
    raise_errors: bool = False,
) -> list[float] | None:
    """Embed a single query string, returning ``None`` on timeout/failure."""

    config = resolve_embedding_config(embedding_override)
    if model:
        config = EmbeddingConfig(
            provider=config.provider,
            endpoint=config.endpoint,
            model=model,
            api_key=config.api_key,
            dimensions=config.dimensions,
            max_batch_size=config.max_batch_size,
        )
    model_version = config.model_version
    cache_token = str(cache_key or "").strip()
    if cache_token:
        cached = _cache_get((model_version, cache_token))
        if cached is not None:
            return cached
    try:
        vectors = _embed_batch_with_retries(
            [str(text or "")],
            config=config,
            timeout_ms=_query_embedding_timeout_ms(timeout_ms),
            max_retries=0,
        )
    except ResumeEmbeddingError as e:
        if raise_errors:
            raise
        log.warning(
            "resume query embedding failed: %s",
            _redact_embedding_error(e, config),
        )
        return None
    vector = vectors[0] if vectors else None
    if vector is not None and cache_token:
        _cache_put((model_version, cache_token), vector)
    return vector


def current_embedding_model_version(
    embedding_override: dict[str, Any] | None = None,
) -> str:
    """Return the canonical model version string written to anchor rows."""

    return resolve_embedding_config(embedding_override).model_version


def resolve_embedding_config(
    embedding_override: dict[str, Any] | None = None,
) -> EmbeddingConfig:
    """Resolve per-session embedding config, falling back to server settings."""

    settings = get_settings()
    override = embedding_override or _runtime_embedding_override()
    expected_dim = int(settings.resume_rag_embedding_dimension or 1536)
    if isinstance(override, dict) and str(override.get("api_key") or "").strip():
        try:
            provider_spec = browser_embedding_provider_spec(
                str(override.get("provider") or "qwen")
            )
        except UnsupportedEmbeddingProviderError as e:
            raise ResumeEmbeddingError(str(e)) from e
        provider = provider_spec.id
        endpoint = str(
            override.get("base_url")
            or override.get("endpoint")
            or provider_spec.default_base_url
        ).strip()
        model = str(
            override.get("model") or provider_spec.default_model
        ).strip()
        dimensions = int(override.get("dimensions") or expected_dim)
        if dimensions != expected_dim:
            raise ResumeEmbeddingError(
                f"embedding dimension mismatch: expected {expected_dim}, got {dimensions}"
            )
        if dimensions not in provider_spec.supported_dimensions:
            supported = ", ".join(str(dim) for dim in sorted(provider_spec.supported_dimensions))
            raise ResumeEmbeddingError(
                f"embedding dimension unsupported for {provider}: {dimensions}; supported: {supported}"
            )
        if provider_spec.requires_base_url and not endpoint:
            raise ResumeEmbeddingError("embedding base_url required for openai_compatible")
        if not model:
            raise ResumeEmbeddingError("embedding model required")
        return EmbeddingConfig(
            provider=provider,
            endpoint=endpoint,
            model=model,
            api_key=str(override.get("api_key") or "").strip(),
            dimensions=dimensions,
            max_batch_size=provider_spec.max_batch_size,
        )

    endpoint = str(settings.resume_rag_embedding_endpoint or "").strip()
    model = str(settings.resume_rag_embedding_model or "").strip()
    api_key = (
        settings.resume_rag_embedding_api_key
        or settings.openai_api_key
        or ""
    ).strip()
    provider = embedding_provider_from_endpoint(endpoint)
    try:
        provider_spec = embedding_provider_spec(provider)
        max_batch_size = provider_spec.max_batch_size
    except UnsupportedEmbeddingProviderError:
        max_batch_size = _MAX_BATCH_SIZE
    return EmbeddingConfig(
        provider=provider,
        endpoint=endpoint,
        model=model,
        api_key=api_key,
        dimensions=expected_dim,
        max_batch_size=max_batch_size,
    )


def _effective_batch_size(config: EmbeddingConfig) -> int:
    try:
        return max(1, int(config.max_batch_size or _MAX_BATCH_SIZE))
    except (TypeError, ValueError):
        return _MAX_BATCH_SIZE


def _embedding_timeout_ms(timeout_ms: int | None) -> int:
    if timeout_ms is not None:
        return int(timeout_ms)
    settings = get_settings()
    return int(
        getattr(settings, "resume_rag_embedding_timeout_ms", None)
        or settings.resume_rag_timeout_ms
        or 10000
    )


def _query_embedding_timeout_ms(timeout_ms: int | None) -> int:
    if timeout_ms is not None:
        return int(timeout_ms)
    settings = get_settings()
    return int(
        getattr(settings, "resume_rag_query_embedding_timeout_ms", None)
        or settings.resume_rag_timeout_ms
        or 3000
    )


def _embed_batch_with_retries(
    texts: list[str],
    *,
    config: EmbeddingConfig,
    timeout_ms: int | None,
    max_retries: int | None = None,
) -> list[list[float]]:
    settings = get_settings()
    retry_limit = (
        int(settings.resume_rag_embedding_max_retries or 0)
        if max_retries is None
        else int(max_retries)
    )
    backoff = float(settings.resume_rag_embedding_retry_backoff_seconds or 0.0)
    attempt = 0
    while True:
        try:
            return _embed_batch_once(texts, config=config, timeout_ms=timeout_ms)
        except Exception as e:
            retryable = _is_retryable_embedding_error(e)
            if not retryable or attempt >= retry_limit:
                raise _to_embedding_error(e) from e
            time.sleep(backoff * (2**attempt))
            attempt += 1


def _embed_batch_once(
    texts: list[str],
    *,
    config: EmbeddingConfig,
    timeout_ms: int | None,
) -> list[list[float]]:
    settings = get_settings()
    timeout_seconds = (timeout_ms or settings.resume_rag_timeout_ms) / 1000.0
    payload = {
        "model": config.model,
        "input": texts,
        "dimensions": config.dimensions,
    }
    headers = {
        "Content-Type": "application/json",
    }
    if config.api_key:
        headers["Authorization"] = f"Bearer {config.api_key}"

    with _embed_semaphore:
        response = httpx.post(
            _embedding_url(config.endpoint),
            json=payload,
            headers=headers,
            timeout=timeout_seconds,
        )
    response.raise_for_status()
    return _vectors_from_response(response.json(), expected_count=len(texts))


def _embedding_url(endpoint: str) -> str:
    return f"{str(endpoint or '').rstrip('/')}/embeddings"


def _runtime_embedding_override() -> dict[str, Any] | None:
    try:
        from app.services.session_manager import get_llm_override

        llm_config = get_llm_override()
    except Exception:
        return None
    if not isinstance(llm_config, dict):
        return None
    override = llm_config.get("embedding_override")
    return override if isinstance(override, dict) else None


def _redact_embedding_error(error: Exception, config: EmbeddingConfig) -> str:
    try:
        from app.engine.agents.llm_client import redact_llm_secrets

        return redact_llm_secrets(str(error), config.as_secret_config())
    except Exception:
        return str(error)


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
