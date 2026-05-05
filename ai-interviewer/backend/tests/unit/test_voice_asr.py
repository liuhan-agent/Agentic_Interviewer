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

import pytest

from app.voice.asr import WhisperASR, _extension_for_mime

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


def test_transcribe_stub_returns_canned_phrase(asr_stub: WhisperASR) -> None:
    out = asr_stub.transcribe(b"\x00" * 16)
    assert out == "(stub transcription) the candidate spoke for a few seconds."


def test_transcribe_stub_ignores_empty_input(asr_stub: WhisperASR) -> None:
    # Stub mode answers the same canned phrase even for empty input —
    # that is fine because the WS handler has its own empty-audio
    # guard upstream (``buffer.flush`` before calling us).
    assert asr_stub.transcribe(b"") != ""


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
