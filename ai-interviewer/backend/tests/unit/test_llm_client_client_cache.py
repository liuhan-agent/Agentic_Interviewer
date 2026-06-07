"""Tests for the SDK client cache in :mod:`app.engine.agents.llm_client`.

These tests exercise the public-style helpers ``_get_openai_client`` /
``_get_anthropic_client`` directly (rather than going through
``call_chat``) so a cache regression is pinned to a single line of
code instead of buried under provider plumbing. We monkey-patch the
SDK constructors with counter-recording fakes — the production code
imports them lazily from inside the helper, which keeps the patch
target small and stable across openai/anthropic version bumps.
"""
from __future__ import annotations

import sys
import threading
from types import ModuleType
from typing import Any

import pytest

from app.engine.agents import llm_client


@pytest.fixture(autouse=True)
def _reset_cache() -> None:
    """Drop cached clients before and after every case in this module."""
    llm_client._reset_client_cache_for_tests()
    yield
    llm_client._reset_client_cache_for_tests()


def _install_fake_openai(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Replace ``openai.OpenAI`` with a counting fake. Returns a dict
    holding the construction count and the most recent kwargs."""
    state: dict[str, Any] = {"count": 0, "last_kwargs": None}

    class _FakeClient:
        def __init__(self, **kwargs: Any) -> None:
            state["count"] += 1
            state["last_kwargs"] = kwargs
            self._http_client = kwargs.get("http_client")

        def close(self) -> None:
            close = getattr(self._http_client, "close", None)
            if callable(close):
                close()

    fake_module = ModuleType("openai")
    fake_module.OpenAI = _FakeClient
    monkeypatch.setitem(sys.modules, "openai", fake_module)
    return state


def _install_fake_anthropic(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    state: dict[str, Any] = {"count": 0, "last_kwargs": None}

    class _FakeClient:
        def __init__(self, **kwargs: Any) -> None:
            state["count"] += 1
            state["last_kwargs"] = kwargs
            self._http_client = kwargs.get("http_client")

        def close(self) -> None:
            close = getattr(self._http_client, "close", None)
            if callable(close):
                close()

    fake_module = ModuleType("anthropic")
    fake_module.Anthropic = _FakeClient
    monkeypatch.setitem(sys.modules, "anthropic", fake_module)
    return state


# ---------------------------------------------------------------------------
# OpenAI client cache
# ---------------------------------------------------------------------------


def test_openai_client_reused_when_params_identical(monkeypatch: pytest.MonkeyPatch) -> None:
    state = _install_fake_openai(monkeypatch)
    c1 = llm_client._get_openai_client(
        api_key="key-1", base_url=None, timeout=10.0, max_retries=0
    )
    c2 = llm_client._get_openai_client(
        api_key="key-1", base_url=None, timeout=10.0, max_retries=0
    )
    assert c1 is c2
    assert state["count"] == 1


def test_openai_client_distinct_per_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    state = _install_fake_openai(monkeypatch)
    c1 = llm_client._get_openai_client(
        api_key="key-1", base_url=None, timeout=10.0, max_retries=0
    )
    c2 = llm_client._get_openai_client(
        api_key="key-2", base_url=None, timeout=10.0, max_retries=0
    )
    assert c1 is not c2
    assert state["count"] == 2


def test_openai_client_distinct_per_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    state = _install_fake_openai(monkeypatch)
    llm_client._get_openai_client(
        api_key="key-1", base_url="https://api.openai.com/v1",
        timeout=10.0, max_retries=0,
    )
    llm_client._get_openai_client(
        api_key="key-1", base_url="https://api.deepseek.com/v1",
        timeout=10.0, max_retries=0,
    )
    assert state["count"] == 2


def test_openai_client_distinct_per_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """Timeout enters the key because it binds to the underlying httpx
    transport at construction time; mixing 10s and 60s timeouts must
    not collide on a single client."""
    state = _install_fake_openai(monkeypatch)
    llm_client._get_openai_client(
        api_key="key-1", base_url=None, timeout=10.0, max_retries=0
    )
    llm_client._get_openai_client(
        api_key="key-1", base_url=None, timeout=60.0, max_retries=0
    )
    assert state["count"] == 2


def test_openai_client_distinct_per_max_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    state = _install_fake_openai(monkeypatch)
    llm_client._get_openai_client(
        api_key="key-1", base_url=None, timeout=10.0, max_retries=0
    )
    llm_client._get_openai_client(
        api_key="key-1", base_url=None, timeout=10.0, max_retries=3
    )
    assert state["count"] == 2


def test_openai_client_constructor_kwargs_forwarded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _install_fake_openai(monkeypatch)
    llm_client._get_openai_client(
        api_key="my-key",
        base_url="https://example.test/v1",
        timeout=12.5,
        max_retries=2,
    )
    http_client = state["last_kwargs"].pop("http_client")
    assert getattr(http_client, "_trust_env", None) is False
    assert state["last_kwargs"] == {
        "api_key": "my-key",
        "base_url": "https://example.test/v1",
        "timeout": 12.5,
        "max_retries": 2,
    }


def test_openai_client_ignores_invalid_no_proxy_env(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("openai")
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost,::1,127.0.0.0/8,::1/128")
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost,::1,127.0.0.0/8,::1/128")

    client = llm_client._get_openai_client(
        api_key="test-key",
        base_url="https://example.test/v1",
        timeout=10.0,
        max_retries=0,
    )
    close = getattr(client, "close", None)
    if callable(close):
        close()


def test_openai_compatible_transient_failure_evicts_cached_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A poisoned OpenAI-compatible connection pool must not be reused.

    DashScope/Qwen can fail fast with connection-reset style errors
    after earlier successful calls. When that happens, the next request
    should rebuild the SDK client instead of reusing the same cached
    transport.
    """
    state: dict[str, Any] = {"count": 0, "closed": 0}

    class _FailingCompletions:
        def create(self, **_kwargs: Any) -> Any:
            raise RuntimeError("connection reset by peer")

    class _FakeClient:
        def __init__(self, **_kwargs: Any) -> None:
            state["count"] += 1
            self.chat = type(
                "_Chat",
                (),
                {"completions": _FailingCompletions()},
            )()

        def close(self) -> None:
            state["closed"] += 1

    fake_module = ModuleType("openai")
    fake_module.OpenAI = _FakeClient
    monkeypatch.setitem(sys.modules, "openai", fake_module)

    with pytest.raises(RuntimeError, match="connection reset"):
        llm_client._call_openai_compatible(
            [llm_client.ChatMessage("user", "ping")],
            "qwen3.6-flash",
            0.1,
            8,
            False,
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            override={"api_key": "key-1"},
            request_timeout=45.0,
            provider_max_retries=0,
        )

    llm_client._get_openai_client(
        api_key="key-1",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        timeout=45.0,
        max_retries=0,
    )
    assert state["count"] == 2
    assert state["closed"] == 1


# ---------------------------------------------------------------------------
# Anthropic client cache
# ---------------------------------------------------------------------------


def test_anthropic_client_reused_when_params_identical(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _install_fake_anthropic(monkeypatch)
    c1 = llm_client._get_anthropic_client(api_key="key-1", base_url=None)
    c2 = llm_client._get_anthropic_client(api_key="key-1", base_url=None)
    assert c1 is c2
    assert state["count"] == 1


def test_anthropic_client_distinct_per_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _install_fake_anthropic(monkeypatch)
    llm_client._get_anthropic_client(api_key="key-1", base_url=None)
    llm_client._get_anthropic_client(api_key="key-2", base_url=None)
    assert state["count"] == 2


def test_anthropic_client_distinct_per_base_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _install_fake_anthropic(monkeypatch)
    llm_client._get_anthropic_client(
        api_key="key-1", base_url="https://api.anthropic.com"
    )
    llm_client._get_anthropic_client(
        api_key="key-1", base_url="https://api.proxy.test"
    )
    assert state["count"] == 2


def test_anthropic_client_ignores_invalid_no_proxy_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("anthropic")
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost,::1,127.0.0.0/8,::1/128")
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost,::1,127.0.0.0/8,::1/128")

    client = llm_client._get_anthropic_client(
        api_key="test-key",
        base_url="https://example.test",
    )
    close = getattr(client, "close", None)
    if callable(close):
        close()


# ---------------------------------------------------------------------------
# Reset / isolation
# ---------------------------------------------------------------------------


def test_reset_drops_all_cached_clients(monkeypatch: pytest.MonkeyPatch) -> None:
    state = _install_fake_openai(monkeypatch)
    llm_client._get_openai_client(
        api_key="key-1", base_url=None, timeout=10.0, max_retries=0
    )
    llm_client._reset_client_cache_for_tests()
    llm_client._get_openai_client(
        api_key="key-1", base_url=None, timeout=10.0, max_retries=0
    )
    assert state["count"] == 2


def test_concurrent_construction_yields_single_instance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Many threads racing on the same key must converge on one client.

    The fake constructor sleeps briefly so the threads overlap inside
    the cache lookup window; without the lock the test would
    occasionally see ``count > 1``.
    """
    state: dict[str, Any] = {"count": 0, "last_kwargs": None}

    class _SlowFakeClient:
        def __init__(self, **kwargs: Any) -> None:
            import time as _time

            _time.sleep(0.005)
            state["count"] += 1
            state["last_kwargs"] = kwargs

    fake_module = ModuleType("openai")
    fake_module.OpenAI = _SlowFakeClient
    monkeypatch.setitem(sys.modules, "openai", fake_module)

    instances: list[Any] = []
    instances_lock = threading.Lock()

    def _race() -> None:
        c = llm_client._get_openai_client(
            api_key="race-key", base_url=None, timeout=10.0, max_retries=0
        )
        with instances_lock:
            instances.append(c)

    threads = [threading.Thread(target=_race) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert state["count"] == 1
    assert all(c is instances[0] for c in instances)
