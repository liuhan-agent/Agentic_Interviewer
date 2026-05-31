"""Tests for per-agent model routing via ``llm_model_per_agent``.

These tests target the pure resolver :func:`resolve_model` and the
``call_chat`` wiring that forwards the routing decision to the
provider dispatcher. All tests avoid real provider SDK calls by
monkey-patching ``_invoke_provider``.
"""
from __future__ import annotations

import sys
from types import SimpleNamespace
from typing import Any

import pytest

from app.core.settings import Settings
from app.engine.agents import llm_client
from app.engine.agents.llm_client import ChatMessage, LLMFatal, call_chat, resolve_model


class _StubSettings:
    """Minimal settings double for :func:`resolve_model` unit tests."""

    def __init__(
        self,
        *,
        llm_model: str = "default-model",
        llm_model_per_agent: dict[str, str] | None = None,
    ) -> None:
        self.llm_model = llm_model
        self.llm_model_per_agent = llm_model_per_agent or {}


# ---------------------------------------------------------------------------
# resolve_model
# ---------------------------------------------------------------------------


def test_resolve_model_explicit_override_wins() -> None:
    s = _StubSettings(
        llm_model="global",
        llm_model_per_agent={"evaluator": "per-agent"},
    )
    assert (
        resolve_model(
            explicit_model="explicit",
            agent_role="evaluator",
            settings=s,
        )
        == "explicit"
    )


def test_resolve_model_per_agent_map_used_when_no_explicit() -> None:
    s = _StubSettings(
        llm_model="global",
        llm_model_per_agent={"evaluator": "eval-model"},
    )
    assert (
        resolve_model(
            explicit_model=None,
            agent_role="evaluator",
            settings=s,
        )
        == "eval-model"
    )


def test_resolve_model_falls_back_to_global_when_role_missing() -> None:
    s = _StubSettings(
        llm_model="global",
        llm_model_per_agent={"evaluator": "eval-model"},
    )
    assert (
        resolve_model(
            explicit_model=None,
            agent_role="guard",
            settings=s,
        )
        == "global"
    )


def test_resolve_model_no_role_no_override_returns_global() -> None:
    s = _StubSettings(llm_model="global")
    assert (
        resolve_model(explicit_model=None, agent_role=None, settings=s)
        == "global"
    )


def test_resolve_model_empty_string_in_map_is_ignored() -> None:
    """Empty-string values should not mask the global fallback."""
    s = _StubSettings(
        llm_model="global",
        llm_model_per_agent={"evaluator": ""},
    )
    assert (
        resolve_model(
            explicit_model=None,
            agent_role="evaluator",
            settings=s,
        )
        == "global"
    )


# ---------------------------------------------------------------------------
# call_chat wiring
# ---------------------------------------------------------------------------


def _patch_invoke(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Replace ``_invoke_provider`` with a captor; return the capture dict."""
    captured: dict[str, Any] = {}

    def fake_invoke(
        messages: list[ChatMessage],
        *,
        model: str,
        temperature: float,
        max_tokens: int,
        json_mode: bool,
        override: dict[str, Any] | None = None,
        request_timeout: float | None = None,
        provider_max_retries: int | None = None,
    ) -> str:
        # ``override`` is the BYOK per-session hook; these tests
        # exercise routing, not BYOK, so we capture it for optional
        # assertions but otherwise ignore it.
        captured["model"] = model
        captured["messages"] = messages
        captured["temperature"] = temperature
        captured["max_tokens"] = max_tokens
        captured["json_mode"] = json_mode
        captured["override"] = override
        captured["request_timeout"] = request_timeout
        captured["provider_max_retries"] = provider_max_retries
        return "ok"

    monkeypatch.setattr(llm_client, "_invoke_provider", fake_invoke)
    return captured


def _force_non_stub(monkeypatch: pytest.MonkeyPatch, overrides: dict[str, Any]) -> None:
    """Return a settings object whose ``use_stub_llm`` is False."""

    class _Cfg:
        use_stub_llm = False
        llm_provider = overrides.get("llm_provider", "qwen")
        llm_model = overrides.get("llm_model", "global-model")
        llm_model_per_agent = overrides.get("llm_model_per_agent", {})
        llm_temperature = 0.1
        llm_max_tokens = 100
        llm_max_retries = 0
        llm_retry_backoff_seconds = 0.0
        llm_retry_backoff_cap_seconds = 0.0
        llm_request_timeout_seconds = 25.0
        generator_llm_timeout_seconds = overrides.get(
            "generator_llm_timeout_seconds",
            45.0,
        )
        evaluator_llm_timeout_seconds = overrides.get(
            "evaluator_llm_timeout_seconds",
            45.0,
        )
        verifier_llm_timeout_seconds = overrides.get(
            "verifier_llm_timeout_seconds",
            30.0,
        )
        deepseek_base_url = "https://api.deepseek.com/v1"

    monkeypatch.setattr(llm_client, "get_settings", lambda: _Cfg())


def test_call_chat_uses_per_agent_model_when_role_provided(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _force_non_stub(
        monkeypatch,
        {"llm_model_per_agent": {"evaluator": "claude-sonnet-4-5"}},
    )
    captured = _patch_invoke(monkeypatch)

    call_chat(
        [ChatMessage("user", "ping")],
        agent_role="evaluator",
    )

    assert captured["model"] == "claude-sonnet-4-5"


def test_call_chat_falls_back_to_global_when_role_unmapped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _force_non_stub(
        monkeypatch,
        {"llm_model_per_agent": {"evaluator": "claude-sonnet-4-5"}},
    )
    captured = _patch_invoke(monkeypatch)

    call_chat(
        [ChatMessage("user", "ping")],
        agent_role="guard",
    )

    assert captured["model"] == "global-model"


def test_call_chat_explicit_model_overrides_role_map(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _force_non_stub(
        monkeypatch,
        {"llm_model_per_agent": {"evaluator": "claude-sonnet-4-5"}},
    )
    captured = _patch_invoke(monkeypatch)

    call_chat(
        [ChatMessage("user", "ping")],
        agent_role="evaluator",
        model="explicit-model",
    )

    assert captured["model"] == "explicit-model"


def test_call_chat_without_role_preserves_legacy_behaviour(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _force_non_stub(
        monkeypatch,
        {"llm_model_per_agent": {"evaluator": "should-not-be-used"}},
    )
    captured = _patch_invoke(monkeypatch)

    call_chat([ChatMessage("user", "ping")])

    assert captured["model"] == "global-model"


def test_call_chat_uses_byok_role_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _force_non_stub(monkeypatch, {})
    captured = _patch_invoke(monkeypatch)

    import app.services.session_manager as session_manager

    monkeypatch.setattr(
        session_manager,
        "get_llm_override",
        lambda: {
            "provider": "qwen",
            "api_key": "default-key",
            "model": "qwen3.6-flash",
            "role_overrides": {
                "evaluator": {
                    "provider": "kimi",
                    "model": "kimi-k2.6",
                }
            },
        },
    )

    call_chat(
        [ChatMessage("user", "ping")],
        agent_role="evaluator",
    )

    assert captured["model"] == "kimi-k2.6"
    assert captured["override"]["provider"] == "kimi"
    assert captured["override"]["api_key"] == "default-key"
    assert "role_overrides" not in captured["override"]


def test_call_chat_uses_resume_parser_role_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _force_non_stub(monkeypatch, {})
    captured = _patch_invoke(monkeypatch)

    import app.services.session_manager as session_manager

    monkeypatch.setattr(
        session_manager,
        "get_llm_override",
        lambda: {
            "provider": "qwen",
            "api_key": "default-key",
            "model": "qwen3.6-flash",
            "role_overrides": {
                "resume_parser": {
                    "provider": "qwen",
                    "model": "qwen3.6-plus",
                }
            },
        },
    )

    call_chat(
        [ChatMessage("user", "ping")],
        agent_role="resume_parser",
    )

    assert captured["model"] == "qwen3.6-plus"
    assert captured["override"]["provider"] == "qwen"
    assert captured["override"]["api_key"] == "default-key"
    assert "role_overrides" not in captured["override"]


def test_call_chat_logs_resume_parser_diagnostics_without_api_key(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _force_non_stub(monkeypatch, {})
    _patch_invoke(monkeypatch)

    import app.services.session_manager as session_manager

    monkeypatch.setattr(
        session_manager,
        "get_llm_override",
        lambda: {
            "provider": "qwen",
            "api_key": "secret-key",
            "model": "qwen3.6-plus",
            "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        },
    )

    with caplog.at_level("INFO", logger="app.engine.agents.llm_client"):
        call_chat(
            [ChatMessage("user", "ping" * 20)],
            agent_role="resume_parser",
            json_mode=True,
            request_timeout=12.0,
            max_retries=0,
            provider_max_retries=0,
        )

    log_text = "\n".join(record.getMessage() for record in caplog.records)
    assert "llm_call_start" in log_text
    assert "llm_call_success" in log_text
    assert "role=resume_parser" in log_text
    assert "provider=qwen" in log_text
    assert "model=qwen3.6-plus" in log_text
    assert "base_host=dashscope.aliyuncs.com" in log_text
    assert "secret-key" not in log_text


def test_call_chat_logs_interview_role_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _force_non_stub(monkeypatch, {"llm_provider": "qwen", "llm_model": "qwen3.6-flash"})
    _patch_invoke(monkeypatch)

    import app.services.session_manager as session_manager

    monkeypatch.setattr(session_manager, "get_llm_override", lambda: None)

    with caplog.at_level("INFO", logger="app.engine.agents.llm_client"):
        result = call_chat(
            [ChatMessage("user", "请继续追问这个项目")],
            agent_role="generator",
            max_retries=0,
            provider_max_retries=0,
        )

    assert result == "ok"
    log_text = "\n".join(record.getMessage() for record in caplog.records)
    assert "llm_call_start" in log_text
    assert "llm_call_success" in log_text
    assert "role=generator" in log_text
    assert "provider=qwen" in log_text
    assert "model=qwen3.6-flash" in log_text


def test_call_chat_uses_generator_timeout_for_question_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _force_non_stub(
        monkeypatch,
        {
            "llm_provider": "qwen",
            "llm_model": "qwen3.6-flash",
            "generator_llm_timeout_seconds": 45.0,
        },
    )
    captured = _patch_invoke(monkeypatch)

    call_chat(
        [ChatMessage("user", "generate first question")],
        agent_role="generator",
    )

    assert captured["request_timeout"] == 45.0


def test_call_chat_explicit_timeout_overrides_generator_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _force_non_stub(
        monkeypatch,
        {
            "llm_provider": "qwen",
            "llm_model": "qwen3.6-flash",
            "generator_llm_timeout_seconds": 45.0,
        },
    )
    captured = _patch_invoke(monkeypatch)

    call_chat(
        [ChatMessage("user", "generate first question")],
        agent_role="generator",
        request_timeout=12.0,
    )

    assert captured["request_timeout"] == 12.0


def test_call_chat_uses_evaluator_timeout_for_answer_scoring(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _force_non_stub(
        monkeypatch,
        {
            "llm_provider": "qwen",
            "llm_model": "qwen3.6-plus",
            "evaluator_llm_timeout_seconds": 45.0,
        },
    )
    captured = _patch_invoke(monkeypatch)

    call_chat(
        [ChatMessage("user", "score candidate answer")],
        agent_role="evaluator",
    )

    assert captured["request_timeout"] == 45.0


def test_call_chat_explicit_timeout_overrides_evaluator_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _force_non_stub(
        monkeypatch,
        {
            "llm_provider": "qwen",
            "llm_model": "qwen3.6-plus",
            "evaluator_llm_timeout_seconds": 45.0,
        },
    )
    captured = _patch_invoke(monkeypatch)

    call_chat(
        [ChatMessage("user", "score candidate answer")],
        agent_role="evaluator",
        request_timeout=12.0,
    )

    assert captured["request_timeout"] == 12.0


def test_call_chat_uses_verifier_timeout_for_answer_review(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _force_non_stub(
        monkeypatch,
        {
            "llm_provider": "qwen",
            "llm_model": "qwen3.6-flash",
            "verifier_llm_timeout_seconds": 30.0,
        },
    )
    captured = _patch_invoke(monkeypatch)

    call_chat(
        [ChatMessage("user", "review borderline answer")],
        agent_role="verifier",
    )

    assert captured["request_timeout"] == 30.0


def test_call_chat_explicit_timeout_overrides_verifier_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _force_non_stub(
        monkeypatch,
        {
            "llm_provider": "qwen",
            "llm_model": "qwen3.6-flash",
            "verifier_llm_timeout_seconds": 30.0,
        },
    )
    captured = _patch_invoke(monkeypatch)

    call_chat(
        [ChatMessage("user", "review borderline answer")],
        agent_role="verifier",
        request_timeout=12.0,
    )

    assert captured["request_timeout"] == 12.0


def test_default_llm_budget_is_interactive_bounded() -> None:
    settings = Settings(_env_file=None)

    assert settings.llm_request_timeout_seconds <= 20.0
    assert settings.generator_llm_timeout_seconds >= 40.0
    assert settings.evaluator_llm_timeout_seconds >= 40.0
    assert settings.resume_parser_llm_timeout_seconds == 120.0
    assert settings.resume_parse_job_llm_timeout_seconds == 300.0
    assert settings.verifier_llm_timeout_seconds == 30.0
    assert settings.llm_max_retries <= 1
    assert settings.llm_retry_backoff_cap_seconds <= 2.0


def test_placeholder_openai_key_keeps_stub_mode_enabled() -> None:
    settings = Settings(_env_file=None, openai_api_key="sk-replace-me")

    assert settings.use_stub_llm is True


def test_call_chat_unmapped_role_uses_default_byok_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _force_non_stub(monkeypatch, {})
    captured = _patch_invoke(monkeypatch)

    import app.services.session_manager as session_manager

    monkeypatch.setattr(
        session_manager,
        "get_llm_override",
        lambda: {
            "provider": "qwen",
            "api_key": "default-key",
            "model": "qwen3.6-flash",
            "role_overrides": {
                "evaluator": {
                    "provider": "qwen",
                    "model": "qwen3.6-plus",
                }
            },
        },
    )

    call_chat(
        [ChatMessage("user", "ping")],
        agent_role="guard",
    )

    assert captured["model"] == "qwen3.6-flash"
    assert captured["override"]["provider"] == "qwen"
    assert captured["override"]["api_key"] == "default-key"
    assert "role_overrides" not in captured["override"]


def test_call_chat_uses_role_override_without_default_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _force_non_stub(monkeypatch, {})
    captured = _patch_invoke(monkeypatch)

    import app.services.session_manager as session_manager

    monkeypatch.setattr(
        session_manager,
        "get_llm_override",
        lambda: {
            "role_overrides": {
                "verifier": {
                    "provider": "kimi",
                    "api_key": "kimi-key",
                    "model": "kimi-k2.6",
                }
            },
        },
    )

    call_chat(
        [ChatMessage("user", "ping")],
        agent_role="verifier",
    )

    assert captured["model"] == "kimi-k2.6"
    assert captured["override"] == {
        "provider": "kimi",
        "api_key": "kimi-key",
        "model": "kimi-k2.6",
    }


def test_call_chat_ignores_default_override_without_key_for_unmapped_role(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _force_non_stub(monkeypatch, {"llm_model": "server-model"})
    captured = _patch_invoke(monkeypatch)

    import app.services.session_manager as session_manager

    monkeypatch.setattr(
        session_manager,
        "get_llm_override",
        lambda: {
            "provider": "qwen",
            "model": "qwen3.6-flash",
            "role_overrides": {
                "verifier": {
                    "provider": "kimi",
                    "api_key": "kimi-key",
                    "model": "kimi-k2.6",
                }
            },
        },
    )

    call_chat(
        [ChatMessage("user", "ping")],
        agent_role="guard",
    )

    assert captured["model"] == "server-model"
    assert captured["override"] is None


# ---------------------------------------------------------------------------
# OpenAI-compatible provider routing
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("provider", "expected_base_url"),
    [
        ("kimi", "https://api.moonshot.cn/v1"),
        ("moonshot", "https://api.moonshot.cn/v1"),
        ("qwen", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
        ("dashscope", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
        ("zhipu", "https://open.bigmodel.cn/api/paas/v4/"),
        ("mistral", "https://api.mistral.ai/v1"),
        ("xiaomimimo", "https://api.xiaomimimo.com/v1"),
    ],
)
def test_invoke_provider_routes_named_openai_compatible_providers(
    monkeypatch: pytest.MonkeyPatch,
    provider: str,
    expected_base_url: str,
) -> None:
    captured: dict[str, Any] = {}

    def fake_openai_compatible(
        messages: list[ChatMessage],
        model: str,
        temperature: float,
        max_tokens: int,
        json_mode: bool,
        *,
        base_url: str,
        override: dict[str, Any] | None = None,
        request_timeout: float | None = None,
        provider_max_retries: int | None = None,
    ) -> str:
        captured.update(
            {
                "messages": messages,
                "model": model,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "json_mode": json_mode,
                "base_url": base_url,
                "override": override,
                "request_timeout": request_timeout,
                "provider_max_retries": provider_max_retries,
            }
        )
        return "ok"

    monkeypatch.setattr(
        llm_client, "_call_openai_compatible", fake_openai_compatible
    )
    monkeypatch.setattr(
        llm_client.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(None, None, None, None, ("93.184.216.34", 443))],
    )

    result = llm_client._invoke_provider(
        [ChatMessage("user", "ping")],
        model="test-model",
        temperature=0.2,
        max_tokens=12,
        json_mode=True,
        override={"provider": provider, "api_key": "secret"},
    )

    assert result == "ok"
    assert captured["base_url"] == expected_base_url
    assert captured["override"] == {"provider": provider, "api_key": "secret"}


def test_invoke_provider_uses_custom_openai_compatible_base_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_openai_compatible(
        messages: list[ChatMessage],
        model: str,
        temperature: float,
        max_tokens: int,
        json_mode: bool,
        *,
        base_url: str,
        override: dict[str, Any] | None = None,
        request_timeout: float | None = None,
        provider_max_retries: int | None = None,
    ) -> str:
        captured["base_url"] = base_url
        captured["override"] = override
        captured["request_timeout"] = request_timeout
        captured["provider_max_retries"] = provider_max_retries
        return "ok"

    monkeypatch.setattr(
        llm_client, "_call_openai_compatible", fake_openai_compatible
    )
    monkeypatch.setattr(
        llm_client.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(None, None, None, None, ("93.184.216.34", 443))],
    )

    result = llm_client._invoke_provider(
        [ChatMessage("user", "ping")],
        model="custom-model",
        temperature=0,
        max_tokens=8,
        json_mode=False,
        override={
            "provider": "openai_compatible",
            "api_key": "secret",
            "base_url": "https://does-not-resolve.invalid/v1",
        },
    )

    assert result == "ok"
    assert captured["base_url"] == "https://does-not-resolve.invalid/v1"
    assert captured["override"]["api_key"] == "secret"


@pytest.mark.parametrize(
    "base_url",
    [
        "https://api.deepseek.com/v1",
        "https://api.moonshot.cn/v1",
        "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "https://open.bigmodel.cn/api/paas/v4/",
        "https://api.mistral.ai/v1",
        "https://api.xiaomimimo.com/v1",
    ],
)
def test_validate_llm_base_url_allows_known_provider_fake_ip_dns(
    monkeypatch: pytest.MonkeyPatch,
    base_url: str,
) -> None:
    monkeypatch.setattr(
        llm_client.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(None, None, None, None, ("198.18.0.147", 443))],
    )

    llm_client.validate_llm_base_url(base_url)


def test_validate_llm_base_url_rejects_unknown_host_fake_ip_dns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        llm_client.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(None, None, None, None, ("198.18.0.147", 443))],
    )

    with pytest.raises(llm_client.LLMFatal, match="disallowed address"):
        llm_client.validate_llm_base_url("https://example.com/v1")


def test_invoke_provider_rejects_custom_openai_compatible_without_base_url() -> None:
    with pytest.raises(LLMFatal, match="requires a base_url"):
        llm_client._invoke_provider(
            [ChatMessage("user", "ping")],
            model="custom-model",
            temperature=0,
            max_tokens=8,
            json_mode=False,
            override={"provider": "openai_compatible", "api_key": "secret"},
        )


def test_invoke_provider_rejects_private_openai_compatible_base_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_openai_compatible(*args, **kwargs):
        raise AssertionError("unsafe base_url should not reach the provider adapter")

    monkeypatch.setattr(
        llm_client, "_call_openai_compatible", fake_openai_compatible
    )

    with pytest.raises(LLMFatal, match="base_url"):
        llm_client._invoke_provider(
            [ChatMessage("user", "ping")],
            model="custom-model",
            temperature=0,
            max_tokens=8,
            json_mode=False,
            override={
                "provider": "openai_compatible",
                "api_key": "secret",
                "base_url": "http://169.254.169.254/latest/meta-data",
            },
        )


@pytest.mark.parametrize("provider", ["qwen", "zhipu", "mistral"])
def test_invoke_provider_rejects_private_base_url_for_named_providers(
    monkeypatch: pytest.MonkeyPatch,
    provider: str,
) -> None:
    def fake_openai_compatible(*args, **kwargs):
        raise AssertionError("unsafe base_url should not reach the provider adapter")

    monkeypatch.setattr(
        llm_client, "_call_openai_compatible", fake_openai_compatible
    )

    with pytest.raises(LLMFatal, match="base_url"):
        llm_client._invoke_provider(
            [ChatMessage("user", "ping")],
            model="custom-model",
            temperature=0,
            max_tokens=8,
            json_mode=False,
            override={
                "provider": provider,
                "api_key": "secret",
                "base_url": "http://127.0.0.1:11434/v1",
            },
        )


@pytest.mark.parametrize("provider", ["openai", "anthropic", "deepseek"])
def test_invoke_provider_rejects_private_base_url_for_native_providers(
    monkeypatch: pytest.MonkeyPatch,
    provider: str,
) -> None:
    monkeypatch.setattr(
        llm_client,
        "_call_openai",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("unsafe base_url should not reach OpenAI")
        ),
    )
    monkeypatch.setattr(
        llm_client,
        "_call_anthropic",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("unsafe base_url should not reach Anthropic")
        ),
    )
    monkeypatch.setattr(
        llm_client,
        "_call_deepseek",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("unsafe base_url should not reach DeepSeek")
        ),
    )

    with pytest.raises(LLMFatal, match="base_url"):
        llm_client._invoke_provider(
            [ChatMessage("user", "ping")],
            model="custom-model",
            temperature=0,
            max_tokens=8,
            json_mode=False,
            override={
                "provider": provider,
                "api_key": "secret",
                "base_url": "http://169.254.169.254/latest/meta-data",
            },
        )


def test_call_openai_compatible_sets_base_url_and_json_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    class _FakeCompletions:
        def create(self, **kwargs: Any) -> Any:
            captured["kwargs"] = kwargs
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="pong"))]
            )

    class _FakeOpenAI:
        def __init__(
            self,
            *,
            api_key: str,
            base_url: str | None = None,
            timeout: float | None = None,
            max_retries: int | None = None,
        ) -> None:
            captured["api_key"] = api_key
            captured["base_url"] = base_url
            captured["timeout"] = timeout
            captured["max_retries"] = max_retries
            self.chat = SimpleNamespace(completions=_FakeCompletions())

    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=_FakeOpenAI))

    content, usage = llm_client._call_openai_compatible(
        [ChatMessage("user", "ping")],
        "test-model",
        0.1,
        8,
        True,
        base_url="https://llm.example.test/v1",
        override={"api_key": "secret"},
    )

    assert content == "pong"
    # Fake response carries no ``usage`` block, so the helper falls back
    # to the char-based estimate. We just check the shape, not the
    # exact token count, so the test stays robust if the estimator is
    # tuned later.
    assert usage["usage_estimated"] is True
    assert "prompt_tokens" in usage and "completion_tokens" in usage
    assert captured["api_key"] == "secret"
    assert captured["base_url"] == "https://llm.example.test/v1"
    assert captured["timeout"] == 20.0
    assert captured["max_retries"] == 0
    assert captured["kwargs"]["response_format"] == {"type": "json_object"}


def test_call_openai_honors_override_base_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    class _FakeCompletions:
        def create(self, **kwargs: Any) -> Any:
            captured["kwargs"] = kwargs
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="pong"))]
            )

    class _FakeOpenAI:
        def __init__(
            self,
            *,
            api_key: str,
            base_url: str | None = None,
            timeout: float | None = None,
            max_retries: int | None = None,
        ) -> None:
            captured["api_key"] = api_key
            captured["base_url"] = base_url
            captured["timeout"] = timeout
            captured["max_retries"] = max_retries
            self.chat = SimpleNamespace(completions=_FakeCompletions())

    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=_FakeOpenAI))

    content, usage = llm_client._call_openai(
        [ChatMessage("user", "ping")],
        "test-model",
        0.1,
        8,
        True,
        override={
            "api_key": "secret",
            "base_url": "https://openai-proxy.example.test/v1",
        },
    )

    assert content == "pong"
    assert usage["usage_estimated"] is True
    assert captured["api_key"] == "secret"
    assert captured["base_url"] == "https://openai-proxy.example.test/v1"
    assert captured["timeout"] == 20.0
    assert captured["max_retries"] == 0
    assert captured["kwargs"]["response_format"] == {"type": "json_object"}


def test_call_anthropic_honors_override_base_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    class _FakeAnthropic:
        def __init__(self, *, api_key: str, base_url: str | None = None) -> None:
            captured["api_key"] = api_key
            captured["base_url"] = base_url
            self.messages = self

        def create(self, **kwargs: Any) -> Any:
            captured["kwargs"] = kwargs
            return SimpleNamespace(content=[SimpleNamespace(text="pong")])

    monkeypatch.setitem(
        sys.modules,
        "anthropic",
        SimpleNamespace(Anthropic=_FakeAnthropic),
    )
    monkeypatch.setattr(
        llm_client,
        "get_settings",
        lambda: SimpleNamespace(
            anthropic_api_key=None,
            anthropic_prompt_cache=False,
        ),
    )

    content, usage = llm_client._call_anthropic(
        [ChatMessage("user", "ping")],
        "test-model",
        0.1,
        8,
        override={
            "api_key": "secret",
            "base_url": "https://anthropic-proxy.example.test",
        },
    )

    assert content == "pong"
    assert usage["usage_estimated"] is True
    assert captured["api_key"] == "secret"
    assert captured["base_url"] == "https://anthropic-proxy.example.test"
    assert captured["kwargs"]["model"] == "test-model"


@pytest.mark.parametrize(
    "provider",
    [
        "kimi",
        "moonshot",
        "qwen",
        "dashscope",
        "zhipu",
        "mistral",
        "xiaomimimo",
        "openai_compatible",
    ],
)
def test_settings_accepts_openai_compatible_provider_names(provider: str) -> None:
    settings = Settings(_env_file=None, llm_provider=provider)

    assert settings.llm_provider == provider
