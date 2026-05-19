"""Request-scoped ASR/TTS routing helpers.

Voice routes are resolved at call time so a browser-provided BYOK
``llm_config`` can power one interview session even when the backend
default environment is unavailable. Text LLM routing and voice routing
stay separate: voice keys inherit only from a top-level config with the
same provider.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

VoiceProviderId = Literal["qwen", "openai", "stub"]

QWEN_REALTIME_BASE_URL = "wss://dashscope.aliyuncs.com/api-ws/v1/realtime"
QWEN_ASR_MODEL = "qwen3-asr-flash-realtime"
QWEN_TTS_MODEL = "qwen3-tts-flash-realtime"
QWEN_TTS_VOICE = "Cherry"
OPENAI_ASR_MODEL = "whisper-1"
OPENAI_TTS_MODEL = "gpt-4o-mini-tts"
OPENAI_TTS_VOICE = "alloy"


@dataclass(frozen=True)
class VoiceRoute:
    provider: VoiceProviderId
    api_key: str | None
    model: str
    base_url: str | None = None
    voice: str | None = None

    @property
    def is_stub(self) -> bool:
        return self.provider == "stub" or not self.api_key


def _clean(value: Any) -> str | None:
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return None


def normalize_voice_provider(value: Any) -> VoiceProviderId | None:
    provider = _clean(value)
    if provider == "dashscope":
        return "qwen"
    if provider in {"qwen", "openai", "stub"}:
        return provider
    return None


def _provider_defaults(provider: VoiceProviderId, kind: Literal["asr", "tts"]) -> dict[str, str]:
    if provider == "qwen":
        return {
            "model": QWEN_ASR_MODEL if kind == "asr" else QWEN_TTS_MODEL,
            "base_url": QWEN_REALTIME_BASE_URL,
            "voice": QWEN_TTS_VOICE,
        }
    if provider == "openai":
        return {
            "model": OPENAI_ASR_MODEL if kind == "asr" else OPENAI_TTS_MODEL,
            "base_url": "",
            "voice": OPENAI_TTS_VOICE,
        }
    return {"model": "", "base_url": "", "voice": ""}


def _voice_override(
    llm_config: dict[str, Any] | None,
    kind: Literal["asr", "tts"],
) -> dict[str, Any] | None:
    if not isinstance(llm_config, dict):
        return None
    voice_overrides = llm_config.get("voice_overrides")
    if not isinstance(voice_overrides, dict):
        return None
    override = voice_overrides.get(kind)
    return override if isinstance(override, dict) else None


def _top_level_same_provider(
    llm_config: dict[str, Any] | None,
    provider: VoiceProviderId,
) -> dict[str, str | None]:
    if provider == "stub" or not isinstance(llm_config, dict):
        return {}
    top_provider = normalize_voice_provider(llm_config.get("provider"))
    if top_provider != provider:
        return {}
    api_key = _clean(llm_config.get("api_key"))
    if not api_key:
        return {}
    return {
        "api_key": api_key,
        "base_url": _clean(llm_config.get("base_url")),
    }


def _env_same_provider(owner: Any, provider: VoiceProviderId) -> dict[str, str | None]:
    if provider == "stub":
        return {}
    env_provider = normalize_voice_provider(getattr(owner, "provider", None)) or normalize_voice_provider(
        getattr(owner, "llm_provider", None)
    )
    if env_provider != provider:
        return {}
    api_key: str | None
    base_url: str | None
    if provider == "qwen":
        api_key = (
            _clean(getattr(owner, "qwen_api_key", None))
            or _clean(getattr(owner, "dashscope_api_key", None))
            or _clean(getattr(owner, "openai_api_key", None))
        )
        base_url = _clean(getattr(owner, "qwen_realtime_base_url", None)) or QWEN_REALTIME_BASE_URL
    else:
        api_key = _clean(getattr(owner, "openai_api_key", None))
        base_url = _clean(getattr(owner, "openai_base_url", None))
    if not api_key:
        return {}
    return {"api_key": api_key, "base_url": base_url}


def _legacy_existing_openai_client(owner: Any) -> dict[str, str | None]:
    if (
        getattr(owner, "_client", None) is not None
        and getattr(owner, "stub", True) is False
    ):
        owner_provider = normalize_voice_provider(getattr(owner, "provider", None))
        if owner_provider not in {None, "stub"} and owner_provider != "openai":
            return {}
        return {
            "api_key": "existing-client",
            "base_url": _clean(getattr(owner, "openai_base_url", None)),
        }
    return {}


def _default_provider(
    owner: Any,
    llm_config: dict[str, Any] | None,
) -> VoiceProviderId:
    if isinstance(llm_config, dict) and _clean(llm_config.get("api_key")):
        top_provider = normalize_voice_provider(llm_config.get("provider"))
        if top_provider in {"qwen", "openai"}:
            return top_provider
    if getattr(owner, "_client", None) is not None and getattr(owner, "stub", True) is False:
        return "openai"
    configured = normalize_voice_provider(getattr(owner, "provider", None))
    if configured and configured != "stub":
        return configured
    env_provider = normalize_voice_provider(getattr(owner, "llm_provider", None))
    if env_provider and env_provider != "stub":
        return env_provider
    return "qwen"


def _default_model(owner: Any, provider: VoiceProviderId, kind: Literal["asr", "tts"]) -> str:
    configured = _clean(getattr(owner, "model", None))
    if configured:
        return configured
    return _provider_defaults(provider, kind)["model"]


def _resolve_route(
    owner: Any,
    kind: Literal["asr", "tts"],
    llm_config: dict[str, Any] | None,
) -> VoiceRoute:
    override = _voice_override(llm_config, kind)
    provider = normalize_voice_provider(override.get("provider")) if override is not None else None
    provider = provider or _default_provider(owner, llm_config)
    defaults = _provider_defaults(provider, kind)
    model = (
        _clean(override.get("model")) if override is not None else None
    ) or _default_model(owner, provider, kind)
    voice = None
    if kind == "tts":
        owner_voice = _clean(getattr(owner, "voice", None))
        voice = (
            _clean(override.get("voice")) if override is not None else None
        ) or owner_voice or defaults["voice"]

    top_level = _top_level_same_provider(llm_config, provider)
    env_route = _env_same_provider(owner, provider)
    legacy = _legacy_existing_openai_client(owner) if llm_config is None and provider == "openai" else {}
    api_key = (
        (_clean(override.get("api_key")) if override is not None else None)
        or top_level.get("api_key")
        or legacy.get("api_key")
        or env_route.get("api_key")
    )
    base_url = (
        (_clean(override.get("base_url")) if override is not None else None)
        or top_level.get("base_url")
        or legacy.get("base_url")
        or env_route.get("base_url")
        or defaults["base_url"]
        or None
    )
    if not api_key:
        return VoiceRoute(provider="stub", api_key=None, model=model, voice=voice, base_url=base_url)
    return VoiceRoute(provider=provider, api_key=api_key, model=model, voice=voice, base_url=base_url)


def resolve_asr_route(
    owner: Any,
    llm_config: dict[str, Any] | None = None,
) -> VoiceRoute:
    return _resolve_route(owner, "asr", llm_config)


def resolve_tts_route(
    owner: Any,
    llm_config: dict[str, Any] | None = None,
) -> VoiceRoute:
    return _resolve_route(owner, "tts", llm_config)
