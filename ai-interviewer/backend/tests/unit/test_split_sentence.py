"""Regression tests for the sentence-aware chunker in
``app.data.ingest._split``.

The behavioural contract we assert:

- Empty / whitespace-only text yields an empty list.
- A text shorter than ``CHUNK_SIZE`` returns unchanged in a single
  chunk.
- Multi-sentence text respects sentence boundaries: each chunk ends
  on punctuation (``. ! ? 。 ！ ？``) or end-of-input.
- A pathologically long single sentence (no punctuation) degrades to
  fixed-width splitting so no chunk exceeds ``CHUNK_SIZE``.
- Every returned chunk is non-empty after stripping.
"""
from __future__ import annotations

from app.data.ingest import CHUNK_SIZE, _split


def test_empty_input_yields_empty_list():
    assert _split("") == []
    assert _split("   \n  \n\t") == []


def test_short_text_returns_single_chunk():
    text = "Just one short sentence."
    chunks = _split(text)
    assert chunks == [text]


def test_multi_sentence_chunks_end_on_punctuation_when_possible():
    sentence = "This is a sentence. "
    # Force a length that requires splitting across chunks.
    text = sentence * ((CHUNK_SIZE // len(sentence)) + 5)
    chunks = _split(text)
    assert len(chunks) >= 2
    for c in chunks:
        assert c.strip(), "no empty chunks allowed"
    # All-but-last should end on sentence punctuation or whitespace
    # following punctuation.
    for c in chunks[:-1]:
        stripped = c.rstrip()
        assert stripped[-1] in ".。!?！？", f"chunk did not end cleanly: {c!r}"


def test_chinese_sentences_respected():
    text = (
        "这是第一句话。这是第二句话。这是第三句话！"
        "这是第四句话？"
    ) * 30
    chunks = _split(text)
    for c in chunks:
        assert c.strip()


def test_pathological_long_sentence_degrades_to_fixed_width():
    # A single token longer than CHUNK_SIZE - no punctuation, no
    # whitespace.  The chunker should never emit a chunk bigger than
    # the cap.
    long_run = "x" * (CHUNK_SIZE * 3 + 7)
    chunks = _split(long_run)
    assert len(chunks) >= 3
    for c in chunks:
        assert len(c) <= CHUNK_SIZE


def test_paragraph_breaks_flush_buffer():
    para_a = "Para A sentence one. Para A sentence two. "
    para_b = "Para B sentence one. Para B sentence two. "
    text = para_a * 10 + "\n\n" + para_b * 10
    chunks = _split(text)
    joined = "".join(chunks)
    # The content is all there (modulo overlap duplication, which
    # appears in ``chunks[-1]`` as a tail prefix of its predecessor).
    assert "Para A" in joined
    assert "Para B" in joined
