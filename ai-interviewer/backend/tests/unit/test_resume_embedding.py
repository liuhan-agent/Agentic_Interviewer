from __future__ import annotations

from typing import Any

import httpx
import pytest

from app.core.settings import get_settings
from app.services import resume_embedding
from app.services.resume_embedding import (
    ResumeEmbeddingError,
    current_embedding_model_version,
    embed_chunks,
    embed_query,
)


class _MockHTTP:
    def __init__(self) -> None:
        self._responses: list[Any] = []
        self.call_count = 0
        self.payloads: list[dict[str, Any]] = []
        self.timeouts: list[float | None] = []

    def add_post(self, path: str, response: Any) -> None:
        assert path == "/embeddings"
        if isinstance(response, list):
            self._responses.extend(response)
        else:
            self._responses.append(response)

    def set_timeout(self) -> None:
        self._responses.append(httpx.TimeoutException("timed out"))

    def __call__(self, url: str, **kwargs: Any) -> httpx.Response:
        assert url.endswith("/embeddings")
        self.call_count += 1
        payload = dict(kwargs.get("json") or {})
        self.payloads.append(payload)
        self.timeouts.append(kwargs.get("timeout"))
        if not self._responses:
            raise AssertionError("no mock response configured")
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        if callable(response):
            response = response(payload)
        return response


@pytest.fixture
def mock_http(monkeypatch) -> _MockHTTP:
    mock = _MockHTTP()
    monkeypatch.setattr(resume_embedding.httpx, "post", mock)
    monkeypatch.setattr(resume_embedding.time, "sleep", lambda _seconds: None)
    resume_embedding._query_cache.clear()
    return mock


def _ok_response(count: int) -> httpx.Response:
    dim = int(get_settings().resume_rag_embedding_dimension or 1536)
    return httpx.Response(
        200,
        json={
            "data": [
                {"index": index, "embedding": [float(index + 1)] * dim}
                for index in range(count)
            ]
        },
        request=httpx.Request("POST", "https://example.test/embeddings"),
    )


def _status_response(status_code: int) -> httpx.Response:
    return httpx.Response(
        status_code,
        json={"error": {"message": f"status {status_code}"}},
        request=httpx.Request("POST", "https://example.test/embeddings"),
    )


def test_embed_chunks_batches_under_64(mock_http: _MockHTTP) -> None:
    mock_http.add_post("/embeddings", lambda req: _ok_response(len(req["input"])))
    mock_http.add_post("/embeddings", lambda req: _ok_response(len(req["input"])))
    mock_http.add_post("/embeddings", lambda req: _ok_response(len(req["input"])))

    vectors = embed_chunks(["x"] * 150)

    assert len(vectors) == 150
    assert [len(payload["input"]) for payload in mock_http.payloads] == [64, 64, 22]
    assert all(
        payload["dimensions"] == int(get_settings().resume_rag_embedding_dimension or 1536)
        for payload in mock_http.payloads
    )
    assert mock_http.call_count == 3


def test_embed_chunks_uses_qwen_embedding_override(mock_http: _MockHTTP) -> None:
    mock_http.add_post("/embeddings", lambda req: _ok_response(len(req["input"])))

    vectors = embed_chunks(
        ["Redis Lua atomic deduction"],
        embedding_override={
            "provider": "qwen",
            "api_key": "sk-qwen-embedding",
            "model": "text-embedding-v4",
            "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "dimensions": 1536,
        },
    )

    assert len(vectors) == 1
    assert mock_http.payloads[0]["model"] == "text-embedding-v4"
    assert mock_http.payloads[0]["dimensions"] == 1536


def test_embed_chunks_uses_qwen_provider_batch_limit(mock_http: _MockHTTP) -> None:
    for _ in range(3):
        mock_http.add_post("/embeddings", lambda req: _ok_response(len(req["input"])))

    vectors = embed_chunks(
        ["Redis Lua atomic deduction"] * 24,
        embedding_override={
            "provider": "qwen",
            "api_key": "sk-qwen-embedding",
            "model": "text-embedding-v4",
            "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "dimensions": 1536,
        },
    )

    assert len(vectors) == 24
    assert [len(payload["input"]) for payload in mock_http.payloads] == [10, 10, 4]


def test_embed_chunks_uses_longer_vectorization_timeout(
    mock_http: _MockHTTP,
) -> None:
    mock_http.add_post("/embeddings", lambda req: _ok_response(len(req["input"])))

    embed_chunks(["Redis Lua atomic deduction"])

    assert mock_http.timeouts == [pytest.approx(10.0)]


def test_embed_query_uses_query_embedding_timeout(mock_http: _MockHTTP) -> None:
    mock_http.add_post("/embeddings", lambda req: _ok_response(len(req["input"])))

    embed_query("Redis Lua atomic deduction")

    assert mock_http.timeouts == [pytest.approx(3.0)]


def test_embedding_provider_registry_allows_qwen_byok_only() -> None:
    from app.services.embedding_providers import (
        embedding_provider_spec,
        supported_embedding_override_provider_ids,
    )

    assert supported_embedding_override_provider_ids() == {"qwen", "dashscope"}
    qwen = embedding_provider_spec("qwen")
    assert qwen.default_model == "text-embedding-v4"
    assert qwen.default_base_url == "https://dashscope.aliyuncs.com/compatible-mode/v1"
    assert qwen.supported_dimensions == frozenset({1536})
    assert qwen.max_batch_size == 10


def test_openai_embedding_override_is_reserved_for_future_provider_rollout() -> None:
    with pytest.raises(ResumeEmbeddingError, match="unsupported embedding provider: openai"):
        current_embedding_model_version(
            {
                "provider": "openai",
                "api_key": "sk-openai-embedding",
                "model": "text-embedding-3-small",
                "base_url": "https://api.openai.com/v1",
                "dimensions": 1536,
            }
        )


def test_current_embedding_model_version_includes_provider_model_and_dimension() -> None:
    assert (
        current_embedding_model_version(
            {
                "provider": "qwen",
                "api_key": "sk-qwen-embedding",
                "model": "text-embedding-v4",
                "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                "dimensions": 1536,
            }
        )
        == "qwen:text-embedding-v4:1536@v1"
    )


def test_embed_query_swallows_timeout(mock_http: _MockHTTP) -> None:
    mock_http.set_timeout()

    assert embed_query("cache consistency") is None


def test_embed_query_cache_avoids_second_call(mock_http: _MockHTTP) -> None:
    mock_http.add_post("/embeddings", lambda req: _ok_response(len(req["input"])))

    v1 = embed_query("Redis high concurrency", cache_key="seed1")
    v2 = embed_query("Redis high concurrency", cache_key="seed1")

    assert v1 == v2
    assert mock_http.call_count == 1


def test_embed_query_cache_isolated_by_embedding_version(mock_http: _MockHTTP) -> None:
    mock_http.add_post("/embeddings", lambda req: _ok_response(len(req["input"])))
    mock_http.add_post("/embeddings", lambda req: _ok_response(len(req["input"])))

    override_a = {
        "provider": "qwen",
        "api_key": "sk-qwen-embedding",
        "model": "text-embedding-v4",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "dimensions": 1536,
    }
    override_b = {
        **override_a,
        "model": "text-embedding-v4-alt",
    }

    embed_query("Redis high concurrency", cache_key="seed1", embedding_override=override_a)
    embed_query("Redis high concurrency", cache_key="seed1", embedding_override=override_b)

    assert mock_http.call_count == 2


def test_embed_chunks_retries_on_429(mock_http: _MockHTTP) -> None:
    mock_http.add_post("/embeddings", [_status_response(429), _ok_response(1)])

    vectors = embed_chunks(["x"])

    assert len(vectors) == 1
    assert mock_http.call_count == 2


def test_embed_chunks_raises_after_retries_exhausted(mock_http: _MockHTTP) -> None:
    max_retries = int(get_settings().resume_rag_embedding_max_retries)
    mock_http.add_post(
        "/embeddings",
        [_status_response(429)] * (max_retries + 1),
    )

    with pytest.raises(ResumeEmbeddingError):
        embed_chunks(["x"])

    assert mock_http.call_count == max_retries + 1


def test_embed_chunks_does_not_retry_non_429_http_error(
    mock_http: _MockHTTP,
) -> None:
    mock_http.add_post("/embeddings", _status_response(400))

    with pytest.raises(ResumeEmbeddingError):
        embed_chunks(["x"])

    assert mock_http.call_count == 1


def test_embed_chunks_semaphore_matches_settings_concurrency() -> None:
    assert resume_embedding._embed_semaphore._value == int(
        get_settings().resume_rag_embedding_concurrency
    )


def test_current_embedding_model_version_uses_configured_model() -> None:
    assert current_embedding_model_version().endswith(
        f":{get_settings().resume_rag_embedding_dimension}@v1"
    )
