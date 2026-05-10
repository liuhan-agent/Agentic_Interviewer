"""Provider adapters for voice ASR/TTS."""
from __future__ import annotations

import base64
import json
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlencode

from app.voice.routing import QWEN_REALTIME_BASE_URL, VoiceRoute


class OpenAIClientFactory(Protocol):
    def __call__(self, **kwargs: Any) -> Any: ...


class QwenConnectFactory(Protocol):
    async def __call__(self, url: str, *, additional_headers: dict[str, str]) -> Any: ...


@dataclass(frozen=True)
class QwenAudioPayload:
    audio_b64: str
    raw_audio: bytes
    format: str
    sample_rate: int | None = None


QWEN_AUDIO_CHUNK_BYTES = 32000


def _qwen_audio_payload(audio: bytes, mime_type: str = "audio/webm") -> QwenAudioPayload:
    if _is_wav_mime(mime_type) and audio.startswith(b"RIFF"):
        pcm, sample_rate = _extract_pcm_from_wav(audio)
        return QwenAudioPayload(
            audio_b64=base64.b64encode(pcm).decode("ascii"),
            raw_audio=pcm,
            format="pcm",
            sample_rate=sample_rate,
        )
    return QwenAudioPayload(
        audio_b64=base64.b64encode(audio).decode("ascii"),
        raw_audio=audio,
        format="opus",
    )


def _iter_audio_chunks(audio: bytes, chunk_size: int = QWEN_AUDIO_CHUNK_BYTES) -> list[bytes]:
    if chunk_size <= 0 or len(audio) <= chunk_size:
        return [audio]
    return [audio[i : i + chunk_size] for i in range(0, len(audio), chunk_size)]


def _is_wav_mime(mime_type: str) -> bool:
    normalized = (mime_type or "").split(";", 1)[0].strip().lower()
    return normalized in {"audio/wav", "audio/wave", "audio/x-wav"}


def _extract_pcm_from_wav(data: bytes) -> tuple[bytes, int]:
    if len(data) < 44 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise ValueError("invalid wav header")
    offset = 12
    sample_rate = 16000
    pcm: bytes | None = None
    while offset + 8 <= len(data):
        chunk_id = data[offset : offset + 4]
        chunk_size = int.from_bytes(data[offset + 4 : offset + 8], "little")
        chunk_start = offset + 8
        chunk_end = min(chunk_start + chunk_size, len(data))
        if chunk_id == b"fmt " and chunk_size >= 16:
            sample_rate = int.from_bytes(data[chunk_start + 4 : chunk_start + 8], "little")
        elif chunk_id == b"data":
            pcm = data[chunk_start:chunk_end]
            break
        offset = chunk_end + (chunk_size % 2)
    if pcm is None:
        raise ValueError("wav data chunk not found")
    return pcm, sample_rate


def _realtime_url(route: VoiceRoute) -> str:
    base = (route.base_url or QWEN_REALTIME_BASE_URL).rstrip()
    separator = "&" if "?" in base else "?"
    return f"{base}{separator}{urlencode({'model': route.model})}"


def _qwen_headers(route: VoiceRoute) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {route.api_key}",
        "OpenAI-Beta": "realtime=v1",
    }


async def _default_qwen_connect(url: str, *, additional_headers: dict[str, str]) -> Any:
    import websockets

    return await websockets.connect(url, additional_headers=additional_headers)


async def _close_ws(ws: Any) -> None:
    close = getattr(ws, "close", None)
    if close is None:
        return
    result = close()
    if hasattr(result, "__await__"):
        await result


class OpenAIVoiceProvider:
    def transcribe(
        self,
        route: VoiceRoute,
        *,
        file: Any,
        existing_client: Any = None,
        client_factory: OpenAIClientFactory | None = None,
    ) -> str:
        client = existing_client
        if client is None or client_factory is not None:
            if client_factory is None:
                from openai import OpenAI

                client_factory = OpenAI
            client = client_factory(api_key=route.api_key, base_url=route.base_url)
        result = client.audio.transcriptions.create(model=route.model, file=file)
        return getattr(result, "text", "") or ""

    async def synth(
        self,
        route: VoiceRoute,
        text: str,
        *,
        existing_client: Any = None,
        client_factory: OpenAIClientFactory | None = None,
    ) -> AsyncIterator[bytes]:
        client = existing_client
        if client is None or client_factory is not None:
            if client_factory is None:
                from openai import AsyncOpenAI

                client_factory = AsyncOpenAI
            client = client_factory(api_key=route.api_key, base_url=route.base_url)
        async with client.audio.speech.with_streaming_response.create(
            model=route.model,
            voice=route.voice,
            input=text,
        ) as response:
            async for chunk in response.iter_bytes():
                yield chunk


class QwenVoiceProvider:
    async def check_asr_session(
        self,
        route: VoiceRoute,
        *,
        connect_factory: QwenConnectFactory | None = None,
    ) -> str:
        connect = connect_factory or _default_qwen_connect
        ws = await connect(_realtime_url(route), additional_headers=_qwen_headers(route))
        try:
            await ws.send(
                json.dumps(
                    {
                        "type": "session.update",
                        "session": {
                            "input_audio_format": "opus",
                            "input_audio_transcription": {"model": route.model},
                            "turn_detection": None,
                        },
                    },
                    ensure_ascii=False,
                )
            )
            for _ in range(20):
                event = _parse_event(await ws.recv())
                event_type = str(event.get("type") or "")
                if event_type == "session.updated":
                    return event_type
                if event_type in {"error", "response.error"}:
                    raise RuntimeError(event.get("message") or event.get("error") or event)
            return "session.checked"
        finally:
            await _close_ws(ws)

    async def transcribe_async(
        self,
        route: VoiceRoute,
        audio: bytes,
        *,
        mime_type: str = "audio/webm",
        connect_factory: QwenConnectFactory | None = None,
    ) -> str:
        connect = connect_factory or _default_qwen_connect
        audio_payload = _qwen_audio_payload(audio, mime_type)
        ws = await connect(_realtime_url(route), additional_headers=_qwen_headers(route))
        transcript = ""
        try:
            audio_chunks = _iter_audio_chunks(audio_payload.raw_audio)
            session: dict[str, Any] = {
                "input_audio_format": audio_payload.format,
                "input_audio_transcription": {"model": route.model},
                "turn_detection": None,
            }
            if audio_payload.sample_rate:
                session["sample_rate"] = audio_payload.sample_rate
            await ws.send(
                json.dumps(
                    {
                        "type": "session.update",
                        "session": session,
                    },
                    ensure_ascii=False,
                )
            )
            for chunk in audio_chunks:
                await ws.send(
                    json.dumps(
                        {
                            "type": "input_audio_buffer.append",
                            "audio": base64.b64encode(chunk).decode("ascii"),
                        }
                    )
                )
            await ws.send(json.dumps({"type": "input_audio_buffer.commit"}))
            await ws.send(json.dumps({"type": "session.finish"}))
            for _ in range(200):
                event = _parse_event(await ws.recv())
                event_type = str(event.get("type") or "")
                text = event.get("transcript") or event.get("text")
                if isinstance(text, str) and text.strip():
                    transcript = text.strip()
                if event_type.endswith("completed") or event_type in {
                    "session.finished",
                    "response.done",
                }:
                    if transcript:
                        return transcript
                    if isinstance(event.get("transcript"), str):
                        return str(event["transcript"]).strip()
                    if event_type == "session.finished":
                        return transcript
                if event_type in {"error", "response.error"}:
                    raise RuntimeError(event.get("message") or event.get("error") or event)
        finally:
            await _close_ws(ws)
        return transcript

    async def synth(
        self,
        route: VoiceRoute,
        text: str,
        *,
        connect_factory: QwenConnectFactory | None = None,
    ) -> AsyncIterator[bytes]:
        connect = connect_factory or _default_qwen_connect
        ws = await connect(_realtime_url(route), additional_headers=_qwen_headers(route))
        try:
            await ws.send(
                json.dumps(
                    {
                        "type": "session.update",
                        "session": {
                            "voice": route.voice or "Cherry",
                            "output_audio_format": "mp3",
                            "modalities": ["audio"],
                        },
                    },
                    ensure_ascii=False,
                )
            )
            await ws.send(
                json.dumps(
                    {
                        "type": "input_text_buffer.append",
                        "text": text,
                    },
                    ensure_ascii=False,
                )
            )
            await ws.send(json.dumps({"type": "input_text_buffer.commit"}))
            await ws.send(json.dumps({"type": "session.finish"}))
            for _ in range(500):
                event = _parse_event(await ws.recv())
                event_type = str(event.get("type") or "")
                delta = event.get("delta") or event.get("audio")
                if isinstance(delta, str) and delta:
                    yield base64.b64decode(delta)
                    if event_type in {"response.audio.delta", "audio"}:
                        continue
                if event_type in {"response.done", "session.finished"}:
                    return
                if event_type in {"error", "response.error"}:
                    raise RuntimeError(event.get("message") or event.get("error") or event)
        finally:
            await _close_ws(ws)


def _parse_event(raw: Any) -> dict[str, Any]:
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    if isinstance(raw, str):
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    return raw if isinstance(raw, dict) else {}


def provider_for(route: VoiceRoute) -> OpenAIVoiceProvider | QwenVoiceProvider:
    if route.provider == "qwen":
        return QwenVoiceProvider()
    return OpenAIVoiceProvider()
