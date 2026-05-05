"""User-facing LLM configuration checks.

The endpoint in this module validates browser-supplied BYOK settings
with a tiny non-persisted provider request. It deliberately does not
use the admin token gate: this is part of the normal setup flow, not an
operator-only observability surface.
"""
from __future__ import annotations

import time

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from app.core.api_errors import api_error_detail
from app.core.llm_config_schema import (
    LLM_API_KEY_MAX_LENGTH,
    LLM_BASE_URL_MAX_LENGTH,
    LLM_MODEL_MAX_LENGTH,
    LLMProvider,
)
from app.core.metrics import record_rate_limit_block
from app.core.rate_limit import RateLimitExceededError, check_rate_limit
from app.core.settings import get_settings
from app.engine.agents.llm_client import (
    ChatMessage,
    LLMError,
    LLMFatal,
    _invoke_provider,
    classify_llm_error_kind,
    redact_llm_secrets,
    validate_llm_base_url,
)

router = APIRouter(prefix="/api/v1/llm", tags=["llm"])


class LLMTestRequest(BaseModel):
    provider: LLMProvider
    api_key: str = Field(min_length=1, max_length=LLM_API_KEY_MAX_LENGTH)
    model: str = Field(min_length=1, max_length=LLM_MODEL_MAX_LENGTH)
    temperature: float | None = Field(default=None, ge=0, le=2)
    base_url: str | None = Field(default=None, max_length=LLM_BASE_URL_MAX_LENGTH)

    @field_validator("api_key", "model", "base_url", mode="before")
    @classmethod
    def _strip_string(cls, value: str | None) -> str | None:
        if isinstance(value, str):
            return value.strip()
        return value


def _latency_ms(start: float) -> int:
    return max(0, int((time.perf_counter() - start) * 1000))


def _rate_limit_client_key(request: Request, endpoint: str) -> str:
    host = request.client.host if request.client else "unknown"
    return f"{endpoint}:{host}"


def _enforce_rate_limit(request: Request) -> None:
    settings = get_settings()
    try:
        check_rate_limit(
            _rate_limit_client_key(request, "llm_test"),
            limit=settings.llm_test_rate_limit_per_minute,
            window_seconds=settings.rate_limit_window_seconds,
        )
    except RateLimitExceededError as e:
        record_rate_limit_block("llm_test")
        raise HTTPException(
            status_code=429,
            detail=api_error_detail(
                "rate_limit_exceeded",
                "请求过于频繁，请稍后再试。",
                "retry_later",
            ),
            headers={"Retry-After": str(e.retry_after_seconds)},
        ) from e


@router.post("/test")
def test_llm_connection(req: LLMTestRequest, request: Request) -> dict[str, object]:
    """Verify a provider key with a minimal chat-completions request."""
    _enforce_rate_limit(request)
    if req.provider == "openai_compatible" and not req.base_url:
        raise HTTPException(
            status_code=422,
            detail=api_error_detail(
                "llm_base_url_required",
                "自定义 OpenAI-Compatible 服务需要填写 Base URL。",
                "edit_base_url",
                error_kind="misconfig",
                error="provider=openai_compatible requires base_url",
            ),
        )
    if req.base_url:
        try:
            validate_llm_base_url(req.base_url)
        except LLMFatal as e:
            raise HTTPException(
                status_code=422,
                detail=api_error_detail(
                    "llm_base_url_invalid",
                    "Base URL 指向的地址不被允许，请换成公网模型服务地址。",
                    "edit_base_url",
                    error_kind="misconfig",
                    error=str(e),
                ),
            ) from e

    started = time.perf_counter()
    override = {
        "provider": req.provider,
        "api_key": req.api_key,
        "model": req.model,
        **({"base_url": req.base_url} if req.base_url else {}),
    }
    try:
        message = _invoke_provider(
            [ChatMessage(role="user", content="Reply with pong.")],
            model=req.model,
            temperature=0.0,
            max_tokens=8,
            json_mode=False,
            override=override,
        )
    except LLMError as e:
        return {
            "ok": False,
            "provider": req.provider,
            "model": req.model,
            "latency_ms": _latency_ms(started),
            "error_kind": classify_llm_error_kind(e),
            "error": redact_llm_secrets(str(e), override),
        }
    except Exception as e:  # pragma: no cover - SDKs vary their exception classes
        return {
            "ok": False,
            "provider": req.provider,
            "model": req.model,
            "latency_ms": _latency_ms(started),
            "error_kind": classify_llm_error_kind(e),
            "error": redact_llm_secrets(str(e), override),
        }

    return {
        "ok": True,
        "provider": req.provider,
        "model": req.model,
        "latency_ms": _latency_ms(started),
        "message": message,
    }
