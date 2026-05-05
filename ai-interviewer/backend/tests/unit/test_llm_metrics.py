"""LLM cost-observability metrics (P1 #3).

Covers the three Counter-side guarantees that ``record_llm_call``
makes on every ``call_chat`` exit:

1. Real provider responses with ``usage`` carry the prompt /
   completion token counts straight through.
2. Provider responses without ``usage`` fall back to a deterministic
   chars/4 estimate so cost dashboards never see ``None``.
3. Stub and error paths still increment ``LLM_CALLS_TOTAL`` with the
   matching ``status`` label so ops can spot stub-mode traffic.

Plus a few sanity checks on :func:`estimate_llm_cost_usd` so
``cost_summary.est_usd`` is robust to unknown models / negative
inputs / longest-prefix matches like ``gpt-4o-mini-2024-07-18``.
"""
from __future__ import annotations

from typing import Any

import pytest

from app.core import metrics
from app.core.metrics import (
    estimate_llm_cost_usd,
    llm_metrics_snapshot,
    record_llm_call,
    reset_llm_metrics_for_tests,
)
from app.engine.agents import llm_client
from app.engine.agents.llm_client import (
    ChatMessage,
    LLMFatal,
    _empty_usage,
    _estimate_tokens_from_chars,
    _extract_anthropic_usage,
    _extract_openai_usage,
    call_chat,
)


@pytest.fixture(autouse=True)
def _reset_metrics() -> None:
    """Each test starts from a clean LLM Counter snapshot."""
    reset_llm_metrics_for_tests()
    yield
    reset_llm_metrics_for_tests()


# ---------------------------------------------------------------------------
# record_llm_call: Counter book-keeping
# ---------------------------------------------------------------------------


def test_record_llm_call_increments_calls_and_token_counters() -> None:
    record_llm_call(
        agent_role="generator",
        provider="openai",
        model="gpt-4o-mini",
        status="success",
        prompt_tokens=120,
        completion_tokens=64,
    )
    snap = llm_metrics_snapshot()
    assert snap["llm_calls"]["generator:openai:gpt-4o-mini:success"] == 1
    assert snap["llm_prompt_tokens"]["generator:openai:gpt-4o-mini"] == 120
    assert snap["llm_completion_tokens"]["generator:openai:gpt-4o-mini"] == 64


def test_record_llm_call_zero_tokens_skips_token_counters() -> None:
    """Error paths book a call but no tokens — counters must stay clean."""
    record_llm_call(
        agent_role="evaluator",
        provider="deepseek",
        model="deepseek-chat",
        status="error",
        prompt_tokens=0,
        completion_tokens=0,
    )
    snap = llm_metrics_snapshot()
    assert snap["llm_calls"]["evaluator:deepseek:deepseek-chat:error"] == 1
    assert snap["llm_prompt_tokens"] == {}
    assert snap["llm_completion_tokens"] == {}


def test_record_llm_call_normalises_blank_labels() -> None:
    """Empty agent_role / provider / model labels become ``unknown`` so the
    Prometheus library never drops the sample silently."""
    record_llm_call(
        agent_role=None,
        provider="",
        model="",
        status="",
        prompt_tokens=10,
        completion_tokens=10,
    )
    snap = llm_metrics_snapshot()
    assert snap["llm_calls"]["unknown:unknown:unknown:unknown"] == 1


# ---------------------------------------------------------------------------
# usage extraction helpers
# ---------------------------------------------------------------------------


class _Usage:
    """Mimics the SDK's nested ``resp.usage`` attribute container."""

    def __init__(self, **kwargs: Any) -> None:
        for key, value in kwargs.items():
            setattr(self, key, value)


class _OpenAIResp:
    def __init__(self, *, usage: _Usage | None) -> None:
        self.usage = usage


def test_extract_openai_usage_real_usage_block() -> None:
    resp = _OpenAIResp(usage=_Usage(prompt_tokens=300, completion_tokens=128))
    out = _extract_openai_usage(resp, content="hello world", input_chars=400)
    assert out == {
        "prompt_tokens": 300,
        "completion_tokens": 128,
        "usage_estimated": False,
    }


def test_extract_openai_usage_missing_block_falls_back_to_char_estimate() -> None:
    resp = _OpenAIResp(usage=None)
    out = _extract_openai_usage(resp, content="abcd" * 5, input_chars=400)
    assert out["usage_estimated"] is True
    assert out["prompt_tokens"] == _estimate_tokens_from_chars(400)
    assert out["completion_tokens"] == _estimate_tokens_from_chars(20)


def test_extract_anthropic_usage_renames_input_output_tokens() -> None:
    resp = _OpenAIResp(usage=_Usage(input_tokens=512, output_tokens=88))
    out = _extract_anthropic_usage(resp, content="x" * 200, input_chars=900)
    assert out == {
        "prompt_tokens": 512,
        "completion_tokens": 88,
        "usage_estimated": False,
    }


def test_extract_usage_supports_dict_shape() -> None:
    """Some self-hosted gateways expose ``usage`` as a plain dict."""
    resp_dict = type("R", (), {})()
    resp_dict.usage = {"prompt_tokens": 7, "completion_tokens": 3}
    out = _extract_openai_usage(resp_dict, content="hi", input_chars=10)
    assert out == {
        "prompt_tokens": 7,
        "completion_tokens": 3,
        "usage_estimated": False,
    }


def test_empty_usage_is_zero_estimated() -> None:
    assert _empty_usage() == {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "usage_estimated": True,
    }


# ---------------------------------------------------------------------------
# call_chat: success path
# ---------------------------------------------------------------------------


def _force_real_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    """Drive ``call_chat`` through the real provider branch.

    ``use_stub_llm`` is a derived ``Settings`` property that depends on
    ``llm_provider`` + ``openai_api_key``. When the test environment's
    ``.env`` pins ``LLM_PROVIDER=stub``, we override both attributes so
    the property returns ``False`` even though we don't actually hit
    OpenAI (``_invoke_provider`` is monkeypatched separately).
    """
    settings = llm_client.get_settings()
    monkeypatch.setattr(settings, "llm_provider", "openai", raising=False)
    monkeypatch.setattr(settings, "openai_api_key", "sk-test-not-empty", raising=False)


def test_call_chat_success_books_real_usage(monkeypatch: pytest.MonkeyPatch) -> None:
    _force_real_provider(monkeypatch)
    monkeypatch.setattr(
        llm_client,
        "_invoke_provider",
        lambda messages, **_kw: (
            "fake-response",
            {"prompt_tokens": 250, "completion_tokens": 128, "usage_estimated": False},
        ),
    )
    out = call_chat(
        [ChatMessage(role="user", content="hello")],
        agent_role="generator",
    )
    assert out == "fake-response"

    snap = llm_metrics_snapshot()
    role_provider = "generator:openai"
    success_key = f"{role_provider}:{settings_model_for_default()}:success"
    assert snap["llm_calls"][success_key] == 1
    assert snap["llm_prompt_tokens"][f"{role_provider}:{settings_model_for_default()}"] == 250
    assert (
        snap["llm_completion_tokens"][f"{role_provider}:{settings_model_for_default()}"]
        == 128
    )


def settings_model_for_default() -> str:
    """Read the actual default model used by ``call_chat`` so the assertion key
    stays in sync with whatever ``settings.llm_model`` resolves to in this env."""
    return llm_client.get_settings().llm_model


# ---------------------------------------------------------------------------
# call_chat: error path
# ---------------------------------------------------------------------------


def test_call_chat_error_books_call_with_zero_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    _force_real_provider(monkeypatch)

    def _boom(messages: list[ChatMessage], **_kw: Any) -> tuple[str, dict[str, Any]]:
        raise LLMFatal("upstream auth failure")

    monkeypatch.setattr(llm_client, "_invoke_provider", _boom)

    with pytest.raises(LLMFatal):
        call_chat(
            [ChatMessage(role="user", content="hi")],
            agent_role="evaluator",
        )

    snap = llm_metrics_snapshot()
    error_key = f"evaluator:openai:{settings_model_for_default()}:error"
    assert snap["llm_calls"][error_key] == 1
    assert snap["llm_prompt_tokens"] == {}
    assert snap["llm_completion_tokens"] == {}


# ---------------------------------------------------------------------------
# call_chat: stub path (no real API key)
# ---------------------------------------------------------------------------


def test_call_chat_stub_books_estimated_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = llm_client.get_settings()
    # Force stub mode by clearing every API key so ``use_stub_llm`` is True.
    monkeypatch.setattr(settings, "openai_api_key", None, raising=False)
    monkeypatch.setattr(settings, "deepseek_api_key", None, raising=False)
    monkeypatch.setattr(settings, "anthropic_api_key", None, raising=False)

    out = call_chat(
        [ChatMessage(role="user", content="hello world this is the test prompt")],
        agent_role="guard",
    )
    assert out  # stub returns a deterministic non-empty string

    snap = llm_metrics_snapshot()
    stub_keys = [k for k in snap["llm_calls"] if k.startswith("guard:") and k.endswith(":stub")]
    assert len(stub_keys) == 1
    # Stub path must increment prompt/completion at least by 1 (estimate floor).
    role_provider_model = stub_keys[0].rsplit(":", 1)[0]
    assert snap["llm_prompt_tokens"][role_provider_model] >= 1
    assert snap["llm_completion_tokens"][role_provider_model] >= 1


# ---------------------------------------------------------------------------
# estimate_llm_cost_usd: pricing table sanity
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "model,prompt,completion,expected_min,expected_max",
    [
        # gpt-4o-mini = (0.00015, 0.0006) per 1k -> 1k prompt + 1k completion = 0.00075
        ("gpt-4o-mini", 1000, 1000, 0.00073, 0.00077),
        # gpt-4o = (0.0025, 0.01) -> 1k+1k = 0.0125
        ("gpt-4o", 1000, 1000, 0.01245, 0.01255),
        # deepseek-chat = (0.00027, 0.0011) -> 1k+1k = 0.00137
        ("deepseek-chat", 1000, 1000, 0.00134, 0.00140),
        # Unknown model -> default fallback (0.0005, 0.0015) -> 1k+1k = 0.002
        ("totally-fake-model-xyz", 1000, 1000, 0.00198, 0.00203),
    ],
)
def test_estimate_llm_cost_usd_pricing_within_tolerance(
    model: str,
    prompt: int,
    completion: int,
    expected_min: float,
    expected_max: float,
) -> None:
    cost = estimate_llm_cost_usd(
        model=model,
        prompt_tokens=prompt,
        completion_tokens=completion,
    )
    assert expected_min <= cost <= expected_max, (model, cost)


def test_estimate_llm_cost_usd_zero_or_negative_tokens_returns_zero() -> None:
    assert estimate_llm_cost_usd(model="gpt-4o", prompt_tokens=0, completion_tokens=0) == 0.0
    assert estimate_llm_cost_usd(model="gpt-4o", prompt_tokens=-5, completion_tokens=-5) == 0.0


def test_estimate_llm_cost_usd_longest_prefix_match() -> None:
    """``gpt-4o-mini-2024-07-18`` should map to ``gpt-4o-mini`` (longer prefix)
    rather than the shorter ``gpt-4`` entry."""
    cost_short = estimate_llm_cost_usd(
        model="gpt-4o-mini-2024-07-18",
        prompt_tokens=1000,
        completion_tokens=0,
    )
    cost_full = estimate_llm_cost_usd(
        model="gpt-4o-mini",
        prompt_tokens=1000,
        completion_tokens=0,
    )
    assert cost_short == cost_full


# ---------------------------------------------------------------------------
# Prometheus Counter raw inc surface (smoke test)
# ---------------------------------------------------------------------------


def test_record_llm_call_increments_prometheus_counter() -> None:
    """Sanity check that we hit the actual Counter, not just the dict.

    We read the metric family before and after to confirm the inc landed."""
    before = _counter_value(metrics.LLM_CALLS_TOTAL, role="evaluator", status="success")
    record_llm_call(
        agent_role="evaluator",
        provider="openai",
        model="gpt-4o",
        status="success",
        prompt_tokens=11,
        completion_tokens=22,
    )
    after = _counter_value(metrics.LLM_CALLS_TOTAL, role="evaluator", status="success")
    assert after - before == 1


def _counter_value(counter: Any, *, role: str, status: str) -> float:
    """Sum every sample whose label set matches the given role + status."""
    total = 0.0
    for metric in counter.collect():
        for sample in metric.samples:
            if sample.name.endswith("_total") and sample.labels.get("agent_role") == role and sample.labels.get("status") == status:
                total += sample.value
    return total
