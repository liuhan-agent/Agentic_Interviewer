"""Shared user-facing LLM configuration schema constants."""
from __future__ import annotations

from typing import Literal

LLMProvider = Literal[
    "openai",
    "anthropic",
    "deepseek",
    "kimi",
    "moonshot",
    "qwen",
    "dashscope",
    "zhipu",
    "mistral",
    "xiaomimimo",
    "openai_compatible",
]

LLM_API_KEY_MAX_LENGTH = 4096
LLM_MODEL_MAX_LENGTH = 256
LLM_BASE_URL_MAX_LENGTH = 2048
