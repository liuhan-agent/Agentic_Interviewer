"""Conservative prompt budget estimates for elastic ask_question materials.

This module deliberately estimates by characters instead of tokenizer-specific
tokens. The goal is not exact accounting; it is a stable quality floor for
elastic auxiliary blocks while preserving the current fallback behaviour when
the model route is unknown.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

DEFAULT_STRATEGY_BUDGET_CHARS = 3200
DEFAULT_SKILL_BUDGET_CHARS = 3600
NORMAL_STRATEGY_BUDGET_CHARS = 3600
NORMAL_SKILL_BUDGET_CHARS = 4000
EXPANDED_STRATEGY_BUDGET_CHARS = 4800
EXPANDED_SKILL_BUDGET_CHARS = 5200

CHAR_PER_TOKEN_ESTIMATE = 1.5
FIXED_PROMPT_OVERHEAD_TOKENS = 4096
SAFETY_MARGIN_TOKENS = 2048
MIN_OUTPUT_RESERVE_TOKENS = 2048
EXPANDED_ELASTIC_THRESHOLD_CHARS = 9000
NORMAL_ELASTIC_THRESHOLD_CHARS = 6500

STRATEGY_RANK_BODY_BUDGETS: dict[str, tuple[int, int, int, int]] = {
    "fallback": (1200, 800, 500, 300),
    "tight": (1200, 800, 500, 300),
    "normal": (1400, 900, 600, 300),
    "expanded": (1800, 1200, 800, 400),
}
SKILL_RANK_BODY_BUDGETS: dict[str, tuple[int, int, int, int]] = {
    "fallback": (1100, 800, 600, 300),
    "tight": (1100, 800, 600, 300),
    "normal": (1300, 900, 700, 300),
    "expanded": (1700, 1200, 900, 400),
}

MODEL_WINDOW_SUFFIX_RE = re.compile(r"(?:^|[-_.])(?P<size>[1-9]\d{0,3})k(?:$|[-_.])")
MODEL_WINDOW_M_SUFFIX_RE = re.compile(r"(?:^|[-_.])(?P<size>[1-9]\d{0,2})m(?:$|[-_.])")

KNOWN_MODEL_CONTEXT_WINDOWS: tuple[tuple[str, int], ...] = (
    ("deepseek-v4-flash", 1_024_000),
    ("deepseek-v4-pro", 1_024_000),
    ("deepseek-v3.2", 128_000),
    ("deepseek-v3-2", 128_000),
    ("deepseek-chat", 64_000),
    ("deepseek-reasoner", 64_000),
    ("kimi-k2.5", 256_000),
    ("kimi-k2-0905", 256_000),
    ("kimi-k2-thinking", 256_000),
    ("moonshot-v1", 128_000),
    ("glm-4.7", 200_000),
    ("glm-4.6", 128_000),
    ("glm-4.5", 128_000),
    ("doubao-seed-2-0", 256_000),
    ("doubao-seed-2.0", 256_000),
    ("doubao-seed-1-8", 256_000),
    ("doubao-seed-1.8", 256_000),
    ("doubao-seed-1-6", 256_000),
    ("doubao-seed-1.6", 256_000),
    ("mimo-v2.5-tts-voiceclone", 8_000),
    ("mimo-v2.5-tts-voicedesign", 8_000),
    ("mimo-v2.5-tts", 8_000),
    ("mimo-v2-tts", 8_000),
    ("mimo-v2.5-pro", 1_000_000),
    ("mimo-v2-pro", 1_000_000),
    ("mimo-v2.5", 1_000_000),
    ("mimo-v2-omni", 256_000),
    ("mimo-v2-flash", 256_000),
)

PROVIDER_CONTEXT_DEFAULTS: dict[str, int] = {
    "qwen": 32_768,
    "dashscope": 32_768,
    "alibaba": 32_768,
    "deepseek": 64_000,
    "moonshot": 128_000,
    "kimi": 128_000,
    "zhipu": 128_000,
    "bigmodel": 128_000,
    "z.ai": 128_000,
    "zai": 128_000,
    "glm": 128_000,
    "volcengine": 32_768,
    "ark": 32_768,
    "doubao": 32_768,
    "bytedance": 32_768,
    "baichuan": 32_768,
    "minimax": 32_768,
    "hunyuan": 32_768,
    "tencent": 32_768,
    "stepfun": 32_768,
    "step": 32_768,
    "01ai": 32_768,
    "yi": 32_768,
    "baidu": 32_768,
    "ernie": 32_768,
    "wenxin": 32_768,
    "iflytek": 32_768,
    "spark": 32_768,
    "sensenova": 32_768,
    "sensechat": 32_768,
    "xiaomimimo": 256_000,
    "mimo": 256_000,
    "xiaomi": 256_000,
}

MODEL_PREFIX_CONTEXT_DEFAULTS: tuple[tuple[str, int], ...] = (
    ("qwen", 32_768),
    ("qwq", 32_768),
    ("deepseek-", 64_000),
    ("moonshot-", 128_000),
    ("kimi-", 128_000),
    ("glm-", 128_000),
    ("doubao-", 32_768),
    ("baichuan", 32_768),
    ("abab", 32_768),
    ("minimax", 32_768),
    ("hunyuan", 32_768),
    ("step-", 32_768),
    ("yi-", 32_768),
    ("ernie-", 32_768),
    ("wenxin-", 32_768),
    ("spark-", 32_768),
    ("sensechat", 32_768),
    ("mimo-", 256_000),
)


@dataclass(frozen=True)
class ModelRoute:
    provider: str
    model: str


def rank_body_budgets(kind: str, level: str) -> tuple[int, int, int, int]:
    source = (
        STRATEGY_RANK_BODY_BUDGETS
        if kind == "strategy"
        else SKILL_RANK_BODY_BUDGETS
    )
    return source.get(level, source["fallback"])


def resolve_generator_model_route(
    *,
    settings: Any,
    llm_override: dict[str, Any] | None,
) -> ModelRoute:
    """Resolve the provider/model route used by ``agent_role='generator'``."""

    mapped_model = (
        getattr(settings, "llm_model_per_agent", {}) or {}
    ).get("generator")
    provider = str(getattr(settings, "llm_provider", "") or "").strip()
    model = str(mapped_model or getattr(settings, "llm_model", "") or "").strip()

    override = llm_override if isinstance(llm_override, dict) else {}
    role_overrides = override.get("role_overrides") or {}
    role_override = (
        role_overrides.get("generator")
        if isinstance(role_overrides, dict)
        else None
    )

    if override.get("provider"):
        provider = str(override.get("provider") or "").strip()
    if override.get("model"):
        model = str(override.get("model") or "").strip()
    if isinstance(role_override, dict):
        if role_override.get("provider"):
            provider = str(role_override.get("provider") or "").strip()
        if role_override.get("model"):
            model = str(role_override.get("model") or "").strip()

    return ModelRoute(provider=provider, model=model)


def estimate_auxiliary_prompt_budget(
    *,
    provider: str | None,
    model: str | None,
    protected_slot_chars: int,
    output_reserve_tokens: int | None = None,
) -> dict[str, Any]:
    """Estimate Strategy/Skill budgets from model context and protected slots."""

    provider_label = str(provider or "").strip()
    model_label = str(model or "").strip()
    context_tokens = _context_window_tokens(provider_label, model_label)
    protected_chars = max(0, int(protected_slot_chars or 0))
    reserve_tokens = max(
        MIN_OUTPUT_RESERVE_TOKENS,
        int(output_reserve_tokens or MIN_OUTPUT_RESERVE_TOKENS),
    )

    diagnostics: dict[str, Any] = {
        "mode": "elastic_auxiliary",
        "enabled": True,
        "provider": provider_label,
        "model": model_label,
        "context_window_tokens": context_tokens,
        "char_per_token_estimate": CHAR_PER_TOKEN_ESTIMATE,
        "fixed_prompt_overhead_tokens": FIXED_PROMPT_OVERHEAD_TOKENS,
        "output_reserve_tokens": reserve_tokens,
        "safety_margin_tokens": SAFETY_MARGIN_TOKENS,
        "protected_slot_chars": protected_chars,
        "protected_slots": [],
        "elastic_slots": ["STRATEGY_MEMORY", "INTERVIEW_SKILLS"],
        "confidence": "estimated",
        "fallback_used": False,
        "fallback_reason": None,
    }

    if context_tokens is None:
        return _fallback_diagnostics(
            diagnostics,
            reason="unknown_model_context_window",
        )

    usable_tokens = (
        context_tokens
        - reserve_tokens
        - FIXED_PROMPT_OVERHEAD_TOKENS
        - SAFETY_MARGIN_TOKENS
    )
    if usable_tokens <= 0:
        return _fallback_diagnostics(
            diagnostics,
            reason="insufficient_estimated_context_window",
        )

    usable_prompt_chars = int(usable_tokens * CHAR_PER_TOKEN_ESTIMATE)
    elastic_available = usable_prompt_chars - protected_chars
    if elastic_available >= EXPANDED_ELASTIC_THRESHOLD_CHARS:
        level = "expanded"
        strategy_budget = EXPANDED_STRATEGY_BUDGET_CHARS
        skill_budget = EXPANDED_SKILL_BUDGET_CHARS
    elif elastic_available >= NORMAL_ELASTIC_THRESHOLD_CHARS:
        level = "normal"
        strategy_budget = NORMAL_STRATEGY_BUDGET_CHARS
        skill_budget = NORMAL_SKILL_BUDGET_CHARS
    else:
        level = "tight"
        strategy_budget = DEFAULT_STRATEGY_BUDGET_CHARS
        skill_budget = DEFAULT_SKILL_BUDGET_CHARS

    diagnostics.update(
        {
            "usable_prompt_chars": usable_prompt_chars,
            "elastic_available_chars": elastic_available,
            "budget_level": level,
            "strategy_budget_chars": strategy_budget,
            "skill_budget_chars": skill_budget,
        }
    )
    return diagnostics


def _fallback_diagnostics(
    diagnostics: dict[str, Any],
    *,
    reason: str,
) -> dict[str, Any]:
    diagnostics.update(
        {
            "usable_prompt_chars": None,
            "elastic_available_chars": None,
            "budget_level": "fallback",
            "strategy_budget_chars": DEFAULT_STRATEGY_BUDGET_CHARS,
            "skill_budget_chars": DEFAULT_SKILL_BUDGET_CHARS,
            "fallback_used": True,
            "fallback_reason": reason,
        }
    )
    return diagnostics


def _context_window_tokens(provider: str, model: str) -> int | None:
    normalized_provider = provider.lower().strip()
    normalized_model = model.lower().strip()
    if not normalized_model:
        return None

    if normalized_provider == "openai" or normalized_model.startswith("gpt-"):
        if normalized_model.startswith(
            ("gpt-4o", "gpt-4.1", "gpt-4-turbo")
        ):
            return 128_000
        if normalized_model.startswith("gpt-3.5"):
            return 16_000
        return None

    suffix_window = _context_window_from_model_suffix(normalized_model)
    if suffix_window is not None:
        return suffix_window

    known_window = _known_chinese_model_context_window(normalized_model)
    if known_window is not None:
        return known_window

    if normalized_provider in {"qwen", "dashscope"} or normalized_model.startswith(
        ("qwen", "qwq")
    ):
        return 32_768

    provider_default = PROVIDER_CONTEXT_DEFAULTS.get(normalized_provider)
    if provider_default is not None:
        return provider_default

    for prefix, context_tokens in MODEL_PREFIX_CONTEXT_DEFAULTS:
        if normalized_model.startswith(prefix):
            return context_tokens

    return None


def _context_window_from_model_suffix(normalized_model: str) -> int | None:
    match = MODEL_WINDOW_M_SUFFIX_RE.search(normalized_model)
    if match:
        return int(match.group("size")) * 1_000_000

    match = MODEL_WINDOW_SUFFIX_RE.search(normalized_model)
    if match:
        return int(match.group("size")) * 1_000

    return None


def _known_chinese_model_context_window(normalized_model: str) -> int | None:
    for prefix, context_tokens in KNOWN_MODEL_CONTEXT_WINDOWS:
        if normalized_model == prefix or normalized_model.startswith(f"{prefix}-"):
            return context_tokens
    return None
