"""Tests for the streaming TTS wrapper in :mod:`app.voice.tts`.

Two pieces of behaviour are locked:

1. Stub mode yields a single human-readable marker chunk so a manual
   WS test can confirm the round-trip without an API key.
2. The live-path interaction with ``AsyncOpenAI`` uses ``async with``
   + ``async for`` — mixing the sync client with ``async for`` (the
   previous bug) raises ``TypeError`` on the first real call.
"""
# ruff: noqa: N801
# Mock classes mirror ``openai.AsyncOpenAI``'s lowercase attribute
# layout (``client.audio.speech.with_streaming_response.create``).
# Renaming to CapWords would silently desynchronise from the real
# SDK; keeping the shape identical is the whole point of the test.
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest

from app.voice.tts import StreamingTTS


async def _collect(agen: AsyncIterator[bytes]) -> list[bytes]:
    return [chunk async for chunk in agen]


# ---------------------------------------------------------------------
# Stub mode
# ---------------------------------------------------------------------


async def test_synth_stub_yields_single_marker_chunk() -> None:
    tts = StreamingTTS.__new__(StreamingTTS)
    tts.model = "gpt-4o-mini-tts"
    tts.voice = "alloy"
    tts.stub = True
    tts._client = None

    chunks = await _collect(tts.synth("hello there"))

    assert len(chunks) == 1
    assert chunks[0].startswith(b"[stub-tts]")
    assert b"hello there" in chunks[0]


async def test_synth_stub_truncates_long_text_in_marker() -> None:
    tts = StreamingTTS.__new__(StreamingTTS)
    tts.model = "gpt-4o-mini-tts"
    tts.voice = "alloy"
    tts.stub = True
    tts._client = None

    long_text = "x" * 400
    chunks = await _collect(tts.synth(long_text))

    assert len(chunks) == 1
    # Only the first 80 chars land in the marker (see tts.py).
    assert len(chunks[0]) < 120


# ---------------------------------------------------------------------
# Live mode — shape of the AsyncOpenAI streaming protocol
# ---------------------------------------------------------------------


class _FakeAsyncResponse:
    """Matches the ``AsyncOpenAI`` speech-streaming response shape."""

    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks

    async def __aenter__(self) -> _FakeAsyncResponse:
        return self

    async def __aexit__(self, *_: Any) -> None:
        return None

    async def iter_bytes(self) -> AsyncIterator[bytes]:
        for c in self._chunks:
            yield c


class _FakeWithStreamingResponse:
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks

    def create(self, **_: Any) -> _FakeAsyncResponse:
        return _FakeAsyncResponse(self._chunks)


class _FakeSpeech:
    def __init__(self, chunks: list[bytes]) -> None:
        self.with_streaming_response = _FakeWithStreamingResponse(chunks)


class _FakeAudio:
    def __init__(self, chunks: list[bytes]) -> None:
        self.speech = _FakeSpeech(chunks)


class _FakeAsyncOpenAI:
    def __init__(self, chunks: list[bytes]) -> None:
        self.audio = _FakeAudio(chunks)


async def test_synth_live_streams_chunks_in_order() -> None:
    tts = StreamingTTS.__new__(StreamingTTS)
    tts.model = "gpt-4o-mini-tts"
    tts.voice = "alloy"
    tts.stub = False
    tts._client = _FakeAsyncOpenAI(
        [b"chunk-1", b"chunk-2", b"chunk-3"]
    )

    chunks = await _collect(tts.synth("question body"))

    assert chunks == [b"chunk-1", b"chunk-2", b"chunk-3"]


async def test_synth_live_swallows_provider_exceptions() -> None:
    """A provider flake must degrade silently to zero audio chunks.

    The WS handler already sends the question as text *before* calling
    ``synth``, so zero audio chunks means the candidate sees the
    question without voice — strictly better than killing the socket.
    """

    class _BoomClient:
        class audio:
            class speech:
                class with_streaming_response:
                    @staticmethod
                    def create(**_: Any) -> Any:
                        raise RuntimeError("tts provider exploded")

    tts = StreamingTTS.__new__(StreamingTTS)
    tts.model = "gpt-4o-mini-tts"
    tts.voice = "alloy"
    tts.stub = False
    tts._client = _BoomClient()

    chunks = await _collect(tts.synth("anything"))

    assert chunks == []


async def test_synth_uses_voice_override_model_voice_and_key() -> None:
    captured: dict[str, object] = {}

    class _RecordingWithStreamingResponse:
        def create(self, **kwargs: Any) -> _FakeAsyncResponse:
            captured.update(kwargs)
            return _FakeAsyncResponse([b"voice"])

    class _RecordingSpeech:
        def __init__(self) -> None:
            self.with_streaming_response = _RecordingWithStreamingResponse()

    class _RecordingAudio:
        def __init__(self) -> None:
            self.speech = _RecordingSpeech()

    class _RecordingClient:
        def __init__(self, *, api_key: str | None = None, base_url: str | None = None) -> None:
            captured["api_key"] = api_key
            captured["base_url"] = base_url
            self.audio = _RecordingAudio()

    tts = StreamingTTS.__new__(StreamingTTS)
    tts.model = "gpt-4o-mini-tts"
    tts.voice = "alloy"
    tts.provider = "stub"
    tts.openai_api_key = None
    tts.openai_base_url = None
    tts._client = None

    chunks = await _collect(
        tts.synth(
            "question body",
            llm_config={
                "voice_overrides": {
                    "tts": {
                        "provider": "openai",
                        "api_key": "sk-voice-tts",
                        "model": "tts-override",
                        "voice": "verse",
                        "base_url": "https://voice.example/v1",
                    }
                }
            },
            client_factory=_RecordingClient,
        )
    )

    assert chunks == [b"voice"]
    assert captured["api_key"] == "sk-voice-tts"
    assert captured["base_url"] == "https://voice.example/v1"
    assert captured["model"] == "tts-override"
    assert captured["voice"] == "verse"
    assert captured["input"] == "question body"


async def test_synth_uses_top_level_openai_key_as_fallback() -> None:
    captured: dict[str, object] = {}

    class _RecordingWithStreamingResponse:
        def create(self, **kwargs: Any) -> _FakeAsyncResponse:
            captured.update(kwargs)
            return _FakeAsyncResponse([b"voice"])

    class _RecordingClient:
        def __init__(self, *, api_key: str | None = None, base_url: str | None = None) -> None:
            captured["api_key"] = api_key
            captured["base_url"] = base_url
            self.audio = type(
                "_Audio",
                (),
                {
                    "speech": type(
                        "_Speech",
                        (),
                        {"with_streaming_response": _RecordingWithStreamingResponse()},
                    )()
                },
            )()

    tts = StreamingTTS.__new__(StreamingTTS)
    tts.model = "gpt-4o-mini-tts"
    tts.voice = "alloy"
    tts.provider = "stub"
    tts.openai_api_key = None
    tts.openai_base_url = None
    tts._client = None

    chunks = await _collect(
        tts.synth(
            "question body",
            llm_config={"provider": "openai", "api_key": "sk-default-openai"},
            client_factory=_RecordingClient,
        )
    )

    assert chunks == [b"voice"]
    assert captured["api_key"] == "sk-default-openai"
    assert captured["model"] == "gpt-4o-mini-tts"
    assert captured["voice"] == "alloy"


async def test_synth_does_not_use_non_openai_default_key() -> None:
    class _FailingClient:
        def __init__(self, **_: object) -> None:
            raise AssertionError("non-OpenAI default key must not reach OpenAI TTS")

    tts = StreamingTTS.__new__(StreamingTTS)
    tts.model = "gpt-4o-mini-tts"
    tts.voice = "alloy"
    tts.provider = "stub"
    tts.openai_api_key = None
    tts.openai_base_url = None
    tts._client = None

    chunks = await _collect(
        tts.synth(
            "question body",
            llm_config={"provider": "deepseek", "api_key": "sk-deepseek"},
            client_factory=_FailingClient,
        )
    )

    assert len(chunks) == 1
    assert chunks[0].startswith(b"[stub-tts]")


async def test_synth_uses_qwen_voice_override_model_voice_and_key() -> None:
    sent: list[dict[str, object]] = []
    captured: dict[str, object] = {}

    class _FakeQwenWS:
        def __init__(self) -> None:
            self._messages = iter(
                [
                    '{"type":"session.created"}',
                    '{"type":"session.updated"}',
                    '{"type":"response.audio.delta","delta":"dm9pY2UtMQ=="}',
                    '{"type":"response.audio.delta","delta":"dm9pY2UtMg=="}',
                    '{"type":"response.done"}',
                ]
            )

        async def send(self, raw: str) -> None:
            import json

            sent.append(json.loads(raw))

        async def recv(self) -> str:
            return next(self._messages)

        async def close(self) -> None:
            captured["closed"] = True

    async def _connect(url: str, *, additional_headers: dict[str, str]) -> _FakeQwenWS:
        captured["url"] = url
        captured["headers"] = additional_headers
        return _FakeQwenWS()

    tts = StreamingTTS.__new__(StreamingTTS)
    tts.model = "qwen3-tts-flash-realtime"
    tts.voice = "Cherry"
    tts.provider = "stub"
    tts.llm_provider = "stub"
    tts.openai_api_key = None
    tts.openai_base_url = None
    tts.qwen_api_key = None
    tts.dashscope_api_key = None
    tts.qwen_realtime_base_url = None
    tts._client = None

    chunks = await _collect(
        tts.synth(
            "question body",
            llm_config={
                "voice_overrides": {
                    "tts": {
                        "provider": "qwen",
                        "api_key": "sk-qwen-tts",
                        "model": "qwen3-tts-flash-realtime",
                        "voice": "Cherry",
                        "base_url": "wss://dashscope.aliyuncs.com/api-ws/v1/realtime",
                    }
                }
            },
            qwen_connect_factory=_connect,
        )
    )

    assert chunks == [b"voice-1", b"voice-2"]
    assert captured["url"] == (
        "wss://dashscope.aliyuncs.com/api-ws/v1/realtime"
        "?model=qwen3-tts-flash-realtime"
    )
    assert captured["headers"]["Authorization"] == "Bearer sk-qwen-tts"
    assert captured["headers"]["OpenAI-Beta"] == "realtime=v1"
    assert sent[0]["type"] == "session.update"
    assert sent[0]["session"]["voice"] == "Cherry"
    assert sent[0]["session"]["output_audio_format"] == "mp3"
    assert sent[1] == {"type": "input_text_buffer.append", "text": "question body"}
    assert sent[2]["type"] == "input_text_buffer.commit"
    assert sent[3]["type"] == "session.finish"


async def test_synth_uses_top_level_qwen_key_as_fallback() -> None:
    captured: dict[str, object] = {}

    class _FakeQwenWS:
        def __init__(self) -> None:
            self._done = False

        async def send(self, raw: str) -> None:
            return None

        async def recv(self) -> str:
            if self._done:
                return '{"type":"response.done"}'
            self._done = True
            return '{"type":"response.audio.delta","delta":"ZmFsbGJhY2s="}'

        async def close(self) -> None:
            return None

    async def _connect(url: str, *, additional_headers: dict[str, str]) -> _FakeQwenWS:
        captured["url"] = url
        captured["headers"] = additional_headers
        return _FakeQwenWS()

    tts = StreamingTTS.__new__(StreamingTTS)
    tts.model = "qwen3-tts-flash-realtime"
    tts.voice = "Cherry"
    tts.provider = "stub"
    tts.llm_provider = "stub"
    tts.openai_api_key = None
    tts.openai_base_url = None
    tts.qwen_api_key = None
    tts.dashscope_api_key = None
    tts.qwen_realtime_base_url = None
    tts._client = None

    chunks = await _collect(
        tts.synth(
            "question body",
            llm_config={"provider": "qwen", "api_key": "sk-default-qwen"},
            qwen_connect_factory=_connect,
        )
    )

    assert chunks == [b"fallback"]
    assert captured["headers"]["Authorization"] == "Bearer sk-default-qwen"


# ---------------------------------------------------------------------
# Pytest-asyncio auto mode
# ---------------------------------------------------------------------
# pyproject sets ``asyncio_mode = "auto"`` so every ``async def test_*``
# in this file is picked up automatically. Leaving a sync regression
# test at module level to fail loudly if that setting is ever removed.


def test_async_mode_is_configured() -> None:
    # ``StreamingTTS`` itself is not async, so importing it sync works.
    tts = StreamingTTS.__new__(StreamingTTS)
    assert tts is not None


# Keep a lint-friendly reference so pytest fixture discovery does not
# spuriously complain about unused imports on older pytest builds.
_ = pytest
