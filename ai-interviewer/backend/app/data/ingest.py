"""Higher-level ingestion entrypoint.

Wraps :mod:`app.engine.rag.ingestion` with a PII redaction pre-pass so
anything that reaches the vector store is already safe to search
against.
"""
from __future__ import annotations

import re
from pathlib import Path

from app.core.logging import get_logger
from app.data.clean import redact_pii
from app.engine.rag.vectorstore import get_vectorstore

log = get_logger(__name__)


CHUNK_SIZE = 600
CHUNK_OVERLAP = 80

_PARA_RE = re.compile(r"\n{2,}")
# Split after CJK and ASCII sentence terminators.  Look-behind keeps
# the terminator attached to the preceding sentence so a chunk always
# ends on a real boundary, not in the middle of "however,"-style
# comma splits.
_SENT_SPLIT_RE = re.compile(r"(?<=[。！？!?.\n])")


def _split(text: str) -> list[str]:
    """Sentence-aware chunker with hard length cap.

    Behaviour:

    - Paragraphs (separated by blank lines) flush their own buffer.
    - Inside a paragraph, sentences accumulate until adding one more
      would exceed :data:`CHUNK_SIZE`.  At that point the buffer is
      flushed and the next chunk starts with the last
      :data:`CHUNK_OVERLAP` characters of the previous chunk, so
      retrieval still sees the surrounding context.
    - A single sentence that is itself longer than :data:`CHUNK_SIZE`
      (rare in prose, common in code blocks or log lines) degrades to
      fixed-width splitting so we never emit a chunk bigger than the
      cap.

    The output is always a list of non-empty strings.  An empty or
    whitespace-only input returns an empty list.
    """
    text = text.strip()
    if not text:
        return []
    if len(text) <= CHUNK_SIZE:
        return [text]

    chunks: list[str] = []
    buf = ""

    def flush() -> None:
        nonlocal buf
        if buf.strip():
            chunks.append(buf)
        buf = ""

    def start_with_overlap(next_piece: str) -> str:
        if CHUNK_OVERLAP > 0 and chunks:
            tail = chunks[-1][-CHUNK_OVERLAP:]
            return tail + next_piece
        return next_piece

    for para in _PARA_RE.split(text):
        for sent in _SENT_SPLIT_RE.split(para):
            if not sent:
                continue
            if len(sent) > CHUNK_SIZE:
                flush()
                step = max(1, CHUNK_SIZE - CHUNK_OVERLAP)
                for i in range(0, len(sent), step):
                    piece = sent[i : i + CHUNK_SIZE]
                    if piece:
                        chunks.append(piece)
                continue
            if len(buf) + len(sent) <= CHUNK_SIZE:
                buf += sent
            else:
                flush()
                buf = start_with_overlap(sent)
        flush()

    return [c for c in chunks if c.strip()]


def ingest_text(text: str, *, source: str) -> int:
    """Redact, chunk, and store a single text blob.

    Returns the number of chunks added.
    """
    result = redact_pii(text)
    chunks = _split(result.cleaned)
    if not chunks:
        return 0
    metas = [
        {"source": source, "chunk": idx, "redactions": result.redactions}
        for idx in range(len(chunks))
    ]
    get_vectorstore().add(chunks, metas)
    return len(chunks)


def ingest_file(path: Path, *, source_type: str = "misc") -> int:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        log.warning("skipping %s: %s", path, e)
        return 0
    return ingest_text(text, source=f"{source_type}/{path.name}")
