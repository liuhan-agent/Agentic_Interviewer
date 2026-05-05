"""Speech-to-text for the voice channel.

The class hides the provider behind a ``transcribe(bytes) -> str``
method so the WebSocket handler stays transport-only. Stub mode just
echoes a canned phrase, which is enough for Phase-3 integration
testing without an OpenAI key.
"""
from __future__ import annotations

from app.core.logging import get_logger
from app.core.settings import get_settings

log = get_logger(__name__)


# Whisper accepts these file extensions. Anything outside this set
# must be normalised or we risk ``Invalid file format`` errors at the
# API boundary (silently empty transcription from the client's POV).
# Source: OpenAI Whisper documentation; MP4/M4A are covered because
# iOS Safari sends ``audio/mp4`` for MediaRecorder captures.
_WHISPER_EXTENSIONS: set[str] = {
    "mp3",
    "mp4",
    "mpeg",
    "mpga",
    "m4a",
    "wav",
    "webm",
    "flac",
    "ogg",
    "oga",
}


# Common MIME subtype aliases encountered in the wild -> a Whisper
# extension. We deliberately keep the map tiny so a regression is
# easy to spot; unknown subtypes fall through to ``webm`` (the
# browser MediaRecorder default) which Whisper decodes reliably.
_MIME_SUBTYPE_ALIASES: dict[str, str] = {
    "x-wav": "wav",
    "x-m4a": "m4a",
    "vnd.wav": "wav",
    "aac": "m4a",  # AAC bare stream is typically repackaged as m4a
    "opus": "ogg",
}


def _extension_for_mime(mime_type: str) -> str:
    """Derive a Whisper-safe file extension from a MIME type string.

    Handles the three real-world hazards that the naive
    ``mime_type.split('/')[-1]`` version missed:

    1. **Codec parameters**: ``audio/webm;codecs=opus`` must become
       ``webm``, not ``webm;codecs=opus``.
    2. **Vendor-prefixed subtypes**: ``audio/x-wav`` resolves to
       ``wav`` via the alias table.
    3. **Unknown subtypes**: anything we do not recognise is clamped
       to ``webm`` so the Whisper SDK accepts the filename; the
       actual bytes determine decoding either way.

    The helper is side-effect-free and exported at module level so
    tests can pin the decision table without instantiating the ASR
    client.
    """
    if not mime_type:
        return "webm"
    raw = mime_type.split("/", 1)[-1]
    subtype = raw.split(";", 1)[0].strip().lower()
    if not subtype:
        return "webm"
    mapped = _MIME_SUBTYPE_ALIASES.get(subtype, subtype)
    if mapped in _WHISPER_EXTENSIONS:
        return mapped
    return "webm"


class WhisperASR:
    """Calls OpenAI Whisper on a single audio buffer.

    ``transcribe`` expects the complete utterance as bytes - the WS
    handler is responsible for collecting audio into reasonable
    utterance-sized chunks (VAD or an explicit stop signal).
    """

    def __init__(self) -> None:
        settings = get_settings()
        self.model = settings.asr_model
        self.stub = settings.use_stub_llm or settings.asr_provider == "stub"
        self._client = None
        if not self.stub:
            try:
                from openai import OpenAI

                self._client = OpenAI(api_key=settings.openai_api_key)
            except ImportError:  # pragma: no cover
                log.warning("openai package unavailable; ASR will use stub mode")
                self.stub = True

    def transcribe(self, audio: bytes, *, mime_type: str = "audio/webm") -> str:
        """Transcribe a complete utterance.

        Returns an empty string on any provider-side failure or empty
        input so the caller can decide how to degrade (e.g. the WS
        handler refuses to ``submit_answer("")`` and asks the user to
        speak again). We never raise here because killing the
        interview over an ASR hiccup is strictly worse than re-asking.
        """
        if self.stub:
            return "(stub transcription) the candidate spoke for a few seconds."
        if not audio:
            return ""
        import io

        buf = io.BytesIO(audio)
        buf.name = f"utterance.{_extension_for_mime(mime_type)}"
        try:
            result = self._client.audio.transcriptions.create(
                model=self.model, file=buf
            )
        except Exception as e:  # pragma: no cover - provider flakes
            log.warning("ASR provider call failed: %s", e)
            return ""
        return getattr(result, "text", "") or ""


_asr: WhisperASR | None = None


def get_asr() -> WhisperASR:
    global _asr
    if _asr is None:
        _asr = WhisperASR()
    return _asr
