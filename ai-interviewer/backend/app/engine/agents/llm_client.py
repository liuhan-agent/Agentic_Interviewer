"""Thin LLM wrapper that supports multiple providers and a stub mode.

Providers are intentionally hidden behind a tiny ``call_chat`` helper so
nodes/agents don't import provider SDKs directly. ``stub`` mode returns
deterministic fixtures, which is essential for CI, tests, and anyone
running the demo without API keys.

Resilience
----------
``call_chat`` wraps every real provider call with a
``tenacity``-driven retry loop that targets transient failures only
(rate limits, timeouts, 5xx / connection resets).  Deterministic
``LLMError`` subclasses — :class:`LLMRateLimit`,
:class:`LLMTransient`, :class:`LLMFatal` — let the caller decide
whether to degrade or propagate.  The retry budget is tunable via
``settings.llm_max_retries`` so unit tests that rely on exact call
counts can set it to 0.

Providers
---------
- ``openai``   : OpenAI Chat Completions.
- ``anthropic``: Claude Messages API, with optional prompt-cache
  markers on the system block.
- ``deepseek`` : DeepSeek Chat Completions (OpenAI-wire-compatible;
  we reuse the OpenAI SDK pointed at the DeepSeek base URL).
- ``stub``     : deterministic local responses, no network.
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import re
import socket
import threading
import time
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import urlparse

from app.core.logging import get_logger
from app.core.metrics import record_llm_call
from app.core.settings import get_settings
from app.core.timing import record_llm_timing_event

log = get_logger(__name__)

from app.core.roles import AgentRole as AgentCallRole  # noqa: E402 — re-export for back-compat

Role = Literal["system", "user", "assistant", "tool"]
CacheHint = Literal["ephemeral"]

LLMErrorKind = Literal[
    "auth",
    "quota",
    "rate_limit",
    "timeout",
    "network",
    "misconfig",
    "unknown",
]


@dataclass
class ChatMessage:
    role: Role
    content: str
    tool_call_id: str | None = None
    name: str | None = None
    # Provider-specific cache hint. Only ``_call_anthropic`` honours
    # this today; the value is intentionally NOT serialised through
    # :meth:`to_dict` because OpenAI / DeepSeek would reject an unknown
    # per-message key. ``"ephemeral"`` maps to Anthropic's
    # ``cache_control: {"type": "ephemeral"}`` block-level marker.
    cache_control: CacheHint | None = None

    def to_dict(self) -> dict[str, Any]:
        raw = getattr(self, "_raw_dict", None)
        if raw is not None:
            return raw
        d: dict[str, Any] = {"role": self.role, "content": self.content}
        if self.tool_call_id is not None:
            d["tool_call_id"] = self.tool_call_id
        if self.name is not None:
            d["name"] = self.name
        return d


class LLMError(RuntimeError):
    """Base class for provider-side LLM failures."""


# The ``Error`` suffix is intentionally omitted from the three subclasses
# below (hence the ``noqa: N818``): they are public API used as
# ``except LLMRateLimit`` / ``except LLMTransient`` / ``except LLMFatal``
# throughout the codebase, and the shorter names read as a severity
# taxonomy rather than generic error classes.
class LLMRateLimit(LLMError):  # noqa: N818
    """Provider returned an HTTP 429 or equivalent rate-limit error."""


class LLMTransient(LLMError):  # noqa: N818
    """Provider raised a transient error (timeouts, 5xx, reset)."""


class LLMFatal(LLMError):  # noqa: N818
    """Unrecoverable error: bad credentials, malformed request, etc."""


# ---------------------------------------------------------------------------
# Provider SDK client cache
# ---------------------------------------------------------------------------
# Each ``OpenAI()`` / ``Anthropic()`` instance owns its own httpx client
# with a connection pool, TLS handshake state, and DNS cache. Building a
# new client for every ``call_chat`` (the previous behaviour) discarded
# all of that work each call - 30~80ms of wasted overhead per request
# under sustained traffic. We cache one instance per
# ``(api_key, base_url, ...)`` tuple instead, mirroring the pattern that
# ``WhisperASR`` already uses in ``app.voice.asr``.
#
# Cache keys deliberately include every constructor argument that
# influences SDK behaviour (api_key + base_url for routing & auth,
# timeout + max_retries because they bind to the underlying httpx
# transport). Anything that varies per request - the message body,
# temperature, max_tokens, json_mode - is passed at call time on
# ``client.chat.completions.create`` and never enters the key.
_OPENAI_CLIENT_CACHE: dict[tuple[Any, ...], Any] = {}
_ANTHROPIC_CLIENT_CACHE: dict[tuple[Any, ...], Any] = {}
_CLIENT_CACHE_LOCK = threading.Lock()


def _new_sdk_http_client(*, timeout: float | None = None) -> Any:
    import httpx

    kwargs: dict[str, Any] = {"trust_env": False}
    if timeout is not None:
        kwargs["timeout"] = timeout
    return httpx.Client(**kwargs)


def _get_openai_client(
    *,
    api_key: str,
    base_url: str | None,
    timeout: float,
    max_retries: int,
) -> Any:
    """Return a cached ``openai.OpenAI`` instance, building on cache miss.

    Importing the SDK lazily preserves the original behaviour of failing
    only when an OpenAI-flavoured provider is actually invoked, so a
    pure-stub install can still import this module without ``openai``.
    """
    from openai import OpenAI

    key = (api_key or "", base_url or "", timeout, max_retries)
    with _CLIENT_CACHE_LOCK:
        client = _OPENAI_CLIENT_CACHE.get(key)
        if client is None:
            http_client = _new_sdk_http_client(timeout=timeout)
            try:
                client = OpenAI(
                    api_key=api_key,
                    base_url=base_url,
                    timeout=timeout,
                    max_retries=max_retries,
                    http_client=http_client,
                )
            except Exception:
                http_client.close()
                raise
            _OPENAI_CLIENT_CACHE[key] = client
        return client


def _drop_openai_client(
    *,
    api_key: str,
    base_url: str | None,
    timeout: float,
    max_retries: int,
) -> None:
    """Remove one cached OpenAI SDK client and close its transport."""
    key = (api_key or "", base_url or "", timeout, max_retries)
    with _CLIENT_CACHE_LOCK:
        client = _OPENAI_CLIENT_CACHE.pop(key, None)
    close = getattr(client, "close", None)
    if callable(close):
        try:
            close()
        except Exception as exc:  # pragma: no cover - best-effort cleanup
            log.debug("openai client close skipped after cache drop: %s", exc)


def _get_anthropic_client(
    *,
    api_key: str,
    base_url: str | None,
) -> Any:
    """Return a cached ``anthropic.Anthropic`` instance.

    Anthropic's SDK does not expose ``timeout`` / ``max_retries`` to
    constructor in the same way OpenAI's does (we set them via
    ``client.with_options`` per call when needed), so the key is the
    smaller ``(api_key, base_url)`` pair.
    """
    from anthropic import Anthropic

    key = (api_key or "", base_url or "")
    with _CLIENT_CACHE_LOCK:
        client = _ANTHROPIC_CLIENT_CACHE.get(key)
        if client is None:
            http_client = _new_sdk_http_client()
            try:
                client = Anthropic(
                    api_key=api_key,
                    base_url=base_url,
                    http_client=http_client,
                )
            except Exception:
                http_client.close()
                raise
            _ANTHROPIC_CLIENT_CACHE[key] = client
        return client


def _reset_client_cache_for_tests() -> None:
    """Drop every cached SDK client. Tests use this in fixtures to keep
    each case isolated; production callers must never invoke it because
    in-flight requests on dropped clients still complete normally but
    their connection pools are abandoned."""
    with _CLIENT_CACHE_LOCK:
        clients = [*_OPENAI_CLIENT_CACHE.values(), *_ANTHROPIC_CLIENT_CACHE.values()]
        _OPENAI_CLIENT_CACHE.clear()
        _ANTHROPIC_CLIENT_CACHE.clear()
    for client in clients:
        close = getattr(client, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                pass


def _classify_exception(exc: Exception) -> type[LLMError]:
    """Best-effort mapping from SDK exceptions to our error taxonomy.

    We avoid hard-coding SDK class imports because openai / anthropic
    package versions move: string matching on the class name keeps
    the classifier stable across major releases.
    """
    name = exc.__class__.__name__.lower()
    msg = str(exc).lower()
    if "rate" in name or "ratelimit" in name or "429" in msg:
        return LLMRateLimit
    if (
        "timeout" in name
        or "timeout" in msg
        or "apiconnection" in name
        or "apierror" in name
        or "internalserver" in name
        or "service" in name
        or re.match(r"5\d{2}\b", msg)
    ):
        return LLMTransient
    return LLMFatal


def _classify_error_text(text: str) -> LLMErrorKind:
    blob = text.lower()
    if any(
        token in blob
        for token in (
            "invalid api key",
            "api key invalid",
            "incorrect api key",
            "authentication",
            "unauthorized",
            "forbidden",
            "permission denied",
            "not authorized",
            "401",
            "403",
        )
    ):
        return "auth"
    if any(
        token in blob
        for token in (
            "quota",
            "insufficient_quota",
            "billing",
            "balance",
            "credit",
            "credits",
        )
    ):
        return "quota"
    if any(
        token in blob
        for token in (
            "rate limit",
            "ratelimit",
            "too many requests",
            "429",
        )
    ):
        return "rate_limit"
    if any(token in blob for token in ("timeout", "timed out")):
        return "timeout"
    if any(
        token in blob
        for token in (
            "network",
            "connection",
            "failed to fetch",
            "fetch",
            "dns",
            "proxy",
            "socksio",
            "socket",
            "websocket",
            "realtime",
            "session",
            "handshake",
            "reset by peer",
            "service unavailable",
            "gateway",
            "502",
            "503",
            "504",
        )
    ):
        return "network"
    if any(
        token in blob
        for token in (
            "base_url",
            "base url",
            "requires a base_url",
            "unsupported provider",
            "openai package is required",
            "anthropic package is required",
            "malformed",
            "bad request",
        )
    ):
        return "misconfig"
    return "unknown"


def classify_llm_error_kind(exc: BaseException | str | None) -> LLMErrorKind:
    """Best-effort user-facing taxonomy for provider failures."""
    if exc is None:
        return "unknown"

    if isinstance(exc, LLMRateLimit):
        return "rate_limit"

    if isinstance(exc, LLMTransient):
        text = str(exc).lower()
        if "timeout" in text or "timed out" in text:
            return "timeout"
        return "network"

    if isinstance(exc, LLMFatal):
        kind = _classify_error_text(str(exc))
        if kind != "unknown":
            return kind

    if isinstance(exc, BaseException):
        chain: list[BaseException] = []
        current: BaseException | None = exc
        while current is not None and current not in chain:
            chain.append(current)
            current = current.__cause__ or current.__context__
        for item in chain[1:]:
            kind = classify_llm_error_kind(item)
            if kind != "unknown":
                return kind
        return _classify_error_text(f"{exc.__class__.__name__}: {exc}")

    return _classify_error_text(exc)


def _evict_openai_client_after_provider_error(
    exc: BaseException,
    *,
    api_key: str,
    base_url: str | None,
    timeout: float,
    max_retries: int,
) -> None:
    """Drop cached OpenAI-compatible clients after transport failures."""
    if classify_llm_error_kind(exc) not in {"network", "timeout"}:
        return
    _drop_openai_client(
        api_key=api_key,
        base_url=base_url,
        timeout=timeout,
        max_retries=max_retries,
    )


def redact_llm_secrets(text: str, config: dict[str, Any] | None = None) -> str:
    """Remove API keys from provider error text before it reaches clients/logs."""
    if not text or not config:
        return text

    secrets: set[str] = set()

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if key == "api_key" and isinstance(item, str) and item:
                    secrets.add(item)
                else:
                    walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(config)
    redacted = text
    for secret in sorted(secrets, key=len, reverse=True):
        redacted = redacted.replace(secret, "[redacted-api-key]")
    return redacted


def _prompt_json_assignment(prompt: str, label: str) -> Any:
    match = re.search(rf"^{re.escape(label)}\s*=\s*(.+)$", prompt, re.MULTILINE)
    if not match:
        return None
    try:
        return json.loads(match.group(1).strip())
    except json.JSONDecodeError:
        return None


def _prompt_scalar_assignment(prompt: str, label: str) -> str:
    match = re.search(rf"^{re.escape(label)}\s*=\s*(.+)$", prompt, re.MULTILINE)
    return match.group(1).strip() if match else ""


def _prompt_generator_dimension(prompt: str) -> str:
    match = re.search(r'"dimension"\s*:\s*"([^"]+)"', prompt)
    return match.group(1).strip() if match else "general"


def _stub_generator_response(
    *,
    digest: str,
    prompt: str,
) -> str:
    dimension = _prompt_generator_dimension(prompt)
    target_skills = _prompt_json_assignment(prompt, "TARGET_SKILLS")
    if not isinstance(target_skills, list):
        target_skills = []
    target_skills = [str(skill).strip() for skill in target_skills if str(skill).strip()]
    resume_anchor = _prompt_json_assignment(prompt, "RESUME_ANCHOR")
    if not isinstance(resume_anchor, dict):
        resume_anchor = {}
    difficulty = _prompt_scalar_assignment(prompt, "TARGET_DIFFICULTY") or "medium"
    if difficulty not in {"easy", "medium", "hard"}:
        difficulty = "medium"

    project = (
        str(resume_anchor.get("project_name") or resume_anchor.get("label") or "").strip()
        or "简历中的一个项目"
    )
    skill_phrase = "、".join(target_skills[:3]) or "主要技术选择"
    dimension_label = {
        "technical_depth": "技术深度",
        "system_design": "系统设计",
        "coding_quality": "代码质量",
        "project_experience": "项目经验",
        "problem_solving": "问题解决",
    }.get(dimension, dimension.replace("_", " "))
    templates = {
        "technical_depth": (
            f"请结合「{project}」，讲一个围绕「{skill_phrase}」的技术挑战。"
            "你自己具体实现了哪些部分，当时做过哪些取舍，最后是怎么验证效果的？"
        ),
        "system_design": (
            f"请结合「{project}」，讲一个你主导或深度参与的系统设计决策。"
            "当时比较过哪些方案，最关键的取舍是什么，上线后效果如何？"
        ),
        "coding_quality": (
            f"在「{project}」里，挑一个和「{skill_phrase}」有关、代码质量比较关键的部分。"
            "你当时如何保证可维护性？如果现在重做，会优先改进什么？"
        ),
        "project_experience": (
            f"请讲讲你在「{project}」里的角色，重点说说和「{skill_phrase}」相关的工作。"
            "目标是什么，你交付了什么，最后有没有可观察或可量化的结果？"
        ),
        "problem_solving": (
            f"请结合「{project}」，讲一个和「{skill_phrase}」有关的棘手问题。"
            "你是怎么定位原因、选择解决路径，并确认问题真的解决的？"
        ),
    }
    question = templates.get(
        dimension,
        (
            f"请结合「{project}」，聊聊你在「{dimension_label}」方面和「{skill_phrase}」相关的经历。"
            "当时遇到什么问题，你做了哪些选择，最后结果怎么样？"
        ),
    )
    bar_level = {
        "easy": "intro",
        "medium": "standard",
        "hard": "deep_probe",
    }[difficulty]
    return json.dumps(
        {
            "_stub": True,
            "_digest": digest,
            "question": question,
            "dimension": dimension,
            "difficulty": difficulty,
            "rationale": "stub 生成器基于当前提示中的维度、简历锚点和技能焦点生成问题",
            "rubric_points": [dimension_label, "具体例子", "方案取舍"],
            "proposed_contract": {
                "must_cover": [dimension_label, "具体例子", "方案取舍"],
                "acceptable_if_missing": [],
                "acceptance_checks": [
                    f"回答能结合「{project}」展开。",
                    f"回答覆盖「{skill_phrase}」相关内容。",
                    "回答解释至少一个技术取舍或关键决策。",
                ],
                "minimum_bar": "至少给出一个具体例子，并说明自己的决策和结果。",
                "review_focus": ["具体性", "个人贡献", "取舍推理"],
                "bar_level": bar_level,
            },
        },
        ensure_ascii=False,
    )


def _stub_response(
    messages: list[ChatMessage],
    *,
    json_mode: bool,
    agent_role: AgentCallRole | None = None,
) -> str:
    """Deterministic fake response keyed on message hash.

    For ``json_mode`` we emit a tiny JSON doc that is still valid for
    the downstream parsing expectations of the graph nodes. This means
    the hello-world loop can run end-to-end without any API access.
    """
    digest = hashlib.sha1(
        json.dumps([m.to_dict() for m in messages], ensure_ascii=False).encode("utf-8")
    ).hexdigest()[:6]
    last_user = next((m.content for m in reversed(messages) if m.role == "user"), "")
    if json_mode:
        if agent_role == "generator":
            return _stub_generator_response(digest=digest, prompt=last_user)
        return json.dumps(
            {
                "_stub": True,
                "_digest": digest,
                "summary": f"stub-reply-to: {last_user[:60]}",
                "score": 7.5,
                "strengths": ["回答结构清晰，能围绕核心方案展开"],
                "weaknesses": ["还可以补充更具体的线上数据或复盘结果"],
                "followup": "请结合一次真实线上场景，继续说明你的取舍和结果。",
                "question": "请讲一个你设计过的系统，并说明当时的关键取舍。",
                "dimension": "system_design",
                "rubric_points": ["clarity", "trade_offs", "scale_reasoning"],
            },
            ensure_ascii=False,
        )
    return (
        f"[stub:{digest}] I heard: {last_user[:80]}. "
        "This is a deterministic fake reply used when no LLM key is configured."
    )


# Default base_url per OpenAI-compatible provider. The frontend
# normally supplies ``base_url`` in the BYOK payload; this map is the
# server-side fallback so a missing ``base_url`` still routes
# correctly when the operator only set ``LLM_PROVIDER=moonshot`` in
# ``.env``.
_OPENAI_COMPATIBLE_DEFAULT_BASE_URLS: dict[str, str] = {
    "moonshot": "https://api.moonshot.cn/v1",
    "kimi": "https://api.moonshot.cn/v1",
    "qwen": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "dashscope": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "zhipu": "https://open.bigmodel.cn/api/paas/v4/",
    "mistral": "https://api.mistral.ai/v1",
    "xiaomimimo": "https://api.xiaomimimo.com/v1",
}


_BLOCKED_BASE_URL_HOSTS = {"localhost", "localhost.localdomain"}
_FAKE_IP_NETWORKS = (
    ipaddress.ip_network("198.18.0.0/15"),
)
_FAKE_IP_ALLOWED_LLM_HOST_SUFFIXES = (
    "deepseek.com",
    "moonshot.cn",
    "dashscope.aliyuncs.com",
    "dashscope-intl.aliyuncs.com",
    "bigmodel.cn",
    "mistral.ai",
    "xiaomimimo.com",
)


def _is_blocked_base_url_ip(raw_ip: str) -> bool:
    try:
        ip = ipaddress.ip_address(raw_ip)
    except ValueError:
        return False
    return (
        ip.is_loopback
        or ip.is_private
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def _is_fake_ip(raw_ip: str) -> bool:
    try:
        ip = ipaddress.ip_address(raw_ip)
    except ValueError:
        return False
    return any(ip in network for network in _FAKE_IP_NETWORKS)


def _is_fake_ip_allowed_llm_host(host: str) -> bool:
    return any(
        host == suffix or host.endswith(f".{suffix}")
        for suffix in _FAKE_IP_ALLOWED_LLM_HOST_SUFFIXES
    )


def validate_llm_base_url(base_url: str) -> None:
    """Reject OpenAI-compatible base URLs that can target internal networks."""
    parsed = urlparse(str(base_url).strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise LLMFatal("base_url must be an absolute http(s) URL")

    host = parsed.hostname.strip().lower()
    if host in _BLOCKED_BASE_URL_HOSTS or _is_blocked_base_url_ip(host):
        raise LLMFatal("base_url host is not allowed")

    try:
        addr_infos = socket.getaddrinfo(host, parsed.port, type=socket.SOCK_STREAM)
    except socket.gaierror:
        # Let the provider SDK surface ordinary DNS failures; the denylist still
        # catches literal private/metadata hosts before any outbound request.
        return

    for info in addr_infos:
        sockaddr = info[4]
        if not sockaddr:
            continue
        raw_ip = str(sockaddr[0])
        if _is_fake_ip(raw_ip) and _is_fake_ip_allowed_llm_host(host):
            continue
        if _is_blocked_base_url_ip(raw_ip):
            raise LLMFatal("base_url resolves to a disallowed address")


def _invoke_provider(
    messages: list[ChatMessage],
    *,
    model: str,
    temperature: float,
    max_tokens: int,
    json_mode: bool,
    override: dict[str, Any] | None = None,
    request_timeout: float | None = None,
    provider_max_retries: int | None = None,
) -> tuple[str, dict[str, Any]]:
    """Route to the configured provider after retry semantics are applied.

    Returns ``(content, usage)`` where ``usage`` is the dict produced
    by ``_extract_openai_usage`` / ``_extract_anthropic_usage``.

    When *override* is provided (BYOK per-session config), it takes
    precedence over the server-wide ``Settings``. Provider routing:

    - ``openai`` / ``anthropic`` / ``deepseek``: native adapters with
      provider-specific quirks (Anthropic system blocks, DeepSeek
      base_url default).
    - Anything in :data:`_OPENAI_COMPATIBLE_DEFAULT_BASE_URLS` keys
      (moonshot/kimi/qwen/dashscope/zhipu/mistral/xiaomimimo): routes through
      ``_call_openai_compatible`` with that vendor's default base_url.
    - ``openai_compatible`` (escape hatch): caller MUST supply
      ``base_url`` in the override; raises ``LLMFatal`` otherwise.
    """
    provider = (override or {}).get("provider") or get_settings().llm_provider
    override_base_url = (override or {}).get("base_url")
    if override_base_url:
        validate_llm_base_url(str(override_base_url))
    if provider == "openai":
        return _call_openai(
            messages,
            model,
            temperature,
            max_tokens,
            json_mode,
            override=override,
            request_timeout=request_timeout,
            provider_max_retries=provider_max_retries,
        )
    if provider == "anthropic":
        return _call_anthropic(
            messages, model, temperature, max_tokens, override=override
        )
    if provider == "deepseek":
        return _call_deepseek(
            messages,
            model,
            temperature,
            max_tokens,
            json_mode,
            override=override,
            request_timeout=request_timeout,
            provider_max_retries=provider_max_retries,
        )
    if provider in _OPENAI_COMPATIBLE_DEFAULT_BASE_URLS:
        base_url = (override or {}).get("base_url") or _OPENAI_COMPATIBLE_DEFAULT_BASE_URLS[
            provider
        ]
        return _call_openai_compatible(
            messages,
            model,
            temperature,
            max_tokens,
            json_mode,
            base_url=base_url,
            override=override,
            request_timeout=request_timeout,
            provider_max_retries=provider_max_retries,
        )
    if provider == "openai_compatible":
        base_url = (override or {}).get("base_url")
        if not base_url:
            raise LLMFatal(
                "provider=openai_compatible requires a base_url in the BYOK config"
            )
        return _call_openai_compatible(
            messages,
            model,
            temperature,
            max_tokens,
            json_mode,
            base_url=base_url,
            override=override,
            request_timeout=request_timeout,
            provider_max_retries=provider_max_retries,
        )
    raise LLMFatal(f"Unsupported provider: {provider}")


def resolve_model(
    *,
    explicit_model: str | None,
    agent_role: str | None,
    settings: Any = None,
) -> str:
    """Pick the model string for a ``call_chat`` invocation.

    Resolution order (first non-None wins):

    1. ``explicit_model`` - an override the caller passed directly.
    2. ``settings.llm_model_per_agent[agent_role]`` - per-agent map.
    3. ``settings.llm_model`` - global fallback.

    The helper is public and side-effect-free so unit tests can
    exercise the decision table without mocking the SDK clients.
    """
    if settings is None:
        settings = get_settings()
    if explicit_model is not None:
        return explicit_model
    if agent_role is not None:
        mapped = settings.llm_model_per_agent.get(agent_role)
        if mapped:
            return mapped
    return settings.llm_model


def _effective_request_timeout(
    *,
    request_timeout: float | None,
    agent_role: str | None,
    settings: Any,
) -> float:
    if request_timeout is not None:
        return request_timeout
    if agent_role == "generator":
        return float(
            getattr(
                settings,
                "generator_llm_timeout_seconds",
                settings.llm_request_timeout_seconds,
            )
        )
    if agent_role == "evaluator":
        return float(
            getattr(
                settings,
                "evaluator_llm_timeout_seconds",
                settings.llm_request_timeout_seconds,
            )
        )
    if agent_role == "verifier":
        return float(
            getattr(
                settings,
                "verifier_llm_timeout_seconds",
                settings.llm_request_timeout_seconds,
            )
        )
    if agent_role == "coach":
        return float(
            getattr(
                settings,
                "coach_llm_timeout_seconds",
                settings.llm_request_timeout_seconds,
            )
        )
    return float(settings.llm_request_timeout_seconds)


def _clean_override(config: dict[str, Any]) -> dict[str, Any]:
    """Remove empty values and internal routing metadata before SDK dispatch."""
    return {
        key: value
        for key, value in config.items()
        if key != "role_overrides" and value is not None and value != ""
    }


def _override_for_agent_role(
    override: dict[str, Any] | None,
    agent_role: str | None,
) -> dict[str, Any] | None:
    """Merge default BYOK config with the optional per-role override."""
    if not override:
        return None

    default_override = _clean_override(override)
    role_overrides = override.get("role_overrides") or {}
    role_override = (
        role_overrides.get(agent_role)
        if agent_role and isinstance(role_overrides, dict)
        else None
    )
    if not isinstance(role_override, dict):
        return default_override if default_override.get("api_key") else None

    role_config = _clean_override(role_override)
    if not default_override.get("api_key") and not role_config.get("api_key"):
        return None

    merged = default_override if default_override.get("api_key") else {}
    base_provider = merged.get("provider")
    role_provider = role_config.get("provider")
    if role_provider and role_provider != base_provider and not role_config.get("base_url"):
        # Avoid carrying a default provider's custom URL into another provider;
        # named OpenAI-compatible providers can resolve their own default URL.
        merged.pop("base_url", None)

    merged.update(role_config)
    return merged


def _base_host_for_diagnostics(
    *,
    provider: str,
    override: dict[str, Any] | None,
    settings: Any,
) -> str:
    base_url = (override or {}).get("base_url")
    if not base_url and provider in _OPENAI_COMPATIBLE_DEFAULT_BASE_URLS:
        base_url = _OPENAI_COMPATIBLE_DEFAULT_BASE_URLS[provider]
    if not base_url and provider == "deepseek":
        base_url = settings.deepseek_base_url
    if not base_url:
        return "-"
    parsed = urlparse(str(base_url))
    return parsed.netloc or str(base_url).split("/", 1)[0]


def _message_chars(messages: list[ChatMessage]) -> int:
    return sum(len(m.content or "") for m in messages)


# ---------------------------------------------------------------------------
# Token-usage extraction (PR-1: LLM cost observability)
# ---------------------------------------------------------------------------
# Each provider call returns a small ``usage`` dict alongside the raw
# assistant text. The dict carries:
#     prompt_tokens     - real or estimated tokens consumed
#     completion_tokens - real or estimated tokens produced
#     usage_estimated   - True when the provider response did not include
#                         a ``usage`` block (we fall back to ``len/4``)
# Callers should treat the dict as opaque; ``call_chat`` aggregates it
# into ``record_llm_call`` and ``record_llm_timing_event``.

# Rough chars-per-token ratio used when a provider response lacks a
# real ``usage`` block. 4 chars/token is the public OpenAI rule of
# thumb for Latin scripts; CJK answers run closer to 1.5 chars/token,
# so this estimate underreports cost on Chinese-heavy traffic — a
# conservative bias that is fine for "did we hit the budget?" alerts.
_CHAR_PER_TOKEN_ESTIMATE = 4


def _estimate_tokens_from_chars(chars: int) -> int:
    if chars <= 0:
        return 0
    return max(1, chars // _CHAR_PER_TOKEN_ESTIMATE)


def _extract_openai_usage(resp: Any, *, content: str, input_chars: int) -> dict[str, Any]:
    """Pull ``prompt_tokens`` / ``completion_tokens`` from an OpenAI-shaped reply.

    OpenAI, DeepSeek, and every OpenAI-compatible vendor that speaks
    the Chat Completions wire protocol expose ``resp.usage.prompt_tokens``
    / ``resp.usage.completion_tokens``. Some self-hosted gateways
    (LiteLLM / OneAPI) drop the field; we fall back to a char-based
    estimate so the metrics path always books *some* number.
    """
    usage_obj = getattr(resp, "usage", None)
    if usage_obj is not None:
        prompt = getattr(usage_obj, "prompt_tokens", None)
        completion = getattr(usage_obj, "completion_tokens", None)
        if prompt is None and isinstance(usage_obj, dict):
            prompt = usage_obj.get("prompt_tokens")
            completion = usage_obj.get("completion_tokens")
        if prompt is not None and completion is not None:
            return {
                "prompt_tokens": max(0, int(prompt)),
                "completion_tokens": max(0, int(completion)),
                "usage_estimated": False,
            }
    return {
        "prompt_tokens": _estimate_tokens_from_chars(input_chars),
        "completion_tokens": _estimate_tokens_from_chars(len(content or "")),
        "usage_estimated": True,
    }


def _extract_anthropic_usage(
    resp: Any,
    *,
    content: str,
    input_chars: int,
) -> dict[str, Any]:
    """Pull ``input_tokens`` / ``output_tokens`` from an Anthropic reply.

    Anthropic SDK names differ from OpenAI's: ``resp.usage.input_tokens``
    and ``resp.usage.output_tokens``. We normalise to the OpenAI keys
    so downstream cost code stays single-shaped.
    """
    usage_obj = getattr(resp, "usage", None)
    if usage_obj is not None:
        prompt = getattr(usage_obj, "input_tokens", None)
        completion = getattr(usage_obj, "output_tokens", None)
        if prompt is None and isinstance(usage_obj, dict):
            prompt = usage_obj.get("input_tokens")
            completion = usage_obj.get("output_tokens")
        if prompt is not None and completion is not None:
            return {
                "prompt_tokens": max(0, int(prompt)),
                "completion_tokens": max(0, int(completion)),
                "usage_estimated": False,
            }
    return {
        "prompt_tokens": _estimate_tokens_from_chars(input_chars),
        "completion_tokens": _estimate_tokens_from_chars(len(content or "")),
        "usage_estimated": True,
    }


def _empty_usage() -> dict[str, Any]:
    """Used by error / stub paths where no provider response exists."""
    return {"prompt_tokens": 0, "completion_tokens": 0, "usage_estimated": True}


def call_chat(
    messages: list[ChatMessage],
    *,
    temperature: float | None = None,
    max_tokens: int | None = None,
    json_mode: bool = False,
    model: str | None = None,
    agent_role: AgentCallRole | None = None,
    request_timeout: float | None = None,
    max_retries: int | None = None,
    provider_max_retries: int | None = None,
) -> str:
    """Single entrypoint used by every agent/node.

    Returns raw assistant text. ``json_mode=True`` asks the provider to
    produce a JSON object where supported, otherwise we simply rely on
    the agent's prompt to request JSON.

    ``agent_role`` is consumed by :func:`resolve_model` to route the
    call to a per-agent model configured via
    ``settings.llm_model_per_agent``. When the map is empty (the
    default) all agents share ``settings.llm_model`` - the behaviour
    is identical to the pre-rollout single-model world.

    Per-session BYOK overrides are read from a ``contextvars`` token
    set by the session manager thread. When present, the override's
    provider / api_key / model / temperature take precedence over the
    server-wide ``Settings`` values.

    Transient errors (rate limits, timeouts, 5xx) are retried with
    exponential backoff up to ``settings.llm_max_retries`` times.
    Fatal errors (invalid model, auth, bad request) are raised on the
    first attempt so callers surface them immediately.
    """
    from app.services.session_manager import get_llm_override

    settings = get_settings()
    override = _override_for_agent_role(get_llm_override(), agent_role)

    if override and override.get("temperature") is not None and temperature is None:
        temperature = float(override["temperature"])
    temperature = temperature if temperature is not None else settings.llm_temperature
    max_tokens = max_tokens if max_tokens is not None else settings.llm_max_tokens

    if override and override.get("model") and model is None:
        model = override["model"]
    else:
        model = resolve_model(
            explicit_model=model,
            agent_role=agent_role,
            settings=settings,
        )

    has_override_key = bool(override and override.get("api_key"))
    max_retries = max(
        0,
        int(settings.llm_max_retries if max_retries is None else max_retries),
    )
    backoff = max(0.0, float(settings.llm_retry_backoff_seconds))
    cap = max(backoff, float(settings.llm_retry_backoff_cap_seconds))
    effective_request_timeout = _effective_request_timeout(
        request_timeout=request_timeout,
        agent_role=agent_role,
        settings=settings,
    )

    provider = (override or {}).get("provider") or settings.llm_provider
    base_host = _base_host_for_diagnostics(
        provider=provider,
        override=override,
        settings=settings,
    )
    input_chars = _message_chars(messages)
    # Every real LLM call in the interview pipeline should leave a
    # lightweight timing breadcrumb. The log deliberately contains
    # provider/model/host and character counts, but never message bodies
    # or API keys, so slow nodes can be diagnosed without leaking user
    # resume/interview content.
    diagnostic = agent_role is not None
    started_at = time.perf_counter()
    if diagnostic:
        log.info(
            "llm_call_start role=%s provider=%s model=%s base_host=%s input_chars=%d "
            "messages=%d json_mode=%s max_tokens=%d request_timeout=%s "
            "app_retries=%d provider_retries=%s",
            agent_role,
            provider,
            model,
            base_host,
            input_chars,
            len(messages),
            json_mode,
            max_tokens,
            effective_request_timeout,
            max_retries,
            0 if provider_max_retries is None else provider_max_retries,
        )

    def _record_timing(
        *,
        status: str,
        elapsed_ms: int,
        output_chars: int | None = None,
        attempts: int = 1,
        error_kind: str | None = None,
        usage: dict[str, Any] | None = None,
    ) -> None:
        record_llm_timing_event(
            role=agent_role,
            provider=str(provider),
            model=str(model),
            status=status,
            elapsed_ms=elapsed_ms,
            input_chars=input_chars,
            output_chars=output_chars,
            messages=len(messages),
            json_mode=json_mode,
            max_tokens=max_tokens,
            request_timeout=effective_request_timeout,
            attempts=attempts,
            base_host=base_host,
            error_kind=error_kind,
            prompt_tokens=None if usage is None else usage.get("prompt_tokens"),
            completion_tokens=None if usage is None else usage.get("completion_tokens"),
            usage_estimated=bool(usage and usage.get("usage_estimated")),
        )

    def _book_llm_call(*, status: str, usage: dict[str, Any]) -> None:
        """Forward call + token counts to the global Counter and the
        per-session accumulator on the active SessionHandle (if any)."""
        prompt_tokens = int(usage.get("prompt_tokens") or 0)
        completion_tokens = int(usage.get("completion_tokens") or 0)
        record_llm_call(
            agent_role=agent_role,
            provider=str(provider),
            model=str(model),
            status=status,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )
        try:
            from app.services.session_manager import record_session_llm_call

            record_session_llm_call(
                provider=str(provider),
                model=str(model),
                status=status,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                usage_estimated=bool(usage.get("usage_estimated")),
            )
        except ImportError:  # pragma: no cover - session manager always present in app
            return
        except Exception as exc:  # pragma: no cover - never let book-keeping break the call
            log.debug("session llm-call accounting skipped: %s", exc)

    if not has_override_key and settings.use_stub_llm:
        result = _stub_response(
            messages,
            json_mode=json_mode,
            agent_role=agent_role,
        )
        stub_usage: dict[str, Any] = {
            "prompt_tokens": _estimate_tokens_from_chars(input_chars),
            "completion_tokens": _estimate_tokens_from_chars(len(result or "")),
            "usage_estimated": True,
        }
        _record_timing(
            status="stub",
            elapsed_ms=int((time.perf_counter() - started_at) * 1000),
            output_chars=len(result or ""),
            attempts=1,
            usage=stub_usage,
        )
        _book_llm_call(status="stub", usage=stub_usage)
        return result

    attempt = 0
    while True:
        try:
            provider_result = _invoke_provider(
                messages,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                json_mode=json_mode,
                override=override if has_override_key else None,
                request_timeout=effective_request_timeout,
                provider_max_retries=provider_max_retries,
            )
            # ``_invoke_provider`` returns ``(content, usage)`` in
            # production. Existing pre-PR-1 tests, however, monkeypatch
            # ``_invoke_provider`` to return a bare string; treat that
            # as "no usage block, fall back to char-based estimate" so
            # those tests stay green without rewriting every mock.
            if isinstance(provider_result, tuple) and len(provider_result) == 2:
                result, usage = provider_result
            else:
                result = provider_result  # type: ignore[assignment]
                usage = {
                    "prompt_tokens": _estimate_tokens_from_chars(input_chars),
                    "completion_tokens": _estimate_tokens_from_chars(len(result or "")),
                    "usage_estimated": True,
                }
            if diagnostic:
                log.info(
                    "llm_call_success role=%s provider=%s model=%s elapsed_ms=%d "
                    "output_chars=%d prompt_tokens=%s completion_tokens=%s",
                    agent_role,
                    provider,
                    model,
                    int((time.perf_counter() - started_at) * 1000),
                    len(result or ""),
                    usage.get("prompt_tokens"),
                    usage.get("completion_tokens"),
                )
            _record_timing(
                status="success",
                elapsed_ms=int((time.perf_counter() - started_at) * 1000),
                output_chars=len(result or ""),
                attempts=attempt + 1,
                usage=usage,
            )
            _book_llm_call(status="success", usage=usage)
            return result
        except LLMError as exc:
            if diagnostic:
                log.warning(
                    "llm_call_failure role=%s provider=%s model=%s elapsed_ms=%d",
                    agent_role,
                    provider,
                    model,
                    int((time.perf_counter() - started_at) * 1000),
                )
            error_usage = _empty_usage()
            _record_timing(
                status="error",
                elapsed_ms=int((time.perf_counter() - started_at) * 1000),
                output_chars=None,
                attempts=attempt + 1,
                error_kind=classify_llm_error_kind(exc),
                usage=error_usage,
            )
            _book_llm_call(status="error", usage=error_usage)
            raise
        except Exception as exc:
            err_cls = _classify_exception(exc)
            wrapped = err_cls(str(exc))
            if err_cls is LLMFatal or attempt >= max_retries:
                if diagnostic:
                    log.warning(
                        "llm_call_failure role=%s provider=%s model=%s elapsed_ms=%d "
                        "error_class=%s",
                        agent_role,
                        provider,
                        model,
                        int((time.perf_counter() - started_at) * 1000),
                        exc.__class__.__name__,
                    )
                log.warning(
                    "llm call fatal after %d retries: %s", attempt, exc
                )
                error_usage = _empty_usage()
                _record_timing(
                    status="error",
                    elapsed_ms=int((time.perf_counter() - started_at) * 1000),
                    output_chars=None,
                    attempts=attempt + 1,
                    error_kind=classify_llm_error_kind(wrapped),
                    usage=error_usage,
                )
                _book_llm_call(status="error", usage=error_usage)
                raise wrapped from exc
            sleep_for = min(cap, backoff * (2**attempt))
            attempt += 1
            log.info(
                "llm call transient (%s); retry %d/%d in %.2fs",
                err_cls.__name__,
                attempt,
                max_retries,
                sleep_for,
            )
            time.sleep(sleep_for)


def _call_openai(
    messages: list[ChatMessage],
    model: str,
    temperature: float,
    max_tokens: int,
    json_mode: bool,
    *,
    override: dict[str, Any] | None = None,
    request_timeout: float | None = None,
    provider_max_retries: int | None = None,
) -> tuple[str, dict[str, Any]]:
    try:
        import openai  # noqa: F401 — early import for clearer error
    except ImportError as e:  # pragma: no cover
        raise LLMFatal("openai package is required for provider=openai") from e

    api_key = (override or {}).get("api_key") or get_settings().openai_api_key
    s = get_settings()
    timeout = request_timeout or s.llm_request_timeout_seconds
    client_max_retries = 0 if provider_max_retries is None else provider_max_retries
    base_url = (override or {}).get("base_url")
    client = _get_openai_client(
        api_key=api_key,
        base_url=base_url,
        timeout=timeout,
        max_retries=client_max_retries,
    )
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": [m.to_dict() for m in messages],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}

    try:
        resp = client.chat.completions.create(**kwargs)
    except Exception as exc:
        _evict_openai_client_after_provider_error(
            exc,
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
            max_retries=client_max_retries,
        )
        raise
    content = resp.choices[0].message.content or ""
    usage = _extract_openai_usage(
        resp,
        content=content,
        input_chars=_message_chars(messages),
    )
    return content, usage


def _call_deepseek(
    messages: list[ChatMessage],
    model: str,
    temperature: float,
    max_tokens: int,
    json_mode: bool,
    *,
    override: dict[str, Any] | None = None,
    request_timeout: float | None = None,
    provider_max_retries: int | None = None,
) -> tuple[str, dict[str, Any]]:
    """Call DeepSeek via its OpenAI-compatible Chat Completions API.

    DeepSeek speaks the OpenAI wire protocol on ``api.deepseek.com``,
    so we reuse the OpenAI SDK with ``base_url`` overridden. This
    keeps the dependency surface small (no extra SDK) and preserves
    the ``response_format={"type":"json_object"}`` affordance.
    """
    s = get_settings()
    api_key = (override or {}).get("api_key") or s.deepseek_api_key
    base_url = (override or {}).get("base_url") or s.deepseek_base_url
    return _call_openai_compatible(
        messages,
        model,
        temperature,
        max_tokens,
        json_mode,
        base_url=base_url,
        override={"api_key": api_key},
        request_timeout=request_timeout,
        provider_max_retries=provider_max_retries,
    )


def _call_openai_compatible(
    messages: list[ChatMessage],
    model: str,
    temperature: float,
    max_tokens: int,
    json_mode: bool,
    *,
    base_url: str,
    override: dict[str, Any] | None = None,
    request_timeout: float | None = None,
    provider_max_retries: int | None = None,
) -> tuple[str, dict[str, Any]]:
    """Generic OpenAI-Chat-Completions-compatible client.

    Used by every vendor that speaks the OpenAI wire protocol on a
    custom base URL: DeepSeek, Moonshot/Kimi, Qwen (DashScope
    compatible mode), Zhipu GLM, Mistral, and any user-supplied
    OneAPI / LiteLLM / LobeChat self-hosted gateway.

    We deliberately reuse the official ``openai`` Python SDK to keep
    the dependency surface tight; pointing it at ``base_url`` is all
    that vendor compatibility actually requires.
    """
    try:
        import openai  # noqa: F401 — early import for clearer error
    except ImportError as e:  # pragma: no cover
        raise LLMFatal("openai package is required for OpenAI-compatible providers") from e

    s = get_settings()
    api_key = (override or {}).get("api_key") or s.openai_api_key or ""
    timeout = request_timeout or s.llm_request_timeout_seconds
    client_max_retries = 0 if provider_max_retries is None else provider_max_retries
    client = _get_openai_client(
        api_key=api_key,
        base_url=base_url,
        timeout=timeout,
        max_retries=client_max_retries,
    )
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": [m.to_dict() for m in messages],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}

    try:
        resp = client.chat.completions.create(**kwargs)
    except Exception as exc:
        _evict_openai_client_after_provider_error(
            exc,
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
            max_retries=client_max_retries,
        )
        raise
    content = resp.choices[0].message.content or ""
    usage = _extract_openai_usage(
        resp,
        content=content,
        input_chars=_message_chars(messages),
    )
    return content, usage


def _call_anthropic(
    messages: list[ChatMessage],
    model: str,
    temperature: float,
    max_tokens: int,
    *,
    override: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any]]:
    try:
        import anthropic  # noqa: F401 — early import for clearer error
    except ImportError as e:  # pragma: no cover
        raise LLMFatal("anthropic package is required for provider=anthropic") from e

    s = get_settings()
    api_key = (override or {}).get("api_key") or s.anthropic_api_key
    system_messages = [m for m in messages if m.role == "system"]
    turn_parts = [m.to_dict() for m in messages if m.role != "system"]
    client = _get_anthropic_client(
        api_key=api_key,
        base_url=(override or {}).get("base_url"),
    )

    system_arg = _anthropic_system_arg(system_messages, s.anthropic_prompt_cache)

    resp = client.messages.create(
        model=model,
        system=system_arg,
        messages=turn_parts,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    content = "".join(block.text for block in resp.content if hasattr(block, "text"))
    usage = _extract_anthropic_usage(
        resp,
        content=content,
        input_chars=_message_chars(messages),
    )
    return content, usage


def _anthropic_system_arg(
    system_messages: list[ChatMessage],
    prompt_cache_enabled: bool,
) -> Any:
    """Build the Anthropic ``system=`` argument from N system messages.

    Two routing modes, picked automatically:

    1. *Per-message cache hints* (``m.cache_control`` set on any
       system message). Each message becomes its own Anthropic text
       block; ``cache_control: ephemeral`` is attached to the blocks
       whose ``ChatMessage.cache_control == "ephemeral"``. This is
       how the :mod:`app.engine.context` renderers mark a stable
       static prefix while leaving the dynamic tail uncached.
    2. *Legacy mode* (no per-message hints on any system message).
       The pre-PR-2b behaviour is preserved bit-for-bit: a single
       joined text block with or without ``cache_control``,
       depending on the global ``anthropic_prompt_cache`` flag, or a
       plain-string ``system`` when the flag is off.

    Passing no system messages returns ``None`` (matching the
    Anthropic SDK's "no system prompt" semantic).
    """
    if not system_messages:
        return None

    has_explicit_cache_hint = any(m.cache_control for m in system_messages)

    if has_explicit_cache_hint:
        blocks: list[dict[str, Any]] = []
        for m in system_messages:
            block: dict[str, Any] = {"type": "text", "text": m.content}
            if prompt_cache_enabled and m.cache_control == "ephemeral":
                block["cache_control"] = {"type": "ephemeral"}
            blocks.append(block)
        return blocks

    # Legacy path: join all system parts and either wrap in one
    # cacheable block (flag on) or return a plain string (flag off).
    joined = "\n".join(m.content for m in system_messages)
    if prompt_cache_enabled:
        return [
            {
                "type": "text",
                "text": joined,
                "cache_control": {"type": "ephemeral"},
            }
        ]
    return joined


def parse_json_response(text: str) -> dict[str, Any]:
    """Permissive JSON parser used by agents expecting structured output.

    LLMs occasionally wrap JSON in ```json fences or prepend chatter. We
    do a best-effort extraction before the real ``json.loads`` and fall
    back to an empty dict rather than raising, because agents are
    responsible for defaulting missing fields.
    """
    text = (text or "").strip()
    if not text:
        return {}
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                log.warning("Failed to parse JSON from LLM response: %s", text[:200])
        return {}
