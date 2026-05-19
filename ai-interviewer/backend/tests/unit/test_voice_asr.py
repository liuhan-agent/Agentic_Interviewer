"""Tests for the ASR wrapper in :mod:`app.voice.asr`.

Coverage is intentionally narrow because the real Whisper API is out
of scope for unit tests. We lock two pieces of behaviour that broke
real clients before the fix:

1. The MIME-to-extension translator (:func:`_extension_for_mime`)
   handles ``codecs=`` parameters, vendor-prefixed subtypes, and
   unknown values without producing an illegal filename.
2. The :class:`WhisperASR` wrapper never raises and never lets an
   empty byte buffer slip through to the provider — both guard rails
   exist so the WebSocket handler can refuse an empty transcript
   instead of polluting the evaluator and bandit reward signal.
"""
# ruff: noqa: N801
# The SDK mock classes below intentionally mirror the lowercase
# attribute names used by ``openai.OpenAI`` (e.g. ``client.audio.
# transcriptions.create``). Renaming them to PEP-8 CapWords would
# mean the tests no longer match the shape of the real client and
# silently bit-rot the moment the SDK adds a new attribute.
from __future__ import annotations

import base64
import struct

import pytest

from app.voice.asr import WhisperASR, _extension_for_mime, _qwen_audio_payload

# ---------------------------------------------------------------------
# _extension_for_mime — decision table
# ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "mime_type, expected",
    [
        # Plain ``audio/<ext>`` pairs that match Whisper's accepted set.
        ("audio/webm", "webm"),
        ("audio/wav", "wav"),
        ("audio/mp3", "mp3"),
        ("audio/mp4", "mp4"),
        ("audio/m4a", "m4a"),
        ("audio/mpeg", "mpeg"),
        ("audio/flac", "flac"),
        ("audio/ogg", "ogg"),
        # Codec parameters must be stripped — the browser MediaRecorder
        # default on Chrome is ``audio/webm;codecs=opus`` and the
        # previous implementation passed ``webm;codecs=opus`` to the
        # Whisper SDK, breaking the call end-to-end.
        ("audio/webm;codecs=opus", "webm"),
        ("audio/ogg;codecs=opus", "ogg"),
        ("audio/mp4; codecs=aac", "mp4"),
        # Vendor-prefixed subtypes resolve through the alias table.
        ("audio/x-wav", "wav"),
        ("audio/x-m4a", "m4a"),
        ("audio/vnd.wav", "wav"),
        ("audio/opus", "ogg"),
        # Case-insensitive.
        ("AUDIO/WEBM", "webm"),
        ("audio/WEBM;CODECS=OPUS", "webm"),
        # Unknown / malformed values clamp to ``webm`` rather than
        # producing something Whisper will reject outright.
        ("audio/three-gp", "webm"),
        ("application/octet-stream", "webm"),
        ("", "webm"),
        ("garbage", "webm"),
        ("audio/", "webm"),
    ],
)
def test_extension_for_mime(mime_type: str, expected: str) -> None:
    assert _extension_for_mime(mime_type) == expected


def test_qwen_audio_payload_sends_wav_as_raw_pcm() -> None:
    pcm = b"\x01\x02\x03\x04"
    wav = (
        b"RIFF"
        + struct.pack("<I", 36 + len(pcm))
        + b"WAVEfmt "
        + struct.pack("<IHHIIHH", 16, 1, 1, 16000, 32000, 2, 16)
        + b"data"
        + struct.pack("<I", len(pcm))
        + pcm
    )

    payload = _qwen_audio_payload(wav, "audio/wav")

    assert payload.format == "pcm"
    assert payload.sample_rate == 16000
    assert base64.b64decode(payload.audio_b64) == pcm


def test_qwen_asr_sends_large_audio_in_chunks() -> None:
    sent: list[dict[str, object]] = []
    captured: dict[str, object] = {}
    pcm = b"\x01\x02" * 40000
    wav = (
        b"RIFF"
        + struct.pack("<I", 36 + len(pcm))
        + b"WAVEfmt "
        + struct.pack("<IHHIIHH", 16, 1, 1, 16000, 32000, 2, 16)
        + b"data"
        + struct.pack("<I", len(pcm))
        + pcm
    )

    class _FakeQwenWS:
        def __init__(self) -> None:
            self._messages = iter(
                [
                    '{"type":"session.created"}',
                    '{"type":"session.updated"}',
                    '{"type":"session.finished","transcript":"长段转写"}',
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
        return _FakeQwenWS()

    asr = WhisperASR.__new__(WhisperASR)
    asr.model = "qwen3-asr-flash-realtime"
    asr.provider = "stub"
    asr.llm_provider = "stub"
    asr.openai_api_key = None
    asr.openai_base_url = None
    asr.qwen_api_key = None
    asr.dashscope_api_key = None
    asr.qwen_realtime_base_url = None
    asr._client = None

    out = asr.transcribe(
        wav,
        mime_type="audio/wav",
        llm_config={
            "voice_overrides": {
                "asr": {
                    "provider": "qwen",
                    "api_key": "sk-qwen-asr",
                    "model": "qwen3-asr-flash-realtime",
                }
            }
        },
        qwen_connect_factory=_connect,
    )

    append_frames = [frame for frame in sent if frame.get("type") == "input_audio_buffer.append"]
    assert out == "长段转写"
    assert len(append_frames) > 1
    assert all(len(str(frame["audio"])) < len(base64.b64encode(pcm)) for frame in append_frames)


# ---------------------------------------------------------------------
# WhisperASR — stub / empty-input behaviour
# ---------------------------------------------------------------------


@pytest.fixture
def asr_stub(monkeypatch: pytest.MonkeyPatch) -> WhisperASR:
    """Force stub mode regardless of the test environment's env vars."""
    asr = WhisperASR.__new__(WhisperASR)
    asr.model = "whisper-1"
    asr.stub = True
    asr._client = None
    return asr


def test_transcribe_stub_returns_empty_string(asr_stub: WhisperASR) -> None:
    out = asr_stub.transcribe(b"\x00" * 16)
    assert out == ""


def test_transcribe_stub_ignores_empty_input(asr_stub: WhisperASR) -> None:
    # Stub mode answers the same canned phrase even for empty input —
    # that is fine because the WS handler has its own empty-audio
    # guard upstream (``buffer.flush`` before calling us).
    assert asr_stub.transcribe(b"") == ""


def test_transcribe_live_mode_returns_empty_string_for_empty_audio() -> None:
    """Live path must refuse an empty buffer without touching the provider.

    The WS handler's empty-transcript guard depends on this behaviour
    to keep ``submit_answer`` free of empty strings. We simulate live
    mode manually so no real API key is needed.
    """

    class _FailingClient:
        class audio:
            class transcriptions:
                @staticmethod
                def create(**_: object) -> object:
                    raise AssertionError(
                        "client must not be called for empty audio"
                    )

    asr = WhisperASR.__new__(WhisperASR)
    asr.model = "whisper-1"
    asr.stub = False
    asr._client = _FailingClient()

    assert asr.transcribe(b"") == ""


def test_transcribe_live_mode_swallows_provider_exceptions() -> None:
    """Provider flakes must never kill the interview.

    The ASR wrapper's contract is ``returns str, never raises`` — the
    WS handler relies on this to degrade to an error frame instead of
    tearing the socket down.
    """

    class _FlakyClient:
        class audio:
            class transcriptions:
                @staticmethod
                def create(**_: object) -> object:
                    raise RuntimeError("provider exploded")

    asr = WhisperASR.__new__(WhisperASR)
    asr.model = "whisper-1"
    asr.stub = False
    asr._client = _FlakyClient()

    assert asr.transcribe(b"\x00\x01\x02") == ""


def test_transcribe_live_mode_passes_extension_from_mime_type() -> None:
    """The MIME is translated before reaching the SDK.

    We capture the ``file.name`` attribute that the wrapper sets and
    check it ends with the expected extension; the rest of the
    SDK-facing plumbing is out of scope for this unit test.
    """

    captured: dict[str, str] = {}

    class _RecordingClient:
        class audio:
            class transcriptions:
                @staticmethod
                def create(*, model: str, file: object) -> object:
                    captured["model"] = model
                    captured["filename"] = getattr(file, "name", "")

                    class _Result:
                        text = "hello world"

                    return _Result()

    asr = WhisperASR.__new__(WhisperASR)
    asr.model = "whisper-1"
    asr.stub = False
    asr._client = _RecordingClient()

    text = asr.transcribe(b"\x00" * 64, mime_type="audio/ogg;codecs=opus")

    assert text == "hello world"
    assert captured["filename"].endswith(".ogg")
    assert captured["model"] == "whisper-1"


def test_transcribe_uses_voice_override_model_and_key() -> None:
    captured: dict[str, object] = {}

    class _RecordingClient:
        def __init__(self, *, api_key: str | None = None, base_url: str | None = None) -> None:
            captured["api_key"] = api_key
            captured["base_url"] = base_url
            self.audio = self.Audio()

        class Audio:
            class transcriptions:
                @staticmethod
                def create(*, model: str, file: object) -> object:
                    captured["model"] = model
                    captured["filename"] = getattr(file, "name", "")

                    class _Result:
                        text = "真实转写"

                    return _Result()

    asr = WhisperASR.__new__(WhisperASR)
    asr.model = "whisper-1"
    asr.provider = "stub"
    asr.openai_api_key = None
    asr.openai_base_url = None
    asr._client = None

    out = asr.transcribe(
        b"\x00" * 64,
        llm_config={
            "voice_overrides": {
                "asr": {
                    "provider": "openai",
                    "api_key": "sk-voice-asr",
                    "model": "whisper-override",
                    "base_url": "https://voice.example/v1",
                }
            }
        },
        client_factory=_RecordingClient,
    )

    assert out == "真实转写"
    assert captured["api_key"] == "sk-voice-asr"
    assert captured["base_url"] == "https://voice.example/v1"
    assert captured["model"] == "whisper-override"
    assert str(captured["filename"]).endswith(".webm")


def test_transcribe_uses_top_level_openai_key_as_fallback() -> None:
    captured: dict[str, object] = {}

    class _RecordingClient:
        def __init__(self, *, api_key: str | None = None, base_url: str | None = None) -> None:
            captured["api_key"] = api_key
            captured["base_url"] = base_url
            self.audio = self.Audio()

        class Audio:
            class transcriptions:
                @staticmethod
                def create(*, model: str, file: object) -> object:
                    captured["model"] = model

                    class _Result:
                        text = "fallback transcript"

                    return _Result()

    asr = WhisperASR.__new__(WhisperASR)
    asr.model = "whisper-1"
    asr.provider = "stub"
    asr.openai_api_key = None
    asr.openai_base_url = None
    asr._client = None

    out = asr.transcribe(
        b"\x00" * 64,
        llm_config={
            "provider": "openai",
            "api_key": "sk-default-openai",
            "model": "gpt-4o-mini",
        },
        client_factory=_RecordingClient,
    )

    assert out == "fallback transcript"
    assert captured["api_key"] == "sk-default-openai"
    assert captured["model"] == "whisper-1"


def test_transcribe_does_not_cross_inherit_default_key() -> None:
    class _FailingClient:
        def __init__(self, **_: object) -> None:
            raise AssertionError("non-OpenAI default key must not reach OpenAI ASR")

    asr = WhisperASR.__new__(WhisperASR)
    asr.model = "whisper-1"
    asr.provider = "stub"
    asr.openai_api_key = None
    asr.openai_base_url = None
    asr._client = None

    out = asr.transcribe(
        b"\x00" * 64,
        llm_config={
            "provider": "deepseek",
            "api_key": "sk-deepseek",
            "voice_overrides": {"asr": {"provider": "openai"}},
        },
        client_factory=_FailingClient,
    )

    assert out == ""


def test_transcribe_uses_qwen_voice_override_model_and_key() -> None:
    sent: list[dict[str, object]] = []
    captured: dict[str, object] = {}

    class _FakeQwenWS:
        def __init__(self) -> None:
            self._messages = iter(
                [
                    '{"type":"session.created"}',
                    '{"type":"session.updated"}',
                    '{"type":"conversation.item.input_audio_transcription.text","text":"中间"}',
                    '{"type":"conversation.item.input_audio_transcription.completed","transcript":"真实转写"}',
                    '{"type":"session.finished"}',
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

    asr = WhisperASR.__new__(WhisperASR)
    asr.model = "qwen3-asr-flash-realtime"
    asr.provider = "stub"
    asr.llm_provider = "stub"
    asr.openai_api_key = None
    asr.openai_base_url = None
    asr.qwen_api_key = None
    asr.dashscope_api_key = None
    asr.qwen_realtime_base_url = None
    asr._client = None

    pcm = b"\x01\x02" * 32
    wav = (
        b"RIFF"
        + struct.pack("<I", 36 + len(pcm))
        + b"WAVEfmt "
        + struct.pack("<IHHIIHH", 16, 1, 1, 16000, 32000, 2, 16)
        + b"data"
        + struct.pack("<I", len(pcm))
        + pcm
    )

    out = asr.transcribe(
        wav,
        mime_type="audio/wav",
        llm_config={
            "voice_overrides": {
                "asr": {
                    "provider": "qwen",
                    "api_key": "sk-qwen-asr",
                    "model": "qwen3-asr-flash-realtime",
                    "base_url": "wss://dashscope.aliyuncs.com/api-ws/v1/realtime",
                }
            }
        },
        qwen_connect_factory=_connect,
    )

    assert out == "真实转写"
    assert captured["url"] == (
        "wss://dashscope.aliyuncs.com/api-ws/v1/realtime"
        "?model=qwen3-asr-flash-realtime"
    )
    assert captured["headers"]["Authorization"] == "Bearer sk-qwen-asr"
    assert captured["headers"]["OpenAI-Beta"] == "realtime=v1"
    assert sent[0]["type"] == "session.update"
    assert sent[0]["session"]["input_audio_format"] == "pcm"
    assert sent[0]["session"]["sample_rate"] == 16000
    assert sent[0]["session"]["turn_detection"] is None
    assert sent[1]["type"] == "input_audio_buffer.append"
    assert sent[2]["type"] == "input_audio_buffer.commit"
    assert sent[3]["type"] == "session.finish"


def test_transcribe_uses_top_level_qwen_key_as_fallback() -> None:
    captured: dict[str, object] = {}

    class _FakeQwenWS:
        async def send(self, raw: str) -> None:
            return None

        async def recv(self) -> str:
            return '{"type":"session.finished","transcript":"qwen fallback"}'

        async def close(self) -> None:
            return None

    async def _connect(url: str, *, additional_headers: dict[str, str]) -> _FakeQwenWS:
        captured["url"] = url
        captured["headers"] = additional_headers
        return _FakeQwenWS()

    asr = WhisperASR.__new__(WhisperASR)
    asr.model = "qwen3-asr-flash-realtime"
    asr.provider = "stub"
    asr.llm_provider = "stub"
    asr.openai_api_key = None
    asr.openai_base_url = None
    asr.qwen_api_key = None
    asr.dashscope_api_key = None
    asr.qwen_realtime_base_url = None
    asr._client = None

    out = asr.transcribe(
        b"\x01\x02" * 32,
        llm_config={"provider": "qwen", "api_key": "sk-default-qwen"},
        qwen_connect_factory=_connect,
    )

    assert out == "qwen fallback"
    assert captured["headers"]["Authorization"] == "Bearer sk-default-qwen"
