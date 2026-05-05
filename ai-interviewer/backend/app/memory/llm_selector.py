"""LLM-powered memory selector (Claude Code ``findRelevantMemories.sideQuery`` equivalent).

The existing :func:`app.memory.skill_store.retrieve_skills` and
:func:`app.memory.strategy_store.retrieve_strategies` do the cheap
keyword + static-score first pass. This module takes that candidate
list and runs **one** lightweight LLM side query to pick the
top-N filenames that are semantically most relevant to the current
turn, mirroring Claude Code's
``src/memdir/findRelevantMemories.ts::findRelevantMemories``:

- Input: keyword-filtered ``MemoryCandidate[]`` + ``SelectorContext``
- LLM call: ``call_chat([system, user], json_mode=True,
  agent_role="memory_selector")``
- Output: ``list[str]`` of selected filenames; ``None`` on any
  failure so the caller can unconditionally fall back to the
  keyword top-N without special-casing.

Design constraints
------------------
- **Never raises**: every LLM / parsing exception becomes a
  log.debug + ``None`` return. Memory selection is observational —
  a transient provider issue must not surface as an interview-time
  crash.
- **Bounded cost**: ``max_tokens=256``, ``temperature=0.3``, no
  tools, single-turn. Typical response is < 100 tokens of JSON.
- **Hallucination guard**: parser filters every returned filename
  against the input candidate set, so a model invention cannot
  redirect the caller to a non-existent file.
- **Top-N cap**: hard truncates at ``top_n`` regardless of what the
  LLM returns, protecting downstream prompt-budget invariants.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from app.core.logging import get_logger
from app.engine.agents.llm_client import ChatMessage, call_chat
from app.engine.agents.prompts.loader import render_prompt

log = get_logger(__name__)

__all__ = [
    "MemoryCandidate",
    "SelectorContext",
    "select_memories_with_llm",
]


@dataclass
class MemoryCandidate:
    """One memory file presented to the selector.

    ``kind`` is ``"skill"`` / ``"strategy"`` so the selector prompt
    can group the two layers in the manifest without letting callers
    pre-commit to one view. ``filename`` is the only stable identity
    the selector is allowed to return.
    """

    filename: str
    name: str
    description: str
    kind: str = "skill"
    dimensions: list[str] = field(default_factory=list)
    job_levels: list[str] = field(default_factory=list)


@dataclass
class SelectorContext:
    """Contextual signals passed to the selector so it can do
    semantic routing rather than blind ranking.

    ``purpose`` flags which agent is about to consume the selection
    (``generator`` / ``evaluator`` / ``coach``); the selector prompt
    may bias its ranking differently per purpose. ``recent_qa_summary``
    is optional and empty when the caller has no compressed view
    ready (e.g. the first turn of an interview).
    """

    dimension: str
    job_level: str = "mid"
    purpose: str = "generator"
    recent_qa_summary: str = ""


def _build_manifest(candidates: list[MemoryCandidate]) -> str:
    """Render the input candidate list as a line-oriented manifest
    string, one bullet per candidate.

    Format matches Claude Code's ``formatMemoryManifest``: the
    selector LLM sees just enough metadata (name + description +
    dim/level tags) to rank relevance, without reading any file
    body. Keeping this readable also means a human can paste the
    same manifest into a prompt for debugging.
    """
    if not candidates:
        return "(empty — nothing to select from)"
    lines: list[str] = []
    for c in candidates:
        dims = ", ".join(c.dimensions) if c.dimensions else "all"
        levels = ", ".join(c.job_levels) if c.job_levels else "all"
        desc = (c.description or "").strip() or "(no description)"
        lines.append(
            f"- [{c.kind}] {c.filename} (dims={dims} | levels={levels}): "
            f"{c.name} — {desc}"
        )
    return "\n".join(lines)


def _parse_selection(
    raw: str, allowed: set[str], top_n: int
) -> list[str] | None:
    """Parse ``{"selected": ["name.md", ...]}`` robustly.

    - Accepts arbitrary leading / trailing prose around the JSON
      object because stub / non-strict providers sometimes wrap it.
    - Filters every name against ``allowed`` so hallucinated files
      cannot redirect the caller.
    - Truncates the result at ``top_n`` so a model returning 20
      filenames still respects the caller's budget.
    - Returns ``None`` when no valid JSON was produced so the caller
      knows to use its keyword fallback instead of a bogus empty
      list.
    """
    if not raw:
        return None
    text = raw.strip()
    # Strip optional ```json fences the same way ``parse_json_response`` does.
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        data: Any = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end <= start:
            return None
        try:
            data = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return None
    if not isinstance(data, dict):
        return None
    raw_selected = data.get("selected")
    if not isinstance(raw_selected, list):
        return None
    out: list[str] = []
    seen: set[str] = set()
    for name in raw_selected:
        if not isinstance(name, str):
            continue
        if name not in allowed:
            continue
        if name in seen:
            continue
        seen.add(name)
        out.append(name)
        if len(out) >= top_n:
            break
    return out


def select_memories_with_llm(
    candidates: list[MemoryCandidate],
    context: SelectorContext,
    *,
    top_n: int = 5,
) -> list[str] | None:
    """Run one side-query LLM call and return the selected filenames.

    Parameters
    ----------
    candidates
        Keyword-filtered candidate list from a memory store. Empty
        input returns an empty list without touching the LLM.
    context
        Current ``(dimension, job_level, purpose, recent_qa_summary)``.
    top_n
        Hard cap on the number of returned filenames. Default 5
        matches Claude Code's ``findRelevantMemories`` behaviour.

    Returns
    -------
    list[str] | None
        Selected filenames preserving the LLM-returned order, or
        ``None`` on any failure. Callers should treat ``None`` as
        "use keyword fallback" and treat ``[]`` as "LLM explicitly
        refused to pick anything" (still a valid signal — the prompt
        above tells the model to prefer empty over irrelevant).
    """
    if not candidates:
        return []
    if top_n < 1:
        return []

    allowed = {c.filename for c in candidates}
    manifest = _build_manifest(candidates)

    messages = [
        ChatMessage(
            "system",
            "You are a precise memory selector. Respond only with JSON.",
        ),
        ChatMessage(
            "user",
            render_prompt(
                "memory_selector.md",
                dimension=context.dimension,
                job_level=context.job_level,
                purpose=context.purpose,
                recent_qa_summary=context.recent_qa_summary or "(none)",
                candidates_manifest=manifest,
                top_n=top_n,
            ),
        ),
    ]
    try:
        raw = call_chat(
            messages,
            json_mode=True,
            temperature=0.3,
            max_tokens=256,
            agent_role="memory_selector",
        )
    except Exception as e:  # pragma: no cover - provider flake
        log.debug("memory_selector call_chat failed, falling back: %s", e)
        return None

    parsed = _parse_selection(raw, allowed, top_n)
    if parsed is None:
        log.debug(
            "memory_selector produced an unparsable reply, falling back"
        )
        return None
    return parsed
