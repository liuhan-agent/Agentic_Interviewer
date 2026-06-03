"""End-to-end-lite test for the WebSocket voice channel empty-transcript guard.

This does not exercise the real workflow thread, Whisper, or OpenAI
TTS — it mounts the ``ws_voice`` router on a throw-away FastAPI app
and injects fakes for the collaborators the handler pulls from
module-level getters (``get_session_manager`` / ``get_asr`` /
``get_audio_buffer`` / ``get_tts``).

The scenario under test is the one that bit the HTTP / WS parity
before the fix: a ``stop`` frame that yielded an empty transcription
from ASR (silent mic, corrupt audio, Whisper hiccup) was silently
forwarded to ``submit_answer("")``, which then polluted the evaluator
and the bandit reward signal. The WebSocket path now refuses empty
strings and asks the client to retry, matching the HTTP
``AnswerRequest.answer: str = Field(min_length=1)`` contract.
"""
from __future__ import annotations

import json
import threading
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1 import ws_voice as ws_voice_module
from app.core.session_auth import hash_session_token


@dataclass
class _FakeHandle:
    session_id: str
    trace_id: str = "trace-test"
    turn_idx: int = 0
    current_question: dict[str, Any] | None = None
    final_state: dict[str, Any] | None = None
    error: str | None = None
    cancelled: bool = False
    done_event: threading.Event = field(default_factory=threading.Event)
    # Mirrors prod ``SessionHandle.max_turns`` which ``ws_voice`` reads
    # when it pushes the next question (``max_turns=handle.max_turns``).
    # Default 8 matches ``state.build_initial_state``.
    max_turns: int = 8


class _FakeSessionManager:
    """Minimal stand-in for :class:`app.services.session_manager.SessionManager`.

    Tracks ``submit_answer`` / ``cancel`` calls so tests can assert on
    them; returns a canned question from ``wait_for_next_question`` so
    the handler proceeds past its first round-trip without blocking.
    """

    def __init__(self, handle: _FakeHandle) -> None:
        self._handle = handle
        self.submit_calls: list[tuple[str, str]] = []
        self.cancel_calls: list[str] = []
        self.wait_calls: list[tuple[str, float]] = []
        self._served_first = False
        self.recover_calls: list[str] = []
        self.return_none_from_get = False
        self.submit_error: Exception | None = None

    def get(self, session_id: str) -> _FakeHandle | None:
        if self.return_none_from_get:
            return None
        if session_id != self._handle.session_id:
            return None
        return self._handle

    def recover_waiting_session(self, session_id: str) -> _FakeHandle | None:
        self.recover_calls.append(session_id)
        if session_id != self._handle.session_id:
            return None
        return self._handle

    def wait_for_next_question(
        self, session_id: str, timeout: float
    ) -> dict[str, Any] | None:
        self.wait_calls.append((session_id, timeout))
        # First call: hand back the canned question so the handler
        # enters its ``receive`` loop. Later calls (after an answer
        # was accepted) would normally return the *next* question;
        # the empty-transcript path never reaches that branch in this
        # test, so we return None so the handler would cleanly exit
        # if it got that far (that would be a test failure, not a
        # crash).
        if not self._served_first:
            self._served_first = True
            return {
                "question": "Tell me about a tricky bug you fixed.",
                "dimension": "problem_solving",
            }
        return None

    def submit_answer(self, session_id: str, answer: str, **_: Any) -> None:
        if self.submit_error is not None:
            raise self.submit_error
        self.submit_calls.append((session_id, answer))

    def cancel(self, session_id: str) -> None:
        self.cancel_calls.append(session_id)


class _EmptyASR:
    """ASR double that always returns an empty transcription."""

    def transcribe(self, audio: bytes, **_: Any) -> str:
        return ""


class _TranscriptASR:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def transcribe(self, audio: bytes, **_: Any) -> str:
        self.calls.append({"audio": audio, **_})
        return "candidate answer"


class _RecordingBuffer:
    """Audio buffer double; flush returns what was appended."""

    def __init__(self) -> None:
        self._buf: bytearray = bytearray()

    def append(self, session_id: str, chunk: bytes) -> None:
        self._buf.extend(chunk)

    def flush(self, session_id: str) -> bytes:
        data = bytes(self._buf)
        self._buf = bytearray()
        return data

    def clear(self, session_id: str) -> None:
        self._buf = bytearray()


class _StubTTS:
    async def synth(self, text: str) -> AsyncIterator[bytes]:
        yield f"[stub-tts] {text[:80]}".encode()


class _CaptureWebSocket:
    def __init__(self) -> None:
        self.sent: list[tuple[str, Any]] = []

    async def send_text(self, text: str) -> None:
        self.sent.append(("text", json.loads(text)))

    async def send_bytes(self, data: bytes) -> None:
        self.sent.append(("bytes", data))


@pytest.fixture
def ws_client(monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, _FakeSessionManager]:
    handle = _FakeHandle(session_id="sess-empty")
    manager = _FakeSessionManager(handle)
    asr = _EmptyASR()
    buffer = _RecordingBuffer()
    tts = _StubTTS()

    monkeypatch.setattr(ws_voice_module, "get_session_manager", lambda: manager)
    monkeypatch.setattr(ws_voice_module, "get_asr", lambda: asr)
    monkeypatch.setattr(ws_voice_module, "get_audio_buffer", lambda: buffer)
    monkeypatch.setattr(ws_voice_module, "get_tts", lambda: tts)

    app = FastAPI()
    app.include_router(ws_voice_module.router)
    return TestClient(app), manager


def test_empty_transcription_is_not_submitted_and_error_is_sent(
    ws_client: tuple[TestClient, _FakeSessionManager],
) -> None:
    client, manager = ws_client

    with client.websocket_connect("/ws/voice/sess-empty") as ws:
        # 1. Handshake: server pushes the first question as JSON
        #    followed by one TTS chunk (stub mode).
        first_question = json.loads(ws.receive_text())
        assert first_question["type"] == "question"
        assert first_question["content"].startswith("Tell me about")
        tts_chunk = ws.receive_bytes()
        assert tts_chunk.startswith(b"[stub-tts]")
        assert json.loads(ws.receive_text()) == {"type": "tts_end", "turn_idx": 0}

        # 2. Candidate "speaks" some audio and then presses stop.
        ws.send_bytes(b"\x00\x01\x02\x03")
        ws.send_text(json.dumps({"type": "stop"}))

        # 3. Because the ASR returned "", the server MUST send an
        #    error frame and NOT call ``submit_answer``.
        error_frame = json.loads(ws.receive_text())
        assert error_frame == {
            "type": "error",
            "error": "empty_transcription",
            "message": (
                "Could not transcribe audio. Please try speaking again."
            ),
        }

        # 4. Tear the socket down from the client side. For durable
        #    sessions this should only close the voice channel; the user
        #    can still continue in text mode with the same pending question.
        ws.close()

    assert manager.submit_calls == [], (
        f"empty transcripts must not reach submit_answer; got {manager.submit_calls!r}"
    )
    assert manager.cancel_calls == []


def test_stop_returns_draft_transcript_without_submitting(
    ws_client: tuple[TestClient, _FakeSessionManager],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, manager = ws_client
    monkeypatch.setattr(ws_voice_module, "get_asr", lambda: _TranscriptASR())

    with client.websocket_connect("/ws/voice/sess-empty") as ws:
        assert json.loads(ws.receive_text())["type"] == "question"
        assert ws.receive_bytes().startswith(b"[stub-tts]")
        assert json.loads(ws.receive_text()) == {"type": "tts_end", "turn_idx": 0}

        ws.send_bytes(b"\x00\x01\x02\x03")
        ws.send_text(json.dumps({"type": "stop", "turn_idx": 0}))

        assert json.loads(ws.receive_text()) == {
            "type": "draft_transcript",
            "turn_idx": 0,
            "content": "candidate answer",
        }
        ws.close()

    assert manager.submit_calls == []


def test_asr_only_mode_skips_question_tts_and_returns_draft(
    ws_client: tuple[TestClient, _FakeSessionManager],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, manager = ws_client
    monkeypatch.setattr(ws_voice_module, "get_asr", lambda: _TranscriptASR())

    with client.websocket_connect("/ws/voice/sess-empty") as ws:
        ws.send_text(json.dumps({"type": "auth", "mode": "asr_only"}))
        ws.send_bytes(b"\x00\x01\x02\x03")
        ws.send_text(json.dumps({"type": "stop", "turn_idx": 0}))

        assert json.loads(ws.receive_text()) == {
            "type": "draft_transcript",
            "turn_idx": 0,
            "content": "candidate answer",
        }
        ws.close()

    assert manager.wait_calls == []
    assert manager.submit_calls == []


def test_asr_only_mode_rejects_submit_transcript(
    ws_client: tuple[TestClient, _FakeSessionManager],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, manager = ws_client
    monkeypatch.setattr(ws_voice_module, "get_asr", lambda: _TranscriptASR())

    with client.websocket_connect("/ws/voice/sess-empty") as ws:
        ws.send_text(json.dumps({"type": "auth", "mode": "asr_only"}))
        ws.send_text(
            json.dumps(
                {
                    "type": "submit_transcript",
                    "turn_idx": 0,
                    "content": "must not submit over voice ws",
                }
            )
        )

        assert json.loads(ws.receive_text()) == {
            "type": "error",
            "error": "unsupported_frame",
            "message": "ASR-only voice connections cannot submit answers.",
        }
        ws.close()

    assert manager.wait_calls == []
    assert manager.submit_calls == []


def test_stop_passes_recording_mime_type_to_asr(
    ws_client: tuple[TestClient, _FakeSessionManager],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _manager = ws_client
    asr = _TranscriptASR()
    monkeypatch.setattr(ws_voice_module, "get_asr", lambda: asr)

    with client.websocket_connect("/ws/voice/sess-empty") as ws:
        assert json.loads(ws.receive_text())["type"] == "question"
        assert ws.receive_bytes().startswith(b"[stub-tts]")
        assert json.loads(ws.receive_text()) == {"type": "tts_end", "turn_idx": 0}

        ws.send_bytes(b"\x00\x01\x02\x03")
        ws.send_text(
            json.dumps(
                {
                    "type": "stop",
                    "turn_idx": 0,
                    "mime_type": "audio/wav",
                }
            )
        )

        assert json.loads(ws.receive_text())["type"] == "draft_transcript"
        ws.close()

    assert asr.calls[0]["mime_type"] == "audio/wav"


def test_submit_transcript_accepts_edited_draft_and_pushes_next_question(
    ws_client: tuple[TestClient, _FakeSessionManager],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, manager = ws_client
    monkeypatch.setattr(ws_voice_module, "get_asr", lambda: _TranscriptASR())

    with client.websocket_connect("/ws/voice/sess-empty") as ws:
        assert json.loads(ws.receive_text())["type"] == "question"
        assert ws.receive_bytes().startswith(b"[stub-tts]")
        assert json.loads(ws.receive_text()) == {"type": "tts_end", "turn_idx": 0}

        ws.send_bytes(b"\x00\x01\x02\x03")
        ws.send_text(json.dumps({"type": "stop", "turn_idx": 0}))
        assert json.loads(ws.receive_text())["type"] == "draft_transcript"

        ws.send_text(
            json.dumps(
                {
                    "type": "submit_transcript",
                    "turn_idx": 0,
                    "content": "edited candidate answer",
                }
            )
        )

        assert json.loads(ws.receive_text()) == {
            "type": "transcript",
            "content": "edited candidate answer",
        }
        ws.close()

    assert manager.submit_calls == [("sess-empty", "edited candidate answer")]


def test_invalid_turn_idx_sends_error_without_submitting(
    ws_client: tuple[TestClient, _FakeSessionManager],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, manager = ws_client
    monkeypatch.setattr(ws_voice_module, "get_asr", lambda: _TranscriptASR())

    with client.websocket_connect("/ws/voice/sess-empty") as ws:
        assert json.loads(ws.receive_text())["type"] == "question"
        assert ws.receive_bytes().startswith(b"[stub-tts]")
        assert json.loads(ws.receive_text()) == {"type": "tts_end", "turn_idx": 0}

        ws.send_bytes(b"\x00\x01\x02\x03")
        ws.send_text(json.dumps({"type": "stop", "turn_idx": "not-a-number"}))

        assert json.loads(ws.receive_text()) == {
            "type": "error",
            "error": "invalid_turn",
            "message": "Invalid turn index for this answer.",
        }
        ws.close()

    assert manager.submit_calls == []


def test_audio_too_large_is_rejected_before_asr(
    ws_client: tuple[TestClient, _FakeSessionManager],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, manager = ws_client
    monkeypatch.setattr(ws_voice_module, "MAX_VOICE_BYTES", 3, raising=False)
    monkeypatch.setattr(ws_voice_module, "get_asr", lambda: _TranscriptASR())

    with client.websocket_connect("/ws/voice/sess-empty") as ws:
        assert json.loads(ws.receive_text())["type"] == "question"
        assert ws.receive_bytes().startswith(b"[stub-tts]")
        assert json.loads(ws.receive_text()) == {"type": "tts_end", "turn_idx": 0}

        ws.send_bytes(b"\x00\x01\x02\x03")
        ws.send_text(json.dumps({"type": "stop", "turn_idx": 0}))
        assert json.loads(ws.receive_text()) == {
            "type": "error",
            "error": "audio_too_large",
            "message": "Audio is too long. Please record a shorter answer.",
        }
        ws.close()

    assert manager.submit_calls == []


def test_turn_mismatch_sends_structured_error(
    ws_client: tuple[TestClient, _FakeSessionManager],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, manager = ws_client
    manager.submit_error = ValueError(
        "answer turn_idx=1 does not match current turn_idx=2"
    )
    monkeypatch.setattr(ws_voice_module, "get_asr", lambda: _TranscriptASR())

    with client.websocket_connect("/ws/voice/sess-empty") as ws:
        assert json.loads(ws.receive_text())["type"] == "question"
        assert ws.receive_bytes().startswith(b"[stub-tts]")
        assert json.loads(ws.receive_text()) == {"type": "tts_end", "turn_idx": 0}

        ws.send_bytes(b"\x00\x01\x02\x03")
        ws.send_text(json.dumps({"type": "stop", "turn_idx": 1}))

        assert json.loads(ws.receive_text())["type"] == "draft_transcript"
        ws.send_text(
            json.dumps(
                {
                    "type": "submit_transcript",
                    "turn_idx": 1,
                    "content": "candidate answer",
                }
            )
        )

        assert json.loads(ws.receive_text()) == {
            "type": "error",
            "error": "turn_mismatch",
            "message": "This answer belongs to an older question. Please refresh and try again.",
        }
        ws.close()

    assert manager.submit_calls == []


def test_parse_text_rejects_oversized_frame(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ws_voice_module, "MAX_TEXT_FRAME_BYTES", 8, raising=False)

    assert ws_voice_module._parse_text(json.dumps({"type": "cancel"})) == {
        "type": "invalid",
        "error": "text_frame_too_large",
    }


def test_parse_text_rejects_unknown_frame_type() -> None:
    assert ws_voice_module._parse_text(json.dumps({"type": "surprise"})) == {
        "type": "invalid",
        "error": "invalid_frame",
    }


def test_parse_text_drops_invalid_video_signals() -> None:
    payload = {
        "type": "stop",
        "turn_idx": 0,
        "video_signals": {
            "confidence": 2,
            "engagement": 0.5,
            "dominant_emotion": "neutral",
            "sample_count": 3,
        },
    }

    assert ws_voice_module._parse_text(json.dumps(payload)) == {
        "type": "stop",
        "turn_idx": 0,
    }


def test_voice_channel_closes_after_too_many_invalid_frames(
    ws_client: tuple[TestClient, _FakeSessionManager],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, manager = ws_client
    monkeypatch.setattr(ws_voice_module, "MAX_INVALID_WS_FRAMES", 2, raising=False)

    with client.websocket_connect("/ws/voice/sess-empty") as ws:
        assert json.loads(ws.receive_text())["type"] == "question"
        assert ws.receive_bytes().startswith(b"[stub-tts]")
        assert json.loads(ws.receive_text()) == {"type": "tts_end", "turn_idx": 0}

        ws.send_text("{not-json")
        assert json.loads(ws.receive_text()) == {
            "type": "error",
            "error": "invalid_json",
        }
        ws.send_text(json.dumps({"type": "surprise"}))
        assert json.loads(ws.receive_text()) == {
            "type": "error",
            "error": "too_many_invalid_frames",
        }

    assert manager.submit_calls == []


def test_voice_channel_rejects_invalid_session_id(
    ws_client: tuple[TestClient, _FakeSessionManager],
) -> None:
    client, manager = ws_client

    with client.websocket_connect("/ws/voice/bad%20id") as ws:
        error_frame = json.loads(ws.receive_text())
        assert error_frame == {"type": "error", "error": "invalid_session_id"}

    assert manager.recover_calls == []
    assert manager.submit_calls == []
    assert manager.cancel_calls == []


async def test_push_question_sends_tts_end_after_audio_chunks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handle = _FakeHandle(session_id="sess-tts-end", turn_idx=3)
    manager = _FakeSessionManager(handle)
    ws = _CaptureWebSocket()

    monkeypatch.setattr(ws_voice_module, "get_session_manager", lambda: manager)
    monkeypatch.setattr(ws_voice_module, "get_tts", lambda: _StubTTS())

    has_more = await ws_voice_module._push_question(ws, handle)  # type: ignore[arg-type]

    assert has_more is True
    assert ws.sent == [
        (
            "text",
            {
                "type": "question",
                "turn_idx": 3,
                "max_turns": 8,
                "content": "Tell me about a tricky bug you fixed.",
                "dimension": "problem_solving",
            },
        ),
        ("bytes", b"[stub-tts] Tell me about a tricky bug you fixed."),
        ("text", {"type": "tts_end", "turn_idx": 3}),
    ]


def test_explicit_voice_cancel_tears_down_session(
    ws_client: tuple[TestClient, _FakeSessionManager],
) -> None:
    client, manager = ws_client

    with client.websocket_connect("/ws/voice/sess-empty") as ws:
        first_question = json.loads(ws.receive_text())
        assert first_question["type"] == "question"
        _ = ws.receive_bytes()
        assert json.loads(ws.receive_text()) == {"type": "tts_end", "turn_idx": 0}

        ws.send_text(json.dumps({"type": "cancel"}))

    assert manager.cancel_calls == ["sess-empty"]


def test_voice_channel_rejects_invalid_session_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handle = _FakeHandle(session_id="sess-auth")
    handle.session_token_hash = hash_session_token("voice-secret")  # type: ignore[attr-defined]
    manager = _FakeSessionManager(handle)

    monkeypatch.setattr(ws_voice_module, "get_session_manager", lambda: manager)
    monkeypatch.setattr(ws_voice_module, "get_tts", lambda: _StubTTS())

    app = FastAPI()
    app.include_router(ws_voice_module.router)
    client = TestClient(app)

    with client.websocket_connect("/ws/voice/sess-auth") as ws:
        ws.send_text(json.dumps({"type": "auth", "session_token": "wrong"}))
        assert json.loads(ws.receive_text()) == {
            "type": "error",
            "error": "invalid_token",
        }


def test_voice_channel_accepts_valid_session_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handle = _FakeHandle(session_id="sess-auth")
    handle.session_token_hash = hash_session_token("voice-secret")  # type: ignore[attr-defined]
    manager = _FakeSessionManager(handle)

    monkeypatch.setattr(ws_voice_module, "get_session_manager", lambda: manager)
    monkeypatch.setattr(ws_voice_module, "get_tts", lambda: _StubTTS())

    app = FastAPI()
    app.include_router(ws_voice_module.router)
    client = TestClient(app)

    with client.websocket_connect("/ws/voice/sess-auth") as ws:
        ws.send_text(json.dumps({"type": "auth", "session_token": "voice-secret"}))
        first_question = json.loads(ws.receive_text())
        assert first_question["type"] == "question"
        assert ws.receive_bytes().startswith(b"[stub-tts]")
        assert json.loads(ws.receive_text()) == {"type": "tts_end", "turn_idx": 0}


def test_owned_voice_channel_rejects_session_token_without_owner_cookie(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handle = _FakeHandle(session_id="sess-owned")
    handle.owner_user_id = 123  # type: ignore[attr-defined]
    handle.session_token_hash = hash_session_token("voice-secret")  # type: ignore[attr-defined]
    manager = _FakeSessionManager(handle)

    monkeypatch.setattr(ws_voice_module, "get_session_manager", lambda: manager)
    monkeypatch.setattr(ws_voice_module, "get_tts", lambda: _StubTTS())
    monkeypatch.setattr(
        ws_voice_module,
        "_current_ws_user_id",
        lambda _ws: None,
        raising=False,
    )

    app = FastAPI()
    app.include_router(ws_voice_module.router)
    client = TestClient(app)

    with client.websocket_connect("/ws/voice/sess-owned") as ws:
        ws.send_text(json.dumps({"type": "auth", "session_token": "voice-secret"}))
        assert json.loads(ws.receive_text()) == {
            "type": "error",
            "error": "auth_required",
        }


def test_owned_voice_channel_rejects_other_logged_in_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handle = _FakeHandle(session_id="sess-owned")
    handle.owner_user_id = 123  # type: ignore[attr-defined]
    handle.session_token_hash = hash_session_token("voice-secret")  # type: ignore[attr-defined]
    manager = _FakeSessionManager(handle)

    monkeypatch.setattr(ws_voice_module, "get_session_manager", lambda: manager)
    monkeypatch.setattr(ws_voice_module, "get_tts", lambda: _StubTTS())
    monkeypatch.setattr(
        ws_voice_module,
        "_current_ws_user_id",
        lambda _ws: 456,
        raising=False,
    )

    app = FastAPI()
    app.include_router(ws_voice_module.router)
    client = TestClient(app)

    with client.websocket_connect("/ws/voice/sess-owned") as ws:
        ws.send_text(json.dumps({"type": "auth", "session_token": "voice-secret"}))
        assert json.loads(ws.receive_text()) == {
            "type": "error",
            "error": "session_owner_required",
        }


def test_owned_voice_channel_accepts_owner_cookie_without_session_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handle = _FakeHandle(session_id="sess-owned")
    handle.owner_user_id = 123  # type: ignore[attr-defined]
    handle.session_token_hash = hash_session_token("voice-secret")  # type: ignore[attr-defined]
    manager = _FakeSessionManager(handle)

    monkeypatch.setattr(ws_voice_module, "get_session_manager", lambda: manager)
    monkeypatch.setattr(ws_voice_module, "get_tts", lambda: _StubTTS())
    monkeypatch.setattr(
        ws_voice_module,
        "_current_ws_user_id",
        lambda _ws: 123,
        raising=False,
    )

    app = FastAPI()
    app.include_router(ws_voice_module.router)
    client = TestClient(app)

    with client.websocket_connect("/ws/voice/sess-owned") as ws:
        ws.send_text(json.dumps({"type": "auth"}))
        first_question = json.loads(ws.receive_text())
        assert first_question["type"] == "question"
        assert ws.receive_bytes().startswith(b"[stub-tts]")
        assert json.loads(ws.receive_text()) == {"type": "tts_end", "turn_idx": 0}


def test_voice_channel_accepts_one_time_voice_ticket(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.voice_ticket import clear_voice_tickets, issue_voice_ticket

    clear_voice_tickets()
    handle = _FakeHandle(session_id="sess-auth")
    handle.session_token_hash = hash_session_token("voice-secret")  # type: ignore[attr-defined]
    manager = _FakeSessionManager(handle)
    ticket = issue_voice_ticket("sess-auth")

    monkeypatch.setattr(ws_voice_module, "get_session_manager", lambda: manager)
    monkeypatch.setattr(ws_voice_module, "get_tts", lambda: _StubTTS())

    app = FastAPI()
    app.include_router(ws_voice_module.router)
    client = TestClient(app)

    with client.websocket_connect("/ws/voice/sess-auth") as ws:
        ws.send_text(json.dumps({"type": "auth", "ticket": ticket}))
        first_question = json.loads(ws.receive_text())
        assert first_question["type"] == "question"
        assert ws.receive_bytes().startswith(b"[stub-tts]")
        assert json.loads(ws.receive_text()) == {"type": "tts_end", "turn_idx": 0}

    with client.websocket_connect("/ws/voice/sess-auth") as ws:
        ws.send_text(json.dumps({"type": "auth", "ticket": ticket}))
        assert json.loads(ws.receive_text()) == {
            "type": "error",
            "error": "invalid_token",
        }


def test_voice_channel_rejects_tokenless_session_in_prod(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handle = _FakeHandle(session_id="sess-tokenless")
    manager = _FakeSessionManager(handle)

    monkeypatch.setattr(ws_voice_module, "get_session_manager", lambda: manager)
    monkeypatch.setattr(ws_voice_module, "get_tts", lambda: _StubTTS())
    # Force the DB-fallback to also return None so the prod gate fires.
    monkeypatch.setattr(
        ws_voice_module,
        "_session_token_hash_from_db",
        lambda _sid: None,
    )
    monkeypatch.setattr(
        ws_voice_module,
        "get_settings",
        lambda: type("_Settings", (), {"app_env": "prod"})(),
        raising=False,
    )

    app = FastAPI()
    app.include_router(ws_voice_module.router)
    client = TestClient(app)

    with client.websocket_connect("/ws/voice/sess-tokenless") as ws:
        assert json.loads(ws.receive_text()) == {
            "type": "error",
            "error": "auth_required",
        }


def test_voice_channel_uses_db_token_hash_when_handle_lost_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression: a recovered SessionHandle that lost its in-memory
    token_hash (server restart -> rehydrate path) must still enforce
    auth based on the DB-persisted hash, not silently fail open."""
    handle = _FakeHandle(session_id="sess-rehydrated")
    manager = _FakeSessionManager(handle)

    persisted_hash = hash_session_token("voice-secret")

    monkeypatch.setattr(ws_voice_module, "get_session_manager", lambda: manager)
    monkeypatch.setattr(ws_voice_module, "get_tts", lambda: _StubTTS())
    monkeypatch.setattr(
        ws_voice_module,
        "_session_token_hash_from_db",
        lambda sid: persisted_hash if sid == "sess-rehydrated" else None,
    )

    app = FastAPI()
    app.include_router(ws_voice_module.router)
    client = TestClient(app)

    # Wrong token must be rejected even though handle.session_token_hash is None.
    with client.websocket_connect("/ws/voice/sess-rehydrated") as ws:
        ws.send_text(json.dumps({"type": "auth", "session_token": "wrong"}))
        assert json.loads(ws.receive_text()) == {
            "type": "error",
            "error": "invalid_token",
        }

    # Correct token reaches the question stream.
    with client.websocket_connect("/ws/voice/sess-rehydrated") as ws:
        ws.send_text(json.dumps({"type": "auth", "session_token": "voice-secret"}))
        first_question = json.loads(ws.receive_text())
        assert first_question["type"] == "question"


def test_voice_channel_recovers_waiting_session_before_auth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handle = _FakeHandle(session_id="sess-recover")
    handle.session_token_hash = hash_session_token("voice-secret")  # type: ignore[attr-defined]
    manager = _FakeSessionManager(handle)
    manager.return_none_from_get = True

    monkeypatch.setattr(ws_voice_module, "get_session_manager", lambda: manager)
    monkeypatch.setattr(ws_voice_module, "get_tts", lambda: _StubTTS())

    app = FastAPI()
    app.include_router(ws_voice_module.router)
    client = TestClient(app)

    with client.websocket_connect("/ws/voice/sess-recover") as ws:
        ws.send_text(json.dumps({"type": "auth", "session_token": "voice-secret"}))
        first_question = json.loads(ws.receive_text())
        assert first_question["type"] == "question"
        assert ws.receive_bytes().startswith(b"[stub-tts]")
        assert json.loads(ws.receive_text()) == {"type": "tts_end", "turn_idx": 0}

    assert manager.recover_calls == ["sess-recover"]


def test_session_not_found_closes_cleanly(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unknown session ids get a single error frame and a clean close.

    Locks the existing behaviour in ``voice_channel`` so a follow-up
    change does not accidentally leave the socket open on 404.
    """

    class _NoneManager:
        def get(self, session_id: str) -> None:
            return None

        def cancel(self, session_id: str) -> None:  # pragma: no cover
            pass

    monkeypatch.setattr(
        ws_voice_module, "get_session_manager", lambda: _NoneManager()
    )

    app = FastAPI()
    app.include_router(ws_voice_module.router)
    client = TestClient(app)

    with client.websocket_connect("/ws/voice/unknown") as ws:
        first = json.loads(ws.receive_text())
        assert first == {"type": "error", "error": "session not found"}
