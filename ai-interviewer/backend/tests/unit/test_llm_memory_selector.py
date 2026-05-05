"""Tests for :mod:`app.memory.llm_selector`.

Verifies the three layers that must hold for Claude Code-parity
``findRelevantMemories.sideQuery`` behaviour:

1. Input handling — empty candidates must not call the LLM.
2. Manifest rendering — stable, matches the shape Claude Code
   expects selectors to read.
3. Output parsing — robust to fenced JSON, hallucinated filenames,
   and oversized selections; every failure mode falls back to
   ``None`` so callers can keep their keyword top-N.
"""
from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch

from app.memory.llm_selector import (
    MemoryCandidate,
    SelectorContext,
    _build_manifest,
    _parse_selection,
    select_memories_with_llm,
)

_DEFAULT_DIMS = ["system_design", "leadership"]
_DEFAULT_LEVELS = ["senior", "staff"]


def _candidate(
    *,
    filename: str = "senior_backend.md",
    name: str = "Senior Backend Ownership",
    dimensions: list[str] | None = None,
    job_levels: list[str] | None = None,
    kind: str = "skill",
) -> MemoryCandidate:
    # ``is None`` check so callers can pass ``[]`` to model a
    # dimension-agnostic / level-agnostic card without the default
    # silently kicking back in via truthiness fallback.
    return MemoryCandidate(
        filename=filename,
        name=name,
        description="Probe ownership, not buzzwords.",
        kind=kind,
        dimensions=(
            list(_DEFAULT_DIMS) if dimensions is None else list(dimensions)
        ),
        job_levels=(
            list(_DEFAULT_LEVELS) if job_levels is None else list(job_levels)
        ),
    )


def _context(**overrides: Any) -> SelectorContext:
    base = {
        "dimension": "system_design",
        "job_level": "senior",
        "purpose": "generator",
        "recent_qa_summary": "",
    }
    base.update(overrides)
    return SelectorContext(**base)


def test_empty_candidates_returns_empty_list_no_llm_call() -> None:
    """Caller should unconditionally skip the LLM when no candidates
    pass keyword filtering. Any network call on an empty input is a
    bug — assert via a patch that ``call_chat`` is NOT invoked.
    """
    with patch(
        "app.memory.llm_selector.call_chat"
    ) as mock_call_chat:
        result = select_memories_with_llm([], _context(), top_n=5)

    assert result == []
    mock_call_chat.assert_not_called()


def test_top_n_zero_returns_empty_list_no_llm_call() -> None:
    with patch(
        "app.memory.llm_selector.call_chat"
    ) as mock_call_chat:
        result = select_memories_with_llm(
            [_candidate()], _context(), top_n=0
        )

    assert result == []
    mock_call_chat.assert_not_called()


def test_manifest_format_matches_claude_code_shape() -> None:
    """Manifest must carry: ``kind`` tag, filename, dim/level tags,
    name, description — readable by both humans and LLMs and
    byte-stable across renderer tweaks."""
    candidates = [
        _candidate(
            filename="a.md",
            name="A-skill",
            dimensions=["system_design"],
            job_levels=["senior"],
        ),
        _candidate(
            filename="b.md",
            name="B-strategy",
            dimensions=[],
            job_levels=[],
            kind="strategy",
        ),
    ]
    manifest = _build_manifest(candidates)

    assert "[skill] a.md" in manifest
    assert "[strategy] b.md" in manifest
    # Universal-skill rendering
    assert "dims=system_design" in manifest
    assert "dims=all | levels=all" in manifest  # for b.md
    # The description must appear
    assert "Probe ownership" in manifest


def test_parse_selection_accepts_plain_json() -> None:
    raw = json.dumps({"selected": ["a.md", "b.md"]})
    result = _parse_selection(raw, {"a.md", "b.md", "c.md"}, top_n=5)
    assert result == ["a.md", "b.md"]


def test_parse_selection_strips_fenced_json() -> None:
    raw = "```json\n" + json.dumps({"selected": ["a.md"]}) + "\n```"
    result = _parse_selection(raw, {"a.md"}, top_n=5)
    assert result == ["a.md"]


def test_parse_selection_rejects_hallucinated_filenames() -> None:
    raw = json.dumps({"selected": ["a.md", "not_a_real_file.md", "b.md"]})
    result = _parse_selection(raw, {"a.md", "b.md"}, top_n=5)
    # Hallucinated filename dropped; preserved order.
    assert result == ["a.md", "b.md"]


def test_parse_selection_deduplicates() -> None:
    raw = json.dumps({"selected": ["a.md", "a.md", "b.md", "a.md"]})
    result = _parse_selection(raw, {"a.md", "b.md"}, top_n=5)
    assert result == ["a.md", "b.md"]


def test_parse_selection_respects_top_n() -> None:
    raw = json.dumps({"selected": ["a.md", "b.md", "c.md", "d.md"]})
    result = _parse_selection(
        raw, {"a.md", "b.md", "c.md", "d.md"}, top_n=2
    )
    assert result == ["a.md", "b.md"]


def test_parse_selection_returns_none_on_invalid_json() -> None:
    assert _parse_selection("this is not json", {"a.md"}, top_n=5) is None


def test_parse_selection_returns_none_when_selected_is_not_a_list() -> None:
    raw = json.dumps({"selected": "a.md"})
    assert _parse_selection(raw, {"a.md"}, top_n=5) is None


def test_select_end_to_end_with_stubbed_call_chat() -> None:
    """Full function: stubbed ``call_chat`` returns a valid selection;
    final output preserves the LLM order and filters hallucinations
    in one pass."""
    candidates = [
        _candidate(filename="a.md", name="A"),
        _candidate(filename="b.md", name="B"),
        _candidate(filename="c.md", name="C"),
    ]

    def fake_call_chat(messages: Any, **_: Any) -> str:
        return json.dumps({"selected": ["c.md", "a.md", "fake.md"]})

    with patch(
        "app.memory.llm_selector.call_chat",
        side_effect=fake_call_chat,
    ):
        result = select_memories_with_llm(
            candidates, _context(), top_n=5
        )

    assert result == ["c.md", "a.md"]


def test_select_returns_none_on_call_chat_exception() -> None:
    def _boom(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("provider down")

    with patch("app.memory.llm_selector.call_chat", side_effect=_boom):
        result = select_memories_with_llm(
            [_candidate()], _context(), top_n=5
        )

    assert result is None


def test_select_returns_none_on_unparsable_reply() -> None:
    """Provider returned arbitrary prose instead of JSON; the selector
    must NOT guess and must hand control back to the keyword
    fallback."""
    with patch(
        "app.memory.llm_selector.call_chat",
        return_value="I'm not sure, pick what you like.",
    ):
        result = select_memories_with_llm(
            [_candidate()], _context(), top_n=5
        )

    assert result is None


def test_select_returns_empty_list_when_llm_explicitly_chooses_nothing() -> None:
    """LLM says ``{"selected":[]}`` -> selector returns ``[]`` (not
    ``None``): this is a valid "nothing relevant" signal and the
    caller should respect it rather than fall back to keyword."""
    with patch(
        "app.memory.llm_selector.call_chat",
        return_value=json.dumps({"selected": []}),
    ):
        result = select_memories_with_llm(
            [_candidate()], _context(), top_n=5
        )

    assert result == []
