"""Block until an answer is available.

Two execution models are supported, selected at runtime so the same
node code can back both the synchronous CLI demo and the durable
HITL (human-in-the-loop) API / WebSocket flow:

1. **Durable interrupt (default)** - the node calls
   ``langgraph.types.interrupt`` with a payload describing the pending
   question. The graph pauses, LangGraph persists the state via the
   configured checkpointer (``MemorySaver`` or ``PostgresSaver``), and
   ``stream(...)`` terminates. When the client later submits an
   answer the caller resumes with ``Command(resume=answer)`` and
   control re-enters this node with the answer already in hand. That
   is what unlocks "resumable across process restarts" when the
   Postgres checkpointer is enabled.

2. **Synchronous provider** - used by the CLI/demo / integration
   tests that drive ``workflow.invoke`` in a single thread. The
   caller sets ``runtime_config.use_sync_provider = True`` and
   registers a :class:`StaticAnswerProvider`; the node just reads the
   next answer from that provider with no LangGraph interrupt
   involved.

The switch is explicit (``runtime_config`` flag) rather than implicit
("is a provider registered?") so that the same process can run both
paths side-by-side without one accidentally hijacking the other.
"""
from __future__ import annotations

import secrets
import time
from typing import Any

from app.core.logging import get_logger
from app.core.settings import get_settings
from app.data.clean import redact_pii
from app.engine.agents.security import check_answer
from app.engine.workflow.answer_lifecycle import classify_answer_intent
from app.engine.workflow.state import InterviewState

from .answer_provider import (
    AnswerProvider,
    ProviderCancelled,
    StaticAnswerProvider,
    get_provider,
)

log = get_logger(__name__)
# Raw answer side-channel: kept in-process so unredacted text never
# reaches the LangGraph checkpointer / DB / trace rows. Each entry is
# ``(answer, expires_at_monotonic)``; entries older than the TTL are
# evicted lazily on read so a graph that crashes between
# ``wait_answer`` and ``compress_context`` does not keep raw text in
# memory forever.
_RAW_ANSWER_STORE: dict[str, tuple[str, float]] = {}


def _raw_answer_ttl_seconds() -> float:
    """Read TTL from settings on each call so env tweaks land for new entries.

    Falls back to 300s if settings cannot be read — that's the historical
    hard-coded default and matches existing tests.
    """
    try:
        return float(get_settings().raw_answer_ttl_seconds)
    except Exception:
        return 300.0


def _now_monotonic() -> float:
    """Indirection so tests can monkeypatch the clock cleanly."""
    return time.monotonic()


def _evict_expired() -> int:
    """Remove expired entries lazily; return count of evictions."""
    now = _now_monotonic()
    expired = [ref for ref, (_, exp) in _RAW_ANSWER_STORE.items() if exp <= now]
    for ref in expired:
        _RAW_ANSWER_STORE.pop(ref, None)
    return len(expired)


def _store_raw_answer(answer: str) -> str:
    # Best-effort eviction every write keeps the dict from growing
    # unboundedly even if no read ever lands on the same ref.
    _evict_expired()
    ref = secrets.token_urlsafe(16)
    _RAW_ANSWER_STORE[ref] = (
        answer,
        _now_monotonic() + _raw_answer_ttl_seconds(),
    )
    return ref


def get_raw_answer_for_state(state: InterviewState) -> str:
    ref = state.get("current_answer_raw_ref") or ""
    if isinstance(ref, str) and ref:
        entry = _RAW_ANSWER_STORE.get(ref)
        if entry is None:
            return ""
        answer, expires_at = entry
        if expires_at <= _now_monotonic():
            _RAW_ANSWER_STORE.pop(ref, None)
            return ""
        return answer
    # Legacy checkpoints may still contain this field from older builds.
    return state.get("current_answer_raw") or ""


def clear_raw_answer_for_state(state: InterviewState) -> bool:
    ref = state.get("current_answer_raw_ref") or ""
    removed = False
    if isinstance(ref, str) and ref:
        removed = _RAW_ANSWER_STORE.pop(ref, None) is not None
    return removed or bool(state.get("current_answer_raw") or ref)


def _resolve_provider(state: InterviewState) -> AnswerProvider:
    session_id = state.get("session_id") or ""
    provider = get_provider(session_id)
    if provider is None:
        return StaticAnswerProvider(["(no answer configured)"])
    return provider


def _use_sync_provider(state: InterviewState) -> bool:
    rc = state.get("runtime_config") or {}
    return bool(rc.get("use_sync_provider"))


def _extract_answer(payload: Any) -> tuple[str, bool, bool, str | None, dict[str, Any] | None]:
    """Normalise the payload that came back from ``Command(resume=...)``.

    Returns ``(answer_text, cancelled, skipped, skip_reason, video_signals)``. The cancel
    channel is an explicit ``{"__cancelled__": True}`` marker so plain
    string answers like the word "cancel" do not accidentally tear
    down a live session.
    """
    if isinstance(payload, dict):
        if payload.get("__cancelled__"):
            return "", True, False, None, None
        if payload.get("__skipped__"):
            reason = payload.get("reason")
            return (
                "__skip_question__",
                False,
                True,
                str(reason) if reason is not None else None,
                None,
            )
        video = payload.get("video_signals")
        return (
            str(payload.get("answer", "")),
            False,
            False,
            None,
            video if isinstance(video, dict) else None,
        )
    if isinstance(payload, str):
        return payload, False, False, None, None
    return "", False, False, None, None


def answer_log_metrics(
    answer: str,
    redaction_note: dict[str, int] | None,
    verdict: Any,
    question: dict[str, Any],
    turn_idx: int,
) -> dict[str, Any]:
    return {
        "turn_idx": turn_idx,
        "answer_length": len(answer or ""),
        "dimension": question.get("dimension"),
        "pii_redaction_count": sum((redaction_note or {}).values()),
        "guardrail_blocked": not bool(getattr(verdict, "allowed", True)),
    }


def wait_answer_node(state: InterviewState) -> dict[str, Any]:
    # Fast path: the session was already marked cancelled upstream
    # (e.g. by ``SessionManager.cancel`` setting the flag via
    # ``update_state`` before the graph even reached this node). In
    # that case there is nothing to wait for - we record an empty
    # answer and let the conditional edge route straight to
    # ``final_report``.
    if state.get("status") == "cancelled":
        log.info("wait_answer: session already cancelled, skipping wait")
        return {"current_answer": "", "status": "cancelled"}

    turn_idx = state.get("turn_idx", 0)
    question = state.get("current_question") or {}

    cancelled = False
    video_sigs: dict[str, Any] | None = None
    if _use_sync_provider(state):
        provider = _resolve_provider(state)
        try:
            answer = provider.get(turn_idx, question)
        except ProviderCancelled as e:
            # Graceful cancel path: the SessionManager flipped the
            # provider's cancel flag (e.g. because the WebSocket client
            # dropped) so our wait aborts without a spurious answer and
            # the router sends us straight to ``final_report``.
            log.info("wait_answer turn=%d cancelled via provider (%s)", turn_idx, e)
            return {"current_answer": "", "status": "cancelled"}
        except Exception as e:  # pragma: no cover
            log.exception("answer provider failed: %s", e)
            answer = ""
    else:
        # Lazy import: the graph module is imported by both server and
        # offline tooling; the interrupt symbol is only needed at
        # runtime and lives under langgraph.types where availability
        # depends on the installed langgraph version.
        from langgraph.types import interrupt

        payload = interrupt(
            {
                "kind": "answer_needed",
                "turn_idx": turn_idx,
                "question": question,
                "dimension": state.get("current_dimension"),
            }
        )
        answer, cancelled, skipped, skip_reason, video_sigs = _extract_answer(payload)
        if cancelled:
            log.info("wait_answer turn=%d cancelled by client", turn_idx)
            return {"current_answer": "", "status": "cancelled"}
        if skipped:
            log.info("wait_answer turn=%d skipped by client", turn_idx)
            return {
                "current_answer": "",
                "current_answer_intent": "skipped",
                "skip_reason": skip_reason,
            }

    runtime_config = state.get("runtime_config") or {}
    previous_answers = [
        str(qa.get("answer") or "")
        for qa in state.get("qa_history", [])
    ]
    answer_intent = classify_answer_intent(answer, previous_answers)
    verdict = check_answer(answer, runtime_config=runtime_config)
    safety_note = None
    raw_answer = answer
    if not verdict.allowed:
        log.warning("security blocked answer (%s); redacting", verdict.reason)
        safety_note = verdict.reason
        answer = "[redacted by guardrail]"
        raw_answer = ""  # do not keep a raw copy of blocked content

    # PII redaction: store a sanitised copy in state while keeping the
    # unredacted text in a process-local side-channel so evaluator /
    # verifier can still judge the real answer without checkpointing it.
    keep_raw = False
    redaction_note: dict[str, int] | None = None
    if answer and answer != "[redacted by guardrail]":
        try:
            redact_enabled = get_settings().redact_answer_pii
        except Exception:  # pragma: no cover - defensive
            redact_enabled = True
        if redact_enabled:
            result = redact_pii(answer)
            if any(result.redactions.values()):
                redaction_note = result.redactions
                raw_answer = answer
                answer = result.cleaned
                keep_raw = True
        # The guard agent may also have produced a structured
        # ``redacted_text`` under hybrid/llm_only; prefer its output
        # when available because it has additional context (e.g.
        # distinguishing a harmless phone-number-in-docs from a real
        # contact number).
        if verdict.redacted_text and verdict.redacted_text != answer:
            raw_answer = raw_answer or answer
            answer = verdict.redacted_text
            keep_raw = True

    metrics = answer_log_metrics(
        answer,
        redaction_note,
        verdict,
        question,
        turn_idx,
    )
    log.info(
        "wait_answer turn=%d answer_length=%d dimension=%s "
        "pii_redaction_count=%d guardrail_blocked=%s",
        metrics["turn_idx"],
        metrics["answer_length"],
        metrics["dimension"],
        metrics["pii_redaction_count"],
        metrics["guardrail_blocked"],
    )
    video_signals = video_sigs if not _use_sync_provider(state) else None
    raw_ref = _store_raw_answer(raw_answer) if keep_raw else ""
    update: dict[str, Any] = {
        "current_answer": answer,
        "current_answer_intent": answer_intent,
        "current_answer_raw": "",
        "current_answer_raw_ref": raw_ref,
        "video_signals": video_signals,
        "messages": [
            {
                "role": "user",
                "turn_idx": turn_idx,
                "kind": "answer",
                "content": answer,
                "safety_note": safety_note,
                "pii_redactions": redaction_note,
            }
        ],
    }
    return update
