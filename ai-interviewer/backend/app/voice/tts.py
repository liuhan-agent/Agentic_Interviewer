"""Streaming text-to-speech for the voice channel.

Uses :class:`openai.AsyncOpenAI` so the chunk iterator is a native
async generator. The previous version mixed a sync OpenAI client with
``async for``, which raised ``TypeError`` the moment a real provider
call was attempted — masked only by ``# pragma: no cover`` on the
branch.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Callable

from app.core.logging import get_logger
from app.core.settings import get_settings
from app.voice.routing import resolve_tts_route
from app.voice.providers import QwenConnectFactory, provider_for

log = get_logger(__name__)


class StreamingTTS:
    def __init__(self) -> None:
        settings = get_settings()
        self.model = settings.tts_model
        self.voice = settings.tts_voice
        self.provider = settings.tts_provider
        self.llm_provider = settings.llm_provider
        self.openai_api_key = settings.openai_api_key
        self.openai_base_url = None
        self.qwen_api_key = settings.qwen_api_key
        self.dashscope_api_key = settings.dashscope_api_key
        self.qwen_realtime_base_url = settings.qwen_realtime_base_url
        self.stub = settings.tts_provider == "stub"
        self._client = None
        if not self.stub and settings.tts_provider == "openai" and settings.openai_api_key:
            try:
                from openai import AsyncOpenAI

                self._client = AsyncOpenAI(api_key=settings.openai_api_key)
            except ImportError:  # pragma: no cover
                log.warning("openai package unavailable; TTS will use stub mode")
                self.stub = True

    async def synth(
        self,
        text: str,
        *,
        llm_config: dict[str, Any] | None = None,
        client_factory: Callable[..., Any] | None = None,
        qwen_connect_factory: QwenConnectFactory | None = None,
    ) -> AsyncIterator[bytes]:
        """Yield audio chunks for ``text``.

        Stub mode returns a single human-readable marker chunk so a
        manual WebSocket test round-trips visibly without a real API
        key. The marker bytes are **not** playable audio — any
        integration client must only decode what comes back under a
        non-stub configuration.
        """
        route = resolve_tts_route(self, llm_config)
        if route.is_stub:
            yield f"[stub-tts] {text[:80]}".encode()
            return

        try:
            provider = provider_for(route)
            if route.provider == "qwen":
                async for chunk in provider.synth(  # type: ignore[attr-defined]
                    route,
                    text,
                    connect_factory=qwen_connect_factory,
                ):
                    yield chunk
                return
            async for chunk in provider.synth(  # type: ignore[attr-defined]
                route,
                text,
                existing_client=self._client,
                client_factory=client_factory,
            ):
                    yield chunk
        except Exception as e:  # pragma: no cover - provider flakes
            # Fail closed: log, yield nothing. The WS handler will
            # then send a text ``{type: question, content: ...}`` frame
            # without audio, which is strictly better than tearing down
            # the whole interview because the TTS side-channel hiccupped.
            try:
                from app.engine.agents.llm_client import redact_llm_secrets

                error = redact_llm_secrets(str(e), llm_config)
            except Exception:
                error = "<redaction failed>"
            log.warning("TTS provider call failed: %s", error)
            return


_tts: StreamingTTS | None = None


def get_tts() -> StreamingTTS:
    global _tts
    if _tts is None:
        _tts = StreamingTTS()
    return _tts
