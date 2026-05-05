from __future__ import annotations

from types import SimpleNamespace

from app.engine.agents import llm_client
from app.engine.agents.llm_client import ChatMessage


def _settings() -> SimpleNamespace:
    return SimpleNamespace(
        llm_temperature=0.2,
        llm_max_tokens=512,
        llm_model="test-model",
        llm_model_per_agent={},
        llm_provider="openai",
        llm_max_retries=0,
        llm_retry_backoff_seconds=0.0,
        llm_retry_backoff_cap_seconds=0.0,
        llm_request_timeout_seconds=20.0,
        generator_llm_timeout_seconds=45.0,
        evaluator_llm_timeout_seconds=45.0,
        use_stub_llm=False,
    )


def test_call_chat_records_role_timing_success(monkeypatch) -> None:
    from app.core import timing

    monkeypatch.setattr(llm_client, "get_settings", _settings)
    monkeypatch.setattr(llm_client, "_invoke_provider", lambda *_a, **_kw: "ok")

    token = timing.start_timing_trace()
    try:
        result = llm_client.call_chat(
            [ChatMessage(role="user", content="hello")],
            json_mode=True,
            agent_role="generator",
        )
        events = timing.consume_llm_timing_events()
    finally:
        timing.reset_timing_trace(token)

    assert result == "ok"
    assert len(events) == 1
    event = events[0]
    assert event["role"] == "generator"
    assert event["provider"] == "openai"
    assert event["model"] == "test-model"
    assert event["status"] == "success"
    assert event["elapsed_ms"] >= 0
    assert event["input_chars"] == len("hello")
    assert event["output_chars"] == len("ok")

