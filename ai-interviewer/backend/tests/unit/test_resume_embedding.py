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
    assert mock_http.call_count == 3


def test_embed_query_swallows_timeout(mock_http: _MockHTTP) -> None:
    mock_http.set_timeout()

    assert embed_query("cache consistency") is None


def test_embed_query_cache_avoids_second_call(mock_http: _MockHTTP) -> None:
    mock_http.add_post("/embeddings", lambda req: _ok_response(len(req["input"])))

    v1 = embed_query("Redis high concurrency", cache_key="seed1")
    v2 = embed_query("Redis high concurrency", cache_key="seed1")

    assert v1 == v2
    assert mock_http.call_count == 1


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
    assert current_embedding_model_version() == (
        f"{get_settings().resume_rag_embedding_model}@v1"
    )
