"""Short-lived cache for resume upload parsing results.

The cache stores structured parser output, not full uploaded files. It is
fail-open by design: Redis outages should make uploads slower, never fail.
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from typing import Any, Literal

from app.core.logging import get_logger
from app.core.settings import get_settings

log = get_logger(__name__)

PARSER_VERSION = "2026-04-27-v1"
_DENY_CACHE_REASONS = {"timeout", "llm_failed"}


@dataclass(frozen=True)
class ResumeParseCacheHit:
    payload: dict[str, Any]
    age_ms: int


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _clean_config(config: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(config, dict):
        return {}
    return {
        key: value
        for key, value in config.items()
        if key != "role_overrides" and value is not None and value != ""
    }


def _effective_override(llm_override: dict[str, Any] | None) -> dict[str, Any]:
    if not llm_override:
        return {}
    default_override = _clean_config(llm_override)
    role_overrides = llm_override.get("role_overrides") or {}
    role_override = (
        role_overrides.get("resume_parser") if isinstance(role_overrides, dict) else None
    )
    if not isinstance(role_override, dict):
        return default_override
    role_config = _clean_config(role_override)
    if not default_override.get("api_key") and not role_config.get("api_key"):
        return {}
    merged = dict(default_override)
    base_provider = merged.get("provider")
    role_provider = role_config.get("provider")
    if role_provider and role_provider != base_provider and not role_config.get("base_url"):
        merged.pop("base_url", None)
    merged.update(role_config)
    return merged


def _base_url_for(provider: str, override: dict[str, Any], settings: Any) -> str:
    if override.get("base_url"):
        return str(override["base_url"])
    if provider in {"qwen", "dashscope"}:
        return "https://dashscope.aliyuncs.com/compatible-mode/v1"
    if provider == "deepseek":
        return str(getattr(settings, "deepseek_base_url", "https://api.deepseek.com/v1"))
    return ""


def effective_llm_fingerprint(llm_override: dict[str, Any] | None) -> dict[str, Any]:
    """Return non-secret model routing inputs that affect parser output."""
    settings = get_settings()
    override = _effective_override(llm_override)
    provider = str(override.get("provider") or settings.llm_provider)
    model = str(
        override.get("model")
        or getattr(settings, "llm_model_per_agent", {}).get("resume_parser")
        or settings.llm_model
    )
    temperature = override.get("temperature")
    if temperature is None:
        temperature = 0.1
    return {
        "provider": provider,
        "model": model,
        "base_url": _base_url_for(provider, override, settings),
        "temperature": float(temperature),
        "stub": bool(settings.use_stub_llm and not override.get("api_key")),
    }


def resume_parse_cache_key(
    *,
    text: str,
    filename: str | None,
    llm_override: dict[str, Any] | None,
) -> str:
    material = {
        "parser_version": PARSER_VERSION,
        "text_sha256": _sha256(text),
        "filename_sha256": _sha256(filename or ""),
        "llm": effective_llm_fingerprint(llm_override),
    }
    encoded = json.dumps(material, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return _sha256(encoded)


def should_cache_resume_parse(payload: dict[str, Any]) -> bool:
    status = payload.get("parse_status")
    if not isinstance(status, dict):
        return False
    reason = str(status.get("reason") or "")
    return reason not in _DENY_CACHE_REASONS


def _payload_for_storage(payload: dict[str, Any]) -> dict[str, Any]:
    out = dict(payload)
    out.pop("raw_text_preview", None)
    status = out.get("parse_status")
    if isinstance(status, dict):
        clean_status = dict(status)
        clean_status.pop("cached", None)
        clean_status.pop("cache_age_ms", None)
        out["parse_status"] = clean_status
    return out


class RedisResumeParseCache:
    def __init__(
        self,
        *,
        redis_client: Any | None = None,
        ttl_seconds: int,
        prefix: str,
        redis_url: str | None = None,
    ) -> None:
        self._redis_client = redis_client
        self._redis_url = redis_url
        self._ttl_seconds = max(1, int(ttl_seconds))
        self._prefix = prefix.rstrip(":")

    def _redis(self) -> Any:
        if self._redis_client is not None:
            return self._redis_client
        from redis import Redis

        self._redis_client = Redis.from_url(
            self._redis_url or get_settings().redis_url,
            decode_responses=True,
        )
        return self._redis_client

    def _key(self, cache_key: str) -> str:
        return f"{self._prefix}:v1:{cache_key}"

    def get(self, cache_key: str) -> ResumeParseCacheHit | None:
        try:
            raw = self._redis().get(self._key(cache_key))
            if not raw:
                return None
            wrapper = json.loads(raw)
            if not isinstance(wrapper, dict) or not isinstance(wrapper.get("payload"), dict):
                return None
            created_at = float(wrapper.get("created_at") or time.time())
            age_ms = max(0, int((time.time() - created_at) * 1000))
            return ResumeParseCacheHit(payload=dict(wrapper["payload"]), age_ms=age_ms)
        except Exception as e:
            log.warning("resume parse redis cache get failed: %s", e)
            return None

    def set(self, cache_key: str, payload: dict[str, Any]) -> None:
        try:
            wrapper = {
                "created_at": time.time(),
                "payload": _payload_for_storage(payload),
            }
            raw = json.dumps(wrapper, ensure_ascii=False, separators=(",", ":"))
            self._redis().setex(self._key(cache_key), self._ttl_seconds, raw)
        except Exception as e:
            log.warning("resume parse redis cache set failed: %s", e)


class MemoryResumeParseCache:
    def __init__(self, *, ttl_seconds: int) -> None:
        self._ttl_seconds = max(1, int(ttl_seconds))
        self._values: dict[str, tuple[float, dict[str, Any]]] = {}

    def get(self, cache_key: str) -> ResumeParseCacheHit | None:
        item = self._values.get(cache_key)
        if not item:
            return None
        created_at, payload = item
        age = time.time() - created_at
        if age > self._ttl_seconds:
            self._values.pop(cache_key, None)
            return None
        return ResumeParseCacheHit(payload=dict(payload), age_ms=max(0, int(age * 1000)))

    def set(self, cache_key: str, payload: dict[str, Any]) -> None:
        self._values[cache_key] = (time.time(), _payload_for_storage(payload))


_cache: RedisResumeParseCache | MemoryResumeParseCache | None = None
_cache_kind: Literal["redis", "memory", "off"] | None = None


def get_resume_parse_cache() -> RedisResumeParseCache | MemoryResumeParseCache | None:
    global _cache, _cache_kind
    settings = get_settings()
    backend = "off"
    if getattr(settings, "resume_parse_cache_enabled", True):
        backend = getattr(settings, "resume_parse_cache_backend", "redis")
    if backend == "off":
        return None
    if _cache is not None and _cache_kind == backend:
        return _cache
    ttl = int(getattr(settings, "resume_parse_cache_ttl_seconds", 86400))
    if backend == "memory":
        _cache = MemoryResumeParseCache(ttl_seconds=ttl)
        _cache_kind = "memory"
        return _cache
    if backend == "redis":
        _cache = RedisResumeParseCache(
            ttl_seconds=ttl,
            prefix=getattr(
                settings,
                "resume_parse_cache_redis_prefix",
                "agentic_interviewer:resume_parse",
            ),
            redis_url=getattr(settings, "redis_url", None),
        )
        _cache_kind = "redis"
        return _cache
    return None


def reset_resume_parse_cache_for_tests() -> None:
    global _cache, _cache_kind
    _cache = None
    _cache_kind = None
