"""Context compression node — keeps state lean across long interviews.

Inspired by Claude Code's session-memory compaction pattern, but
adapted for structured interview data. Two execution modes:

- ``deterministic`` (default): the original path. Old QA turns are
  folded into a per-dimension digest via deterministic aggregation
  (scores + actions + strength/weakness set unions). Zero extra LLM
  cost, zero latency.
- ``llm``: calls :mod:`app.engine.agents.session_summarizer` to build
  a structured, narrative digest (progression / key_evidence / gaps).
  Strictly more informative but costs one LLM call per compression
  pass.
- ``auto``: uses deterministic while ``qa_history`` is short
  (< :data:`AUTO_LLM_THRESHOLD` turns), upgrades to LLM once the
  interview reaches that length.

Mode is picked from (in priority order):

1. ``state.runtime_config.summary_mode`` — per-session override
2. ``Settings.default_summary_mode`` — global default (still
   ``"deterministic"`` to keep the default zero-cost)

LLM failures always degrade to the deterministic path so the graph
keeps flowing if the provider is flaky.
"""
from __future__ import annotations

import time
from typing import Any, Literal

from app.core.logging import get_logger
from app.core.tracer import get_tracer
from app.engine.agents.session_summarizer import summarise_session
from app.engine.workflow.routers import route_after_eval_diagnostics
from app.engine.workflow.state import InterviewState, QATurn

from .wait_answer import clear_raw_answer_for_state

log = get_logger(__name__)

RECENT_TURNS_TO_KEEP = 2
COMPRESS_AFTER = 3
MAX_MESSAGES_KEPT = 8

SummaryMode = Literal["deterministic", "llm", "auto"]
AUTO_LLM_THRESHOLD = 6


def _resolve_summary_mode(state: InterviewState) -> SummaryMode:
    """Decide which summary path to run this pass.

    Precedence: runtime_config override > Settings default > hardcoded
    ``"deterministic"`` fallback. Unknown values degrade silently to
    ``"deterministic"`` rather than raising, so a bad .env never
    breaks the graph.
    """
    rc = state.get("runtime_config") or {}
    mode_raw = rc.get("summary_mode")
    if mode_raw is None:
        try:
            from app.core.settings import get_settings

            mode_raw = getattr(get_settings(), "default_summary_mode", "deterministic")
        except Exception:  # pragma: no cover - defensive
            mode_raw = "deterministic"

    if mode_raw in ("deterministic", "llm", "auto"):
        return mode_raw  # type: ignore[return-value]
    return "deterministic"


def _dim_digest(turns: list[QATurn]) -> str:
    """One-paragraph digest for all turns on a single dimension."""
    if not turns:
        return ""
    scores = [
        t.get("evaluation", {}).get("score", "?")
        for t in turns
    ]
    actions = [t.get("selected_action", "?") for t in turns]
    strengths: list[str] = []
    weaknesses: list[str] = []
    for t in turns:
        ev = t.get("evaluation", {})
        strengths.extend(ev.get("strengths", [])[:2])
        weaknesses.extend(ev.get("weaknesses", [])[:2])

    lines = [
        f"  Turns: {len(turns)} | Scores: {', '.join(str(s) for s in scores)}",
        f"  Actions: {', '.join(str(a) for a in actions)}",
    ]
    if strengths:
        lines.append(f"  Key strengths: {'; '.join(dict.fromkeys(strengths))})")
    if weaknesses:
        lines.append(f"  Key gaps: {'; '.join(dict.fromkeys(weaknesses))}")
    return "\n".join(lines)


def _build_summary(
    existing_summary: str,
    old_turns: list[QATurn],
) -> str:
    """Merge newly old turns into the running summary."""
    if not old_turns:
        return existing_summary

    by_dim: dict[str, list[QATurn]] = {}
    for t in old_turns:
        dim = t.get("dimension", "general")
        by_dim.setdefault(dim, []).append(t)

    new_block_parts: list[str] = []
    for dim, turns in sorted(by_dim.items()):
        new_block_parts.append(f"[{dim}]")
        new_block_parts.append(_dim_digest(turns))

    new_block = "\n".join(new_block_parts)

    if existing_summary:
        return existing_summary + "\n---\n" + new_block
    return new_block


def _build_llm_summary(
    state: InterviewState,
    existing_summary: str,
    new_turns: list[QATurn],
) -> str:
    """Delegate to the session summariser agent, degrading on failure.

    A failed or schema-invalid LLM reply returns ``existing_summary``
    unchanged, so the caller still has a coherent digest to persist.
    We flag the degrade so operational logs can catch provider flakes
    without terminating the interview.
    """
    job_spec = state.get("job_spec") or {}
    try:
        summary = summarise_session(
            job_title=str(job_spec.get("title") or ""),
            job_level=str(job_spec.get("level") or "mid"),
            new_turns=list(new_turns),
            existing_summary=existing_summary or "",
        )
    except Exception as e:  # pragma: no cover - defensive
        log.warning(
            "compress_context: llm summariser raised (%s); keeping prior summary",
            e,
        )
        return existing_summary
    if summary == existing_summary:
        log.info("compress_context: llm summariser degraded, prior summary retained")
    return summary


def _clear_raw_answer_if_set(state: InterviewState) -> dict[str, Any]:
    """Return the update that clears ``current_answer_raw``.

    Emitted only when the field is non-empty so the rest of the
    graph's state reducer graph remains a strict superset of the
    "no change" shape (nodes returning ``{}`` trigger no reducer
    calls at all). The clear is a single-turn-ephemeral contract owned
    by this node: ``wait_answer`` stores raw text in a process-local
    side-channel, evaluator and verifier read it, and
    ``compress_context`` erases both the side-channel ref and any
    legacy raw state before the next ``director_sample``.
    """
    if clear_raw_answer_for_state(state):
        return {"current_answer_raw": "", "current_answer_raw_ref": ""}
    return {}


def _trace_compress_context(
    state: InterviewState,
    update: dict[str, Any],
    *,
    reason: str,
    node_started_at: float,
    compressed_turns: int = 0,
) -> None:
    try:
        get_tracer().trace_node_event(
            {**state, **update},
            node="compress_context",
            payload={
                "reason": reason,
                "compressed_turns": compressed_turns,
                "cleared_raw_answer": "current_answer_raw" in update,
                "elapsed_ms": int((time.perf_counter() - node_started_at) * 1000),
            },
        )
    except Exception as e:  # pragma: no cover - side channel
        log.warning("compress_context tracer side-channel failed: %s", e)


def _trace_route_decision(state: InterviewState, update: dict[str, Any]) -> None:
    """Record the post-evaluation router decision for rhythm audits."""
    route_state = {**state, **update}
    evaluation = route_state.get("evaluation") or {}
    question = route_state.get("current_question") or {}
    diagnostics = route_after_eval_diagnostics(route_state)
    decision = diagnostics.get("decision")
    try:
        get_tracer().trace_node_event(
            route_state,
            node="route_decision",
            payload={
                "router": "route_after_eval",
                "decision": decision,
                "next_node": diagnostics.get("next_node"),
                "decision_reason": diagnostics.get("decision_reason"),
                "decision_inputs": diagnostics.get("decision_inputs") or {},
                "dimension": (
                    question.get("dimension")
                    or route_state.get("current_dimension")
                    or "unknown"
                ),
                "recommended_next": evaluation.get("recommended_next"),
                "recommended_next_plan": evaluation.get("recommended_next_plan"),
                "recommended_probe_intent": evaluation.get("recommended_probe_intent"),
                "passed": bool(evaluation.get("passed")),
                "evaluation_source": evaluation.get("source"),
                "fallback_reason": evaluation.get("fallback_reason"),
                "fallback": bool(
                    evaluation.get("source") == "fallback"
                    or evaluation.get("fallback_reason")
                ),
                "formal_turn_idx": route_state.get("formal_turn_idx"),
                "max_turns": route_state.get("max_turns"),
                "turn_budget_remaining": route_state.get("turn_budget_remaining"),
            },
            logical_turn_idx=max(0, int(route_state.get("turn_idx", 0)) - 1),
        )
    except Exception as e:  # pragma: no cover - side channel
        log.warning("route_decision tracer side-channel failed: %s", e)


def compress_context_node(state: InterviewState) -> dict[str, Any]:
    node_started_at = time.perf_counter()
    qa_history = state.get("qa_history", [])
    last_compressed = state.get("qa_summary_through_turn", -1)

    if len(qa_history) < COMPRESS_AFTER:
        # Even when there is nothing to compress yet, we still own the
        # raw-answer clear contract - skipping it here would leak the
        # unredacted answer side-channel into the next turn.
        update = _clear_raw_answer_if_set(state)
        _trace_compress_context(
            state,
            update,
            reason="below_threshold",
            node_started_at=node_started_at,
        )
        _trace_route_decision(state, update)
        return update

    # Partition: old turns vs recent turns
    boundary = max(0, len(qa_history) - RECENT_TURNS_TO_KEEP)
    old_turns = qa_history[:boundary]

    # Only compress turns we haven't compressed yet
    new_old_turns = [
        t for t in old_turns
        if t.get("turn_idx", -1) > last_compressed
    ]

    if not new_old_turns:
        update = _clear_raw_answer_if_set(state)
        _trace_compress_context(
            state,
            update,
            reason="no_new_turns",
            node_started_at=node_started_at,
        )
        _trace_route_decision(state, update)
        return update

    existing_summary = state.get("qa_summary", "")
    mode = _resolve_summary_mode(state)

    use_llm = mode == "llm" or (
        mode == "auto" and len(qa_history) >= AUTO_LLM_THRESHOLD
    )
    if use_llm:
        updated_summary = _build_llm_summary(state, existing_summary, new_old_turns)
    else:
        updated_summary = _build_summary(existing_summary, new_old_turns)

    max_compressed_idx = max(
        (t.get("turn_idx", -1) for t in new_old_turns), default=last_compressed
    )

    log.info(
        "compress_context: mode=%s compressed %d turns (through turn %d), "
        "summary length %d chars",
        "llm" if use_llm else "deterministic",
        len(new_old_turns),
        max_compressed_idx,
        len(updated_summary),
    )

    update: dict[str, Any] = {
        "qa_summary": updated_summary,
        "qa_summary_through_turn": max_compressed_idx,
    }
    update.update(_clear_raw_answer_if_set(state))
    _trace_compress_context(
        state,
        update,
        reason="compressed",
        node_started_at=node_started_at,
        compressed_turns=len(new_old_turns),
    )
    _trace_route_decision(state, update)
    return update
