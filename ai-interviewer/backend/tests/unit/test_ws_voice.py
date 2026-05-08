"""Regression tests for voice WebSocket recovery behavior."""
from __future__ import annotations

import json
import threading
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1 import ws_voice as ws_voice_module


@dataclass
class _FakeHandle:
    session_id: str
    trace_id: str = "trace-voice"
    turn_idx: int = 2
    max_turns: int = 8
    current_question: dict[str, Any] | None = None
    final_state: dict[str, Any] | None = None
    done_event: threading.Event = field(default_factory=threading.Event)


class _FakeSessionManager:
    def __init__(self, handle: _FakeHandle) -> None:
        self.handle = handle
        self.recover_calls: list[str] = []
        self.cancel_calls: list[str] = []
        self._served_question = False

    def get(self, _session_id: str) -> None:
        return None

    def recover_waiting_session(self, session_id: str) -> _FakeHandle | None:
        self.recover_calls.append(session_id)
        return self.handle if session_id == self.handle.session_id else None

    def wait_for_next_question(
        self, _session_id: str, _timeout: float
    ) -> dict[str, Any] | None:
        if self._served_question:
            return None
        self._served_question = True
        return {
            "question": "Tell me about a failed rollout you recovered.",
            "dimension": "ownership",
        }

    def cancel(self, session_id: str) -> None:
        self.cancel_calls.append(session_id)


class _StubTTS:
    async def synth(self, text: str) -> AsyncIterator[bytes]:
        yield f"[stub-tts] {text}".encode()


class _NoopBuffer:
    def clear(self, _session_id: str) -> None:
        return None


def test_voice_disconnect_after_recovery_does_not_cancel_durable_session(
    monkeypatch,
) -> None:
    handle = _FakeHandle(session_id="sess-voice")
    manager = _FakeSessionManager(handle)

    monkeypatch.setattr(ws_voice_module, "get_session_manager", lambda: manager)
    monkeypatch.setattr(ws_voice_module, "get_tts", lambda: _StubTTS())
    monkeypatch.setattr(ws_voice_module, "get_audio_buffer", lambda: _NoopBuffer())

    app = FastAPI()
    app.include_router(ws_voice_module.router)
    client = TestClient(app)

    with client.websocket_connect("/ws/voice/sess-voice") as ws:
        first_question = json.loads(ws.receive_text())
        assert first_question == {
            "type": "question",
            "turn_idx": 2,
            "max_turns": 8,
            "content": "Tell me about a failed rollout you recovered.",
            "dimension": "ownership",
        }
        assert ws.receive_bytes().startswith(b"[stub-tts]")
        assert json.loads(ws.receive_text()) == {"type": "tts_end", "turn_idx": 2}
        ws.close()

    assert manager.recover_calls == ["sess-voice"]
    assert manager.cancel_calls == []
