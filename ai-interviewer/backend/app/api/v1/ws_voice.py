"""WebSocket voice channel.

Client-server protocol (JSON text frames + binary audio frames):

- Client -> server binary frame  : audio bytes (appended to the session buffer)
- Client -> server text  ``{"type": "stop"}``  : end-of-utterance; server
  transcribes, pushes the transcript into the answer provider, then
  streams TTS for the next question back.
- Server -> client text  ``{"type": "question", "turn_idx": N, "content": "..."}``
- Server -> client binary frames : TTS audio chunks for the current question
- Server -> client text  ``{"type": "final_report", "report": {...}}``
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import json
import time
from collections.abc import AsyncIterator
from typing import Any, Literal
from uuid import uuid4

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, ConfigDict, ValidationError

from app.core.logging import get_logger
from app.core.metrics import record_ws_invalid_frame
from app.core.session_auth import verify_session_token
from app.core.session_ids import is_valid_session_id
from app.core.settings import get_settings
from app.core.video_signals_schema import normalize_video_signals
from app.core.voice_ticket import consume_voice_ticket
from app.services.session_manager import SessionHandle, get_session_manager
from app.services.user_auth import AUTH_COOKIE_NAME, load_active_user_for_token
from app.voice.asr import get_asr
from app.voice.stream_manager import get_audio_buffer
from app.voice.tts import get_tts

log = get_logger(__name__)

router = APIRouter(tags=["voice"])

REAUTH_REQUIRED_MESSAGE = "This interview needs your personal LLM configuration again."
MAX_VOICE_BYTES = 10 * 1024 * 1024
MAX_TEXT_FRAME_BYTES = 64 * 1024
MAX_INVALID_WS_FRAMES = 5
MAX_AUDIO_TOO_LARGE_FRAMES = 3
VOICE_TOO_LARGE_MESSAGE = "Audio is too long. Please record a shorter answer."
VoiceChannelMode = Literal["voice", "asr_only"]

_VOICE_EXECUTOR = concurrent.futures.ThreadPoolExecutor(
    max_workers=4,
    thread_name_prefix="ws-voice",
)


class AuthFrame(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["auth"]
    mode: VoiceChannelMode | None = None
    session_token: str | None = None
    ticket: str | None = None
    llm_config: dict[str, Any] | None = None


class StopFrame(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["stop"]
    # Keep turn_idx coercion in the main loop so existing invalid-turn
    # handling returns the user-facing "invalid_turn" error.
    turn_idx: Any = None
    mime_type: str | None = None
    video_signals: Any | None = None


class SubmitTranscriptFrame(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["submit_transcript"]
    turn_idx: Any = None
    content: str
    video_signals: Any | None = None
    llm_config: dict[str, Any] | None = None


class CancelFrame(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["cancel"]


async def _send_error(ws: WebSocket, error: str, message: str | None = None) -> None:
    payload: dict[str, Any] = {"type": "error", "error": error}
    if message:
        payload["message"] = message
    await ws.send_text(json.dumps(payload))


def _submit_error_payload(exc: ValueError) -> tuple[str, str]:
    text = str(exc)
    if "reauth_required" in text:
        return "reauth_required", REAUTH_REQUIRED_MESSAGE
    if "turn_idx" in text:
        return (
            "turn_mismatch",
            "This answer belongs to an older question. Please refresh and try again.",
        )
    if "waiting" in text:
        return (
            "not_waiting_for_answer",
            "This session is not waiting for an answer right now.",
        )
    return "answer_rejected", text or "The answer could not be accepted."


def _session_token_hash_from_db(session_id: str) -> str | None:
    """Fallback lookup so a recovered handle that lost the in-memory
    token_hash (e.g. after a server restart + rehydrate) still
    enforces auth in non-dev deployments. Mirrors the HTTP-side
    helper of the same name in ``app.api.v1.interview``.
    """
    try:
        from app.models import InterviewSession
        from app.models import get_session as get_db_session

        with get_db_session() as db:
            row = db.get(InterviewSession, session_id)
            return row.session_token_hash if row is not None else None
    except Exception as e:  # pragma: no cover - DB failures must not unlock auth
        log.warning("ws_voice token lookup failed for %s: %s", session_id, e)
        return None


def _owner_id(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _session_owner_id_from_db(session_id: str) -> tuple[int | None, bool]:
    try:
        from app.models import InterviewSession
        from app.models import get_session as get_db_session

        with get_db_session() as db:
            row = db.get(InterviewSession, session_id)
            if row is None:
                return None, False
            return _owner_id(row.owner_user_id), False
    except Exception as e:  # pragma: no cover - DB failures must not unlock prod auth
        log.warning("ws_voice owner lookup failed for %s: %s", session_id, e)
        return None, True


def _current_ws_user_id(ws: WebSocket) -> int | None:
    token = ws.cookies.get(AUTH_COOKIE_NAME)
    if not token:
        return None
    try:
        from app.models import get_session as get_db_session

        with get_db_session() as db:
            user = load_active_user_for_token(db, token)
            return int(user.id) if user is not None else None
    except Exception as e:
        log.warning("ws_voice auth user lookup failed: %s", e)
        return None


async def _authenticate_ws(ws: WebSocket, handle: SessionHandle) -> VoiceChannelMode | None:
    mode: VoiceChannelMode = "voice"
    owner_user_id = _owner_id(getattr(handle, "owner_user_id", None))
    owner_lookup_failed = False
    if owner_user_id is None:
        owner_user_id, owner_lookup_failed = _session_owner_id_from_db(handle.session_id)
    if owner_lookup_failed and get_settings().app_env == "prod":
        await _send_error(ws, "auth_required")
        return None

    token_hash = getattr(handle, "session_token_hash", None)
    if not token_hash:
        # Mirror app.api.v1.interview._require_session_access: pull the
        # token_hash from DB before deciding to fail open. A recovered
        # SessionHandle (server restart -> rehydrate path) can land here
        # with a None token_hash even though one is persisted, and we
        # must enforce auth based on persisted state, not in-memory
        # lossage.
        token_hash = _session_token_hash_from_db(handle.session_id)
    if owner_user_id is not None:
        try:
            raw = await asyncio.wait_for(ws.receive_text(), timeout=5.0)
            payload = _parse_text(raw)
        except Exception:
            record_ws_invalid_frame("auth_required")
            await _send_error(ws, "auth_required")
            return None
        if payload.get("type") == "invalid":
            record_ws_invalid_frame(str(payload.get("error") or "invalid_frame"))
            await _send_error(ws, str(payload.get("error") or "invalid_frame"))
            return None
        if payload.get("type") != "auth":
            await _send_error(ws, "invalid_token")
            return None
        if payload.get("mode") == "asr_only":
            mode = "asr_only"
        if payload.get("ticket"):
            consume_voice_ticket(payload.get("ticket"), handle.session_id)
        current_user_id = _current_ws_user_id(ws)
        if current_user_id is None:
            await _send_error(ws, "auth_required")
            return None
        if current_user_id != owner_user_id:
            await _send_error(ws, "session_owner_required")
            return None
        llm_config = payload.get("llm_config")
        if isinstance(llm_config, dict):
            handle.llm_config = llm_config
        return mode

    if not token_hash:
        if get_settings().app_env == "prod":
            await _send_error(ws, "auth_required")
            return None
        try:
            raw = await asyncio.wait_for(ws.receive_text(), timeout=0.2)
        except TimeoutError:
            return mode
        except Exception:
            record_ws_invalid_frame("auth_required")
            await _send_error(ws, "auth_required")
            return None
        payload = _parse_text(raw)
        if payload.get("type") == "invalid":
            record_ws_invalid_frame(str(payload.get("error") or "invalid_frame"))
            await _send_error(ws, str(payload.get("error") or "invalid_frame"))
            return None
        if payload.get("type") != "auth":
            await _send_error(ws, "invalid_token")
            return None
        if payload.get("mode") == "asr_only":
            mode = "asr_only"
        llm_config = payload.get("llm_config")
        if isinstance(llm_config, dict):
            handle.llm_config = llm_config
        return mode
    try:
        raw = await asyncio.wait_for(ws.receive_text(), timeout=5.0)
        payload = _parse_text(raw)
    except Exception:
        record_ws_invalid_frame("auth_required")
        await _send_error(ws, "auth_required")
        return None
    if payload.get("type") == "invalid":
        record_ws_invalid_frame(str(payload.get("error") or "invalid_frame"))
        await _send_error(ws, str(payload.get("error") or "invalid_frame"))
        return None
    if payload.get("type") != "auth":
        await _send_error(ws, "invalid_token")
        return None
    if payload.get("mode") == "asr_only":
        mode = "asr_only"
    if consume_voice_ticket(payload.get("ticket"), handle.session_id):
        llm_config = payload.get("llm_config")
        if isinstance(llm_config, dict):
            handle.llm_config = llm_config
        return mode
    if not verify_session_token(payload.get("session_token"), token_hash):
        await _send_error(ws, "invalid_token")
        return None
    llm_config = payload.get("llm_config")
    if isinstance(llm_config, dict):
        handle.llm_config = llm_config
    return mode


async def _push_question(ws: WebSocket, handle: SessionHandle) -> bool:
    """Wait for the next question and stream it back as TTS audio.

    Returns False if the workflow finished; in that case the caller
    should send the final report frame and close.
    """
    loop = asyncio.get_running_loop()
    manager = get_session_manager()
    question = await loop.run_in_executor(
        _VOICE_EXECUTOR, manager.wait_for_next_question, handle.session_id, 60.0
    )
    if question is None:
        return False
    turn_idx = handle.turn_idx
    await ws.send_text(
        json.dumps(
            {
                "type": "question",
                "turn_idx": turn_idx,
                "max_turns": handle.max_turns,
                "content": question.get("question"),
                "dimension": question.get("dimension"),
            }
        )
    )
    tts = get_tts()
    llm_config = getattr(handle, "llm_config", None)
    async for chunk in _synth_question_audio(
        tts,
        question.get("question", ""),
        llm_config=llm_config,
    ):
        await ws.send_bytes(chunk)
    await ws.send_text(json.dumps({"type": "tts_end", "turn_idx": turn_idx}))
    return True


async def _synth_question_audio(
    tts: Any,
    text: str,
    *,
    llm_config: dict[str, Any] | None,
) -> AsyncIterator[bytes]:
    try:
        async for chunk in tts.synth(text, llm_config=llm_config):
            yield chunk
        return
    except TypeError as e:
        if "llm_config" not in str(e):
            raise
    async for chunk in tts.synth(text):
        yield chunk


@router.websocket("/ws/voice/{session_id}")
async def voice_channel(ws: WebSocket, session_id: str) -> None:
    await ws.accept()
    if not is_valid_session_id(session_id):
        await ws.send_text(json.dumps({"type": "error", "error": "invalid_session_id"}))
        await ws.close()
        return
    manager = get_session_manager()
    handle = manager.get(session_id)
    if handle is None:
        recover = getattr(manager, "recover_waiting_session", lambda _sid: None)
        handle = recover(session_id)
    if handle is None:
        await ws.send_text(json.dumps({"type": "error", "error": "session not found"}))
        await ws.close()
        return
    mode = await _authenticate_ws(ws, handle)
    if mode is None:
        await ws.close()
        return
    from app.core.logging import bind_log_context, reset_log_context

    ws_conn_id = uuid4().hex[:8]
    log_token = bind_log_context(
        session_id=session_id, trace_id=handle.trace_id, request_id=ws_conn_id,
    )
    log.info("ws connected session=%s ws_conn=%s", session_id, ws_conn_id)

    buffer = get_audio_buffer()
    asr = get_asr()
    explicit_cancel = False
    voice_bytes = 0
    voice_rejected = False
    invalid_frame_count = 0
    audio_too_large_count = 0
    pending_video_signals: dict[str, Any] | None = None

    # Anything that exits the receive loop - normal end, disconnect,
    # explicit cancel, uncaught exception - must tear the workflow
    # thread down, otherwise the background ``QueueAnswerProvider.get``
    # blocks forever and the session leaks. ``client_closed`` flags
    # the path where the socket is already half-dead so we don't try
    # to write a cancel ack back to it.
    client_closed = False
    try:
        if mode != "asr_only":
            has_more = await _push_question(ws, handle)
            if not has_more:
                await _send_final(ws, handle)
                return

        while True:
            msg = await ws.receive()
            if msg.get("type") == "websocket.disconnect":
                client_closed = True
                break
            if "bytes" in msg and msg["bytes"] is not None:
                chunk = msg["bytes"]
                voice_bytes += len(chunk)
                if voice_bytes > MAX_VOICE_BYTES:
                    buffer.clear(session_id)
                    voice_bytes = 0
                    voice_rejected = True
                    audio_too_large_count += 1
                    record_ws_invalid_frame("audio_too_large")
                    if audio_too_large_count >= MAX_AUDIO_TOO_LARGE_FRAMES:
                        await _send_error(ws, "too_many_invalid_frames")
                        break
                    await _send_error(
                        ws,
                        "audio_too_large",
                        VOICE_TOO_LARGE_MESSAGE,
                    )
                    continue
                buffer.append(session_id, chunk)
                continue
            if "text" in msg and msg["text"] is not None:
                payload = _parse_text(msg["text"])
                if payload.get("type") == "invalid":
                    invalid_frame_count += 1
                    record_ws_invalid_frame(str(payload.get("error") or "invalid_frame"))
                    if invalid_frame_count >= MAX_INVALID_WS_FRAMES:
                        await _send_error(ws, "too_many_invalid_frames")
                        break
                    await _send_error(ws, str(payload.get("error") or "invalid_frame"))
                    continue
                if payload.get("type") == "stop":
                    if voice_rejected:
                        buffer.clear(session_id)
                        voice_rejected = False
                        voice_bytes = 0
                        continue
                    audio = buffer.flush(session_id)
                    voice_bytes = 0
                    asr_t0 = time.perf_counter()
                    llm_config = getattr(handle, "llm_config", None)
                    mime_type = str(payload.get("mime_type") or "audio/webm")
                    transcript = await asyncio.get_running_loop().run_in_executor(
                        _VOICE_EXECUTOR,
                        lambda audio=audio, mime_type=mime_type, llm_config=llm_config: asr.transcribe(
                            audio,
                            mime_type=mime_type,
                            llm_config=llm_config,
                        ),
                    )
                    transcript = (transcript or "").strip()
                    asr_ms = int((time.perf_counter() - asr_t0) * 1000)
                    log.info(
                        "asr done session=%s bytes=%d chars=%d ms=%d mime=%s",
                        session_id, len(audio), len(transcript), asr_ms, mime_type,
                    )
                    if not transcript:
                        log.warning(
                            "empty_transcription session=%s audio_bytes=%d",
                            session_id, len(audio),
                        )
                        await _send_error(
                            ws,
                            "empty_transcription",
                            "Could not transcribe audio. Please try speaking again.",
                        )
                        continue
                    try:
                        turn_idx = int(payload.get("turn_idx", handle.turn_idx))
                    except (TypeError, ValueError):
                        await _send_error(
                            ws,
                            "invalid_turn",
                            "Invalid turn index for this answer.",
                        )
                        continue
                    pending_video_signals = payload.get("video_signals")
                    await ws.send_text(
                        json.dumps(
                            {
                                "type": "draft_transcript",
                                "turn_idx": turn_idx,
                                "content": transcript,
                            }
                        )
                    )
                    continue
                elif payload.get("type") == "submit_transcript":
                    if mode == "asr_only":
                        await _send_error(
                            ws,
                            "unsupported_frame",
                            "ASR-only voice connections cannot submit answers.",
                        )
                        continue
                    content = str(payload.get("content") or "").strip()
                    if not content:
                        await _send_error(
                            ws,
                            "empty_transcription",
                            "Could not transcribe audio. Please try speaking again.",
                        )
                        continue
                    try:
                        turn_idx = int(payload.get("turn_idx", handle.turn_idx))
                    except (TypeError, ValueError):
                        await _send_error(
                            ws,
                            "invalid_turn",
                            "Invalid turn index for this answer.",
                        )
                        continue
                    video_signals = payload.get("video_signals") or pending_video_signals
                    llm_config = payload.get("llm_config")
                    llm_config = llm_config if isinstance(llm_config, dict) else None
                    if llm_config is not None:
                        handle.llm_config = llm_config
                    try:
                        _submit_voice_answer(
                            manager,
                            session_id,
                            content,
                            turn_idx=turn_idx,
                            video_signals=video_signals,
                            llm_config=llm_config,
                        )
                    except ValueError as e:
                        error, message = _submit_error_payload(e)
                        await _send_error(ws, error, message)
                        continue
                    pending_video_signals = None
                    log.info(
                        "answer_submitted session=%s has_video=%s",
                        session_id, isinstance(video_signals, dict),
                    )
                    await ws.send_text(json.dumps({"type": "transcript", "content": content}))
                    has_more = await _push_question(ws, handle)
                    if not has_more:
                        await _send_final(ws, handle)
                        return
                elif payload.get("type") == "cancel":
                    log.info("ws explicit cancel session=%s", session_id)
                    explicit_cancel = True
                    break
    except WebSocketDisconnect:
        client_closed = True
        log.info("ws client disconnected for session=%s", session_id)
    finally:
        buffer.clear(session_id)
        # A normal voice-channel disconnect should not end a durable
        # interview: the same session can continue in the text UI with
        # its current checkpoint. We only cancel on an explicit client
        # cancel, or for the legacy sync-provider path where a blocked
        # provider waiter would otherwise leak.
        if explicit_cancel or getattr(handle, "use_sync_provider", False):
            loop = asyncio.get_running_loop()
            try:
                await loop.run_in_executor(_VOICE_EXECUTOR, manager.cancel, session_id)
            except Exception as e:  # pragma: no cover
                log.warning("ws finally cancel failed for %s: %s", session_id, e)
        if not client_closed:
            try:
                await ws.close()
            except Exception as e:  # pragma: no cover
                log.debug("ws close failed for %s: %s", session_id, e)
        reset_log_context(log_token)


async def _send_final(ws: WebSocket, handle: SessionHandle) -> None:
    report = (handle.final_state or {}).get("final_report") if handle.final_state else None
    await ws.send_text(json.dumps({"type": "final_report", "report": report}))


def _parse_text(text: str) -> dict[str, Any]:
    if len(text.encode("utf-8")) > MAX_TEXT_FRAME_BYTES:
        return {"type": "invalid", "error": "text_frame_too_large"}
    try:
        raw = json.loads(text)
    except json.JSONDecodeError:
        return {"type": "invalid", "error": "invalid_json"}
    if not isinstance(raw, dict) or not isinstance(raw.get("type"), str):
        return {"type": "invalid", "error": "invalid_frame"}

    frame_type = raw["type"]
    try:
        if frame_type == "auth":
            return AuthFrame.model_validate(raw).model_dump(exclude_none=True)
        if frame_type == "cancel":
            return CancelFrame.model_validate(raw).model_dump()
        if frame_type == "stop":
            return _dump_frame_with_soft_video_signals(StopFrame.model_validate(raw))
        if frame_type == "submit_transcript":
            return _dump_frame_with_soft_video_signals(
                SubmitTranscriptFrame.model_validate(raw)
            )
    except ValidationError:
        return {"type": "invalid", "error": "invalid_frame"}

    return {"type": "invalid", "error": "invalid_frame"}


def _dump_frame_with_soft_video_signals(frame: BaseModel) -> dict[str, Any]:
    payload = frame.model_dump(exclude_none=True)
    if "video_signals" not in payload:
        return payload
    normalized = normalize_video_signals(payload.get("video_signals"))
    if normalized is None:
        payload.pop("video_signals", None)
    else:
        payload["video_signals"] = normalized
    return payload


def _submit_voice_answer(
    manager: Any,
    session_id: str,
    content: str,
    *,
    turn_idx: int,
    video_signals: Any,
    llm_config: dict[str, Any] | None,
) -> None:
    if isinstance(video_signals, dict):
        manager.submit_answer(
            session_id,
            content,
            turn_idx=turn_idx,
            video_signals=video_signals,
            llm_config=llm_config,
        )
        return
    manager.submit_answer(
        session_id,
        content,
        turn_idx=turn_idx,
        llm_config=llm_config,
    )
