"""Provider registry for session-anchor embedding routes.

The first BYOK rollout exposes only Qwen in the UI, but the runtime keeps
provider defaults in one place so adding another OpenAI-compatible embedding
service later is a registry change instead of scattered conditionals.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


class UnsupportedEmbeddingProviderError(ValueError):
    """Raised when a browser-supplied embedding provider is not enabled."""


@dataclass(frozen=True)
class EmbeddingProviderSpec:
    id: str
    protocol: Literal["openai_compatible"]
    default_model: str
    default_base_url: str
    requires_base_url: bool
    supported_dimensions: frozenset[int]
    max_batch_size: int = 64
    allow_browser_override: bool = False
    aliases: tuple[str, ...] = ()


EMBEDDING_PROVIDER_SPECS: dict[str, EmbeddingProviderSpec] = {
    "qwen": EmbeddingProviderSpec(
        id="qwen",
        protocol="openai_compatible",
        default_model="text-embedding-v4",
        default_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        requires_base_url=False,
        supported_dimensions=frozenset({1536}),
        max_batch_size=10,
        allow_browser_override=True,
        aliases=("dashscope",),
    ),
    # Reserved for a future UI rollout. The OpenAI-compatible request path
    # already supports these shapes, but browser BYOK is intentionally Qwen-only
    # until the product exposes matching copy and dimension guarantees.
    "openai": EmbeddingProviderSpec(
        id="openai",
        protocol="openai_compatible",
        default_model="text-embedding-3-small",
        default_base_url="https://api.openai.com/v1",
        requires_base_url=False,
        supported_dimensions=frozenset({1536}),
    ),
    "openai_compatible": EmbeddingProviderSpec(
        id="openai_compatible",
        protocol="openai_compatible",
        default_model="",
        default_base_url="",
        requires_base_url=True,
        supported_dimensions=frozenset({1536}),
    ),
}

_ALIASES: dict[str, str] = {
    alias: spec.id
    for spec in EMBEDDING_PROVIDER_SPECS.values()
    for alias in spec.aliases
}


def normalize_embedding_provider(provider: str | None) -> str:
    raw = str(provider or "qwen").strip().lower()
    return _ALIASES.get(raw, raw)


def embedding_provider_spec(provider: str | None) -> EmbeddingProviderSpec:
    canonical = normalize_embedding_provider(provider)
    spec = EMBEDDING_PROVIDER_SPECS.get(canonical)
    if spec is None:
        raise UnsupportedEmbeddingProviderError(
            f"unsupported embedding provider: {str(provider or '').strip() or 'unknown'}"
        )
    return spec


def browser_embedding_provider_spec(provider: str | None) -> EmbeddingProviderSpec:
    spec = embedding_provider_spec(provider)
    if not spec.allow_browser_override:
        raise UnsupportedEmbeddingProviderError(
            f"unsupported embedding provider: {str(provider or '').strip() or spec.id}"
        )
    return spec


def supported_embedding_override_provider_ids() -> set[str]:
    supported: set[str] = set()
    for spec in EMBEDDING_PROVIDER_SPECS.values():
        if spec.allow_browser_override:
            supported.add(spec.id)
            supported.update(spec.aliases)
    return supported


def embedding_provider_from_endpoint(endpoint: str) -> str:
    normalized = str(endpoint or "").lower()
    if "dashscope.aliyuncs.com" in normalized:
        return "qwen"
    if "api.openai.com" in normalized:
        return "openai"
    return "openai_compatible"
