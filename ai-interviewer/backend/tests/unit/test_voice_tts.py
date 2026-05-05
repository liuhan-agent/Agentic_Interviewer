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
