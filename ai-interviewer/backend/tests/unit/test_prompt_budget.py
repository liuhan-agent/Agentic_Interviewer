from __future__ import annotations

from types import SimpleNamespace

from app.engine.context.prompt_budget import (
    DEFAULT_SKILL_BUDGET_CHARS,
    DEFAULT_STRATEGY_BUDGET_CHARS,
    estimate_auxiliary_prompt_budget,
    rank_body_budgets,
    resolve_generator_model_route,
)


def test_known_long_context_model_expands_elastic_auxiliary_budget() -> None:
    result = estimate_auxiliary_prompt_budget(
        provider="openai",
        model="gpt-4o-mini",
        protected_slot_chars=12_000,
        output_reserve_tokens=2048,
    )

    assert result["budget_level"] == "expanded"
    assert result["fallback_used"] is False
    assert result["strategy_budget_chars"] > DEFAULT_STRATEGY_BUDGET_CHARS
    assert result["skill_budget_chars"] > DEFAULT_SKILL_BUDGET_CHARS
    assert result["elastic_available_chars"] > 0


def test_known_model_uses_tight_budget_when_protected_slots_are_large() -> None:
    result = estimate_auxiliary_prompt_budget(
        provider="qwen",
        model="qwen-plus",
        protected_slot_chars=40_000,
        output_reserve_tokens=2048,
    )

    assert result["budget_level"] == "tight"
    assert result["fallback_used"] is False
    assert result["strategy_budget_chars"] == DEFAULT_STRATEGY_BUDGET_CHARS
    assert result["skill_budget_chars"] == DEFAULT_SKILL_BUDGET_CHARS


def test_unknown_model_context_falls_back_to_current_budgets() -> None:
    result = estimate_auxiliary_prompt_budget(
        provider="openai_compatible",
        model="custom-local-model",
        protected_slot_chars=1_000,
        output_reserve_tokens=2048,
    )

    assert result["budget_level"] == "fallback"
    assert result["fallback_used"] is True
    assert result["fallback_reason"] == "unknown_model_context_window"
    assert result["strategy_budget_chars"] == DEFAULT_STRATEGY_BUDGET_CHARS
    assert result["skill_budget_chars"] == DEFAULT_SKILL_BUDGET_CHARS


def test_deepseek_v4_flash_uses_known_chinese_model_window() -> None:
    result = estimate_auxiliary_prompt_budget(
        provider="deepseek",
        model="deepseek-v4-flash",
        protected_slot_chars=20_000,
        output_reserve_tokens=2048,
    )

    assert result["context_window_tokens"] == 1_024_000
    assert result["budget_level"] == "expanded"
    assert result["fallback_used"] is False


def test_chinese_model_window_suffix_overrides_family_default() -> None:
    result = estimate_auxiliary_prompt_budget(
        provider="moonshot",
        model="moonshot-v1-32k",
        protected_slot_chars=1_000,
        output_reserve_tokens=2048,
    )

    assert result["context_window_tokens"] == 32_000
    assert result["fallback_used"] is False


def test_current_chinese_vendor_models_use_known_windows() -> None:
    cases = [
        ("moonshot", "kimi-k2.5", 256_000),
        ("zhipu", "glm-4.5", 128_000),
        ("volcengine", "doubao-seed-1-6-flash-250828", 256_000),
        ("xiaomimimo", "mimo-v2.5-pro", 1_000_000),
        ("xiaomimimo", "mimo-v2.5", 1_000_000),
        ("xiaomimimo", "mimo-v2-flash", 256_000),
    ]

    for provider, model, expected_window in cases:
        result = estimate_auxiliary_prompt_budget(
            provider=provider,
            model=model,
            protected_slot_chars=20_000,
            output_reserve_tokens=2048,
        )

        assert result["context_window_tokens"] == expected_window
        assert result["budget_level"] == "expanded"
        assert result["fallback_used"] is False


def test_mimo_known_small_context_model_does_not_expand() -> None:
    result = estimate_auxiliary_prompt_budget(
        provider="xiaomimimo",
        model="mimo-v2.5-tts",
        protected_slot_chars=1_000,
        output_reserve_tokens=2048,
    )

    assert result["context_window_tokens"] == 8_000
    assert result["budget_level"] == "fallback"
    assert result["fallback_reason"] == "insufficient_estimated_context_window"
    assert result["fallback_used"] is True


def test_mainland_vendor_family_defaults_are_conservative_known_windows() -> None:
    cases = [
        ("baichuan", "baichuan2-turbo", 32_768),
        ("minimax", "abab6.5s-chat", 32_768),
        ("hunyuan", "hunyuan-turbos-latest", 32_768),
        ("stepfun", "step-2-mini", 32_768),
        ("01ai", "yi-large", 32_768),
        ("baidu", "ernie-4.0-turbo", 32_768),
        ("iflytek", "spark-max", 32_768),
        ("sensenova", "sensechat-5", 32_768),
        ("xiaomimimo", "mimo-unknown-text-model", 256_000),
    ]

    for provider, model, expected_window in cases:
        result = estimate_auxiliary_prompt_budget(
            provider=provider,
            model=model,
            protected_slot_chars=1_000,
            output_reserve_tokens=2048,
        )

        assert result["context_window_tokens"] == expected_window
        assert result["fallback_used"] is False


def test_mimo_known_model_prefix_works_without_provider() -> None:
    result = estimate_auxiliary_prompt_budget(
        provider="openai_compatible",
        model="mimo-v2.5-pro-preview",
        protected_slot_chars=20_000,
        output_reserve_tokens=2048,
    )

    assert result["context_window_tokens"] == 1_000_000
    assert result["budget_level"] == "expanded"
    assert result["fallback_used"] is False


def test_rank_body_budgets_expose_expanded_and_default_levels() -> None:
    assert rank_body_budgets("strategy", "fallback") == (1200, 800, 500, 300)
    assert rank_body_budgets("strategy", "expanded") == (1800, 1200, 800, 400)
    assert rank_body_budgets("skill", "fallback") == (1100, 800, 600, 300)
    assert rank_body_budgets("skill", "expanded") == (1700, 1200, 900, 400)


def test_generator_model_route_honors_role_override() -> None:
    settings = SimpleNamespace(
        llm_provider="openai",
        llm_model="gpt-4o-mini",
        llm_model_per_agent={"generator": "gpt-4.1-mini"},
    )

    route = resolve_generator_model_route(
        settings=settings,
        llm_override={
            "provider": "openai",
            "model": "gpt-4o-mini",
            "role_overrides": {
                "generator": {"provider": "qwen", "model": "qwen-plus"}
            },
        },
    )

    assert route.provider == "qwen"
    assert route.model == "qwen-plus"
