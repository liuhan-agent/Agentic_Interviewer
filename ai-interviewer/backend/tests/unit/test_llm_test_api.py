"""Tests for the user-facing ``POST /api/v1/llm/test`` endpoint."""
from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.engine.agents.llm_client import LLMFatal, LLMRateLimit, LLMTransient


@pytest.fixture()
def client() -> TestClient:
    from app.api.v1 import llm as llm_api

    app = FastAPI()
    app.include_router(llm_api.router)
    return TestClient(app)


def test_llm_test_endpoint_returns_latency_on_success(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.v1 import llm as llm_api

    captured: dict[str, Any] = {}

    def fake_invoke(messages, *, model, temperature, max_tokens, json_mode, override):
        captured.update(
            {
                "messages": messages,
                "model": model,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "json_mode": json_mode,
                "override": override,
            }
        )
        return "pong"

    monkeypatch.setattr(llm_api, "_invoke_provider", fake_invoke)

    resp = client.post(
        "/api/v1/llm/test",
        json={
            "provider": "kimi",
            "api_key": "secret-key",
            "model": "kimi-k2.6",
        },
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["provider"] == "kimi"
    assert body["model"] == "kimi-k2.6"
    assert isinstance(body["latency_ms"], int)
    assert body["latency_ms"] >= 0
    assert body["message"] == "pong"
    assert "secret-key" not in resp.text
    assert captured["temperature"] == 0.0
    assert captured["max_tokens"] == 8
    assert captured["json_mode"] is False
    assert captured["override"]["api_key"] == "secret-key"


def test_llm_test_endpoint_checks_qwen_asr_route(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.v1 import llm as llm_api

    captured: dict[str, Any] = {}

    class FakeProvider:
        async def check_asr_session(self, route):
            captured["route"] = route
            return "session.updated"

    monkeypatch.setattr(llm_api, "provider_for", lambda route: FakeProvider())

    resp = client.post(
        "/api/v1/llm/test",
        json={
            "kind": "asr",
            "provider": "qwen",
            "api_key": "secret-key",
            "model": "qwen3-asr-flash-realtime",
            "base_url": "wss://dashscope.aliyuncs.com/api-ws/v1/realtime",
        },
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["provider"] == "qwen"
    assert body["model"] == "qwen3-asr-flash-realtime"
    assert body["message"] == "session.updated"
    assert captured["route"].api_key == "secret-key"
    assert "secret-key" not in resp.text


def test_llm_test_endpoint_checks_qwen_tts_route(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.v1 import llm as llm_api

    captured: dict[str, Any] = {}

    class FakeProvider:
        async def synth(self, route, text, *, connect_factory=None):
            captured["route"] = route
            captured["text"] = text
            yield b"audio"

    monkeypatch.setattr(llm_api, "provider_for", lambda route: FakeProvider())

    resp = client.post(
        "/api/v1/llm/test",
        json={
            "kind": "tts",
            "provider": "qwen",
            "api_key": "secret-key",
            "model": "qwen3-tts-flash-realtime",
            "voice": "Cherry",
            "base_url": "wss://dashscope.aliyuncs.com/api-ws/v1/realtime",
        },
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["provider"] == "qwen"
    assert body["model"] == "qwen3-tts-flash-realtime"
    assert body["message"] == "audio"
    assert captured["route"].voice == "Cherry"
    assert captured["text"]
    assert "secret-key" not in resp.text


def test_llm_test_endpoint_checks_embedding_route(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.v1 import llm as llm_api

    captured: dict[str, Any] = {}

    def fake_embed_query(text: str, **kwargs: Any) -> list[float]:
        captured["text"] = text
        captured["kwargs"] = kwargs
        return [0.1] * 1536

    monkeypatch.setattr(llm_api, "embed_query", fake_embed_query, raising=False)

    resp = client.post(
        "/api/v1/llm/test",
        json={
            "kind": "embedding",
            "provider": "qwen",
            "api_key": "secret-key",
            "model": "text-embedding-v4",
            "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "dimensions": 1536,
        },
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["provider"] == "qwen"
    assert body["model"] == "text-embedding-v4"
    assert body["message"] == "embedding"
    assert captured["text"] == "ping"
    assert captured["kwargs"]["embedding_override"]["api_key"] == "secret-key"
    assert captured["kwargs"]["embedding_override"]["dimensions"] == 1536
    assert "secret-key" not in resp.text


def test_llm_test_endpoint_rejects_embedding_dimension_mismatch(
    client: TestClient,
) -> None:
    resp = client.post(
        "/api/v1/llm/test",
        json={
            "kind": "embedding",
            "provider": "qwen",
            "api_key": "secret-key",
            "model": "text-embedding-v4",
            "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "dimensions": 1024,
        },
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert body["error_kind"] == "misconfig"
    assert "secret-key" not in resp.text


def test_llm_test_endpoint_rejects_unsupported_embedding_provider_before_call(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.v1 import llm as llm_api

    def fail_embed_query(text: str, **kwargs: Any) -> list[float]:
        raise AssertionError("embedding provider should be rejected before call")

    monkeypatch.setattr(llm_api, "embed_query", fail_embed_query, raising=False)

    resp = client.post(
        "/api/v1/llm/test",
        json={
            "kind": "embedding",
            "provider": "openai",
            "api_key": "secret-key",
            "model": "text-embedding-3-small",
            "dimensions": 1536,
        },
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert body["error_kind"] == "misconfig"
    assert body["error"] == "unsupported embedding provider: openai"
    assert "secret-key" not in resp.text


def test_llm_test_endpoint_redacts_embedding_provider_errors(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.v1 import llm as llm_api
    from app.services.resume_embedding import ResumeEmbeddingError

    def fake_embed_query(text: str, **kwargs: Any) -> list[float]:
        raise ResumeEmbeddingError("provider echoed secret-key with HTTP 401")

    monkeypatch.setattr(llm_api, "embed_query", fake_embed_query, raising=False)

    resp = client.post(
        "/api/v1/llm/test",
        json={
            "kind": "embedding",
            "provider": "qwen",
            "api_key": "secret-key",
            "model": "text-embedding-v4",
            "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "dimensions": 1536,
        },
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert body["error_kind"] == "auth"
    assert body["error"] == "provider echoed [redacted-api-key] with HTTP 401"
    assert "secret-key" not in resp.text


def test_llm_test_endpoint_redacts_voice_provider_errors(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.v1 import llm as llm_api

    class FakeProvider:
        async def check_asr_session(self, route):
            raise RuntimeError("provider echoed secret-key")

    monkeypatch.setattr(llm_api, "provider_for", lambda route: FakeProvider())

    resp = client.post(
        "/api/v1/llm/test",
        json={
            "kind": "asr",
            "provider": "qwen",
            "api_key": "secret-key",
            "model": "qwen3-asr-flash-realtime",
        },
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert body["error_kind"] == "unknown"
    assert body["error"] == "provider echoed [redacted-api-key]"
    assert "secret-key" not in resp.text


def test_llm_test_endpoint_classifies_voice_protocol_errors(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.v1 import llm as llm_api

    class FakeProvider:
        async def synth(self, route, text, *, connect_factory=None):
            raise RuntimeError("server rejected websocket realtime session")
            yield b"unreachable"

    monkeypatch.setattr(llm_api, "provider_for", lambda route: FakeProvider())

    resp = client.post(
        "/api/v1/llm/test",
        json={
            "kind": "tts",
            "provider": "qwen",
            "api_key": "secret-key",
            "model": "qwen3-tts-flash-realtime",
            "voice": "Cherry",
        },
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert body["error_kind"] == "network"
    assert body["error"] == "server rejected websocket realtime session"


@pytest.mark.parametrize(
    ("exc", "kind"),
    [
        (LLMFatal("invalid api key"), "auth"),
        (LLMFatal("insufficient_quota: billing hard limit reached"), "quota"),
        (LLMRateLimit("429 too many requests"), "rate_limit"),
        (LLMTransient("request timeout"), "timeout"),
        (LLMTransient("connection reset by peer"), "network"),
        (
            ImportError(
                "Using SOCKS proxy, but the 'socksio' package is not installed."
            ),
            "network",
        ),
        (LLMFatal("unsupported provider: nope"), "misconfig"),
    ],
)
def test_llm_test_endpoint_returns_error_kind_for_provider_failures(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    exc: Exception,
    kind: str,
) -> None:
    from app.api.v1 import llm as llm_api

    def fake_invoke(*args, **kwargs):
        raise exc

    monkeypatch.setattr(llm_api, "_invoke_provider", fake_invoke)

    resp = client.post(
        "/api/v1/llm/test",
        json={
            "provider": "mistral",
            "api_key": "secret-key",
            "model": "mistral-small-latest",
        },
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert body["provider"] == "mistral"
    assert body["error_kind"] == kind
    assert body["error"] == str(exc)
    assert "secret-key" not in resp.text


def test_llm_test_endpoint_requires_base_url_for_custom_provider(
    client: TestClient,
) -> None:
    resp = client.post(
        "/api/v1/llm/test",
        json={
            "provider": "openai_compatible",
            "api_key": "secret-key",
            "model": "custom-model",
        },
    )

    assert resp.status_code == 422
    assert "base_url" in resp.text
    body = resp.json()
    assert body["detail"]["error_kind"] == "misconfig"
    assert body["detail"]["code"] == "llm_base_url_required"
    assert "secret-key" not in resp.text


def test_llm_test_endpoint_rejects_private_base_url(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.v1 import llm as llm_api

    def fake_invoke(*args, **kwargs):
        raise AssertionError("unsafe base_url should be rejected before provider call")

    monkeypatch.setattr(llm_api, "_invoke_provider", fake_invoke)

    resp = client.post(
        "/api/v1/llm/test",
        json={
            "provider": "openai_compatible",
            "api_key": "secret-key",
            "model": "custom-model",
            "base_url": "http://127.0.0.1:11434/v1",
        },
    )

    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert detail["error_kind"] == "misconfig"
    assert detail["code"] == "llm_base_url_invalid"
    assert "base_url" in resp.text
    assert "secret-key" not in resp.text


@pytest.mark.parametrize(
    "provider",
    ["openai", "anthropic", "deepseek", "qwen", "zhipu", "mistral"],
)
def test_llm_test_endpoint_rejects_private_base_url_for_every_provider(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    provider: str,
) -> None:
    from app.api.v1 import llm as llm_api

    def fake_invoke(*args, **kwargs):
        raise AssertionError("unsafe base_url should be rejected before provider call")

    monkeypatch.setattr(llm_api, "_invoke_provider", fake_invoke)

    resp = client.post(
        "/api/v1/llm/test",
        json={
            "provider": provider,
            "api_key": "secret-key",
            "model": "test-model",
            "base_url": "http://127.0.0.1:11434/v1",
        },
    )

    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert detail["error_kind"] == "misconfig"
    assert detail["code"] == "llm_base_url_invalid"
    assert "base_url" in resp.text
    assert "secret-key" not in resp.text


def test_llm_test_endpoint_redacts_key_from_provider_error(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.v1 import llm as llm_api

    def fake_invoke(*args, **kwargs):
        raise LLMFatal("provider echoed secret-key in an auth error")

    monkeypatch.setattr(llm_api, "_invoke_provider", fake_invoke)

    resp = client.post(
        "/api/v1/llm/test",
        json={
            "provider": "qwen",
            "api_key": "secret-key",
            "model": "qwen3.6-flash",
        },
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert body["error"] == "provider echoed [redacted-api-key] in an auth error"
    assert "secret-key" not in resp.text


def test_llm_test_endpoint_rate_limits_by_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.v1 import llm as llm_api
    from app.core import settings as settings_mod
    from app.core.rate_limit import clear_rate_limits

    monkeypatch.setenv("LLM_TEST_RATE_LIMIT_PER_MINUTE", "1")
    settings_mod.get_settings.cache_clear()
    clear_rate_limits()

    def fake_invoke(*args, **kwargs):
        return "pong"

    monkeypatch.setattr(llm_api, "_invoke_provider", fake_invoke)
    app = FastAPI()
    app.include_router(llm_api.router)
    test_client = TestClient(app)
    payload = {"provider": "kimi", "api_key": "secret-key", "model": "kimi-k2.6"}

    assert test_client.post("/api/v1/llm/test", json=payload).status_code == 200
    resp = test_client.post("/api/v1/llm/test", json=payload)

    assert resp.status_code == 429
    assert resp.json()["detail"]["code"] == "rate_limit_exceeded"
    settings_mod.get_settings.cache_clear()
    clear_rate_limits()
