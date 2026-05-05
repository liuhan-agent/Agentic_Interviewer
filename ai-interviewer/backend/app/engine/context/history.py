"""Shared helper: build the history block used in the generator prompt.

Lifted out of ``engine.agents.generator`` so both the legacy code path
and the new :mod:`app.engine.context.builder` render an identical
string. Keeping one implementation eliminates drift risk and lets the
Phase 0 equivalence test guard the invariant mechanically.

Note: ``format_summary_for_prompt`` is imported lazily inside
:func:`build_history_section` to break a circular import between
``engine.context`` and ``engine.agents.session_summarizer`` (the
latter reaches back into ``engine.context`` for its builder/renderer
pair). Keeping the top-level module import graph acyclic lets
top-level process entrypoints (``app.scripts.*``) boot without
relying on a prior test-suite run to prime ``sys.modules``.
"""
from __future__ import annotations

import json
from typing import Any

__all__ = ["build_history_section"]


def build_history_section(
    recent_qa: list[dict[str, Any]],
    qa_summary: str = "",
) -> str:
    """Assemble the QA-history block for the generator prompt.

    When a compressed summary is available, it stands in for older
    turns and only the most recent 3 turns are included verbatim.
    This mirrors Claude Code's two-tier pattern (session-memory
    summary + recent verbatim window) but in structured interview
    form.
    """
    parts: list[str] = []
    if qa_summary:
        # Render JSON-shaped summaries (produced by the LLM summariser)
        # into human/LLM-friendly bullet lines; deterministic strings
        # are returned unchanged. The import is local to sidestep the
        # ``context`` <-> ``session_summarizer`` module-import cycle
        # (see the module docstring).
        from app.engine.agents.session_summarizer import (
            format_summary_for_prompt,
        )

        rendered = format_summary_for_prompt(qa_summary)
        parts.append(
            "INTERVIEW_HISTORY_SUMMARY (earlier turns, compressed) =\n"
            + rendered
        )
    recent = recent_qa[-3:]
    if recent:
        parts.append(
            "RECENT_QA (verbatim) = " + json.dumps(recent, ensure_ascii=False)
        )
    if not parts:
        parts.append("RECENT_QA = []")
    return "\n".join(parts)
