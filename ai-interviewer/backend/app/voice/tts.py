"""Streaming text-to-speech for the voice channel.

Uses :class:`openai.AsyncOpenAI` so the chunk iterator is a native
async generator. The previous version mixed a sync OpenAI client with
``async for``, which raised ``TypeError`` the moment a real provider
call was attempted — masked only by ``# pragma: no cover`` on the
branch.
"""
from __future__ import annotations

from collections.abc import AsyncIterator

from app.core.logging import get_logger
from app.core.settings import get_settings

log = get_logger(__name__)


class StreamingTTS:
    def __init__(self) -> None:
        settings = get_settings()
        self.model = settings.tts_model
        self.voice = settings.tts_voice
        self.stub = settings.use_stub_llm or settings.tts_provider == "stub"
        self._client = None
        if not self.stub:
            try:
                from openai import AsyncOpenAI

                self._client = AsyncOpenAI(api_key=settings.openai_api_key)
            except ImportError:  # pragma: no cover
                log.warning("openai package unavailable; TTS will use stub mode")
                self.stub = True

    async def synth(self, text: str) -> AsyncIterator[bytes]:
        """Yield audio chunks for ``text``.

        Stub mode returns a single human-readable marker chunk so a
        manual WebSocket test round-trips visibly without a real API
        key. The marker bytes are **not** playable audio — any
        integration client must only decode what comes back under a
        non-stub configuration.
        """
        if self.stub:
            yield f"[stub-tts] {text[:80]}".encode()
            return

        try:
            async with self._client.audio.speech.with_streaming_response.create(
                model=self.model,
                voice=self.voice,
                input=text,
            ) as response:
                async for chunk in response.iter_bytes():
                    yield chunk
        except Exception as e:  # pragma: no cover - provider flakes
            # Fail closed: log, yield nothing. The WS handler will
            # then send a text ``{type: question, content: ...}`` frame
            # without audio, which is strictly better than tearing down
            # the whole interview because the TTS side-channel hiccupped.
            log.warning("TTS provider call failed: %s", e)
            return


_tts: StreamingTTS | None = None


def get_tts() -> StreamingTTS:
    global _tts
    if _tts is None:
        _tts = StreamingTTS()
    return _tts
