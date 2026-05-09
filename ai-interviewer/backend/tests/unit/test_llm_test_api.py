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
