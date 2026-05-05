"""Per-session audio buffer manager.

Collects WS frames into utterance-sized blobs. "End of utterance" can
be signalled either explicitly by the client (a ``stop`` text frame)
or, in a future revision, by a VAD hook. For MVP we rely on explicit
signals because it keeps the code dependency-free.
"""
from __future__ import annotations

import threading
from collections import defaultdict


class AudioBuffer:
    """Thread-safe per-session byte buffer."""

    def __init__(self) -> None:
        self._buffers: defaultdict[str, bytearray] = defaultdict(bytearray)
        self._lock = threading.Lock()

    def append(self, session_id: str, chunk: bytes) -> None:
        with self._lock:
            self._buffers[session_id].extend(chunk)

    def flush(self, session_id: str) -> bytes:
        with self._lock:
            data = bytes(self._buffers[session_id])
            self._buffers[session_id] = bytearray()
            return data

    def clear(self, session_id: str) -> None:
        with self._lock:
            self._buffers.pop(session_id, None)


_buffer = AudioBuffer()


def get_audio_buffer() -> AudioBuffer:
    return _buffer
