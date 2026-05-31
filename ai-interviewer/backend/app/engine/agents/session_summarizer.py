"""LLM-backed session summariser for long interviews.

Legacy helper retained for standalone tests and old summaries. The hot
path now uses HistoryContextBuilder inside ``ask_question``; the
``turn_finalize`` node no longer invokes this summarizer when ``summary_mode`` is
``"llm"`` or when ``"auto"`` decides the interview is long enough
to justify the extra call. Produces a structured per-dimension digest
the Generator agent consumes on subsequent turns instead of the full
``qa_history``.

Contract
--------
Input
    - ``job_title`` / ``job_level``: interview framing
    - ``existing_summary``: the previous digest, or the empty string
    - ``new_turns``: the newly-compressed ``QATurn`` list

Output (structured)
    ``{"by_dimension": {<dim>: {progression, key_evidence, gaps}},
       "overall_trajectory": str,
       "summary_version": int}``

The summariser is defensive: any LLM failure or unparsable reply
falls back to returning the unchanged ``existing_summary`` so the
caller can degrade to deterministic aggregation without a stack
trace interrupting the interview.
"""
from __future__ import annotations

import json
from typing import Any

from app.core.logging import get_logger

from .llm_client import call_chat, parse_json_response

# NOTE: ``app.engine.context`` imports ``app.engine.context.history``
# from its ``__init__.py``, which in turn imports ``format_summary_for_prompt``
# from *this* module. Pulling ``app.engine.context`` at module scope
# would therefore close a circular import loop that surfaces the
# moment the import order changes (e.g. after an ``isort`` / ``ruff
# --fix`` pass). We defer the two context-builder imports to the one
# call site that needs them (``summarise_session``) via a lazy
# function-local import below.

log = get_logger(__name__)


def _sanitise_turn(turn: dict[str, Any]) -> dict[str, Any]:
    """Drop bulky/irrelevant fields from a QATurn before JSONifying.

    We feed the summariser only the signals it actually needs; the
    raw prompt context, retrieval snippets, etc. would bloat tokens
    without improving the digest.
    """
    evaluation = turn.get("evaluation") or {}
    return {
        "turn_idx": turn.get("turn_idx"),
        "dimension": turn.get("dimension"),
        "question": turn.get("question"),
        "answer": turn.get("answer"),
        "selected_action": turn.get("selected_action"),
        "score": evaluation.get("score"),
        "passed": evaluation.get("passed"),
        "strengths": evaluation.get("strengths") or [],
        "weaknesses": evaluation.get("weaknesses") or [],
        "rubric_coverage": evaluation.get("rubric_coverage") or {},
    }


def _validate(payload: object) -> dict[str, Any] | None:
    """Return ``payload`` only if it matches the schema we promised.

    We don't want a rogue reply to poison the generator prompt, so
    structural mismatches are treated the same as a hard failure:
    caller falls back to the previous summary.
    """
    if not isinstance(payload, dict):
        return None
    by_dim = payload.get("by_dimension")
    if not isinstance(by_dim, dict):
        return None

    cleaned_by_dim: dict[str, dict[str, Any]] = {}
    for dim, entry in by_dim.items():
        if not isinstance(dim, str) or not isinstance(entry, dict):
            continue
        cleaned_by_dim[dim] = {
            "progression": str(entry.get("progression") or ""),
            "key_evidence": [
                str(x) for x in (entry.get("key_evidence") or []) if x
            ],
            "gaps": [str(x) for x in (entry.get("gaps") or []) if x],
        }
    if not cleaned_by_dim:
        return None

    version = payload.get("summary_version")
    try:
        version_int = int(version) if version is not None else 1
    except (TypeError, ValueError):
        version_int = 1

    return {
        "by_dimension": cleaned_by_dim,
        "overall_trajectory": str(payload.get("overall_trajectory") or ""),
        "summary_version": version_int,
    }


def summarise_session(
    *,
    job_title: str,
    job_level: str,
    new_turns: list[dict[str, Any]],
    existing_summary: str,
) -> str:
    """Return a JSON-serialised structured digest, or ``existing_summary``.

    The caller stores whatever this returns on ``state.qa_summary``.
    If anything goes wrong we return ``existing_summary`` unchanged so
    the generator still has *some* historical context.
    """
    if not new_turns:
        return existing_summary

    sanitised = [_sanitise_turn(t) for t in new_turns]
    # Lazy import — ``app.engine.context`` imports
    # ``app.memory.strategy_store`` which pulls logging+settings, so
    # we defer until first call to dodge the cycle when this module is
    # imported during FastAPI startup (``engine/__init__`` is on the
    # hot path for both ``engine.agents`` and ``engine.context``).
    from app.engine.context import (
        build_context_frame_for_session_summarizer,
        frame_to_session_summarizer_messages,
    )

    frame = build_context_frame_for_session_summarizer(
        job_title=job_title,
        job_level=job_level,
        existing_summary=existing_summary,
        new_turns=sanitised,
    )
    messages = frame_to_session_summarizer_messages(frame)
    try:
        raw = call_chat(messages, json_mode=True, agent_role="session_summarizer")
        data = parse_json_response(raw)
    except Exception as e:  # pragma: no cover - provider flakes
        log.warning("session_summarizer LLM call failed, keeping prior summary: %s", e)
        return existing_summary

    cleaned = _validate(data)
    if cleaned is None:
        log.info(
            "session_summarizer reply did not match schema; keeping prior summary"
        )
        return existing_summary

    return json.dumps(cleaned, ensure_ascii=False)


def format_summary_for_prompt(qa_summary: str) -> str:
    """Render a possibly-structured ``qa_summary`` into prompt-friendly text.

    If ``qa_summary`` is a JSON string produced by this module, we
    expand it into a compact per-dimension bullet list. Otherwise we
    return the string unchanged so deterministic summaries (plain
    legacy summary text still renders.
    """
    if not qa_summary:
        return ""
    stripped = qa_summary.strip()
    if not stripped.startswith("{"):
        return qa_summary
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        return qa_summary

    cleaned = _validate(payload)
    if cleaned is None:
        return qa_summary

    lines: list[str] = []
    trajectory = cleaned.get("overall_trajectory") or ""
    if trajectory:
        lines.append(f"Overall: {trajectory}")
    for dim, entry in cleaned["by_dimension"].items():
        lines.append(f"[{dim}]")
        prog = entry.get("progression")
        if prog:
            lines.append(f"  Progression: {prog}")
        evidence = entry.get("key_evidence") or []
        if evidence:
            lines.append("  Key evidence:")
            lines.extend(f"    - {e}" for e in evidence)
        gaps = entry.get("gaps") or []
        if gaps:
            lines.append("  Gaps:")
            lines.extend(f"    - {g}" for g in gaps)
    return "\n".join(lines)
