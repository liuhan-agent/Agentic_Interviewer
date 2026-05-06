"""Durable HITL session manager.

Execution model
---------------
The LangGraph workflow uses ``interrupt()`` in ``wait_answer_node``
to pause execution whenever it needs a candidate answer.  Each call
to ``workflow.stream(...)`` drives the graph from one interrupt to
the next (or to ``END``).  Between interrupts, all state lives in
the LangGraph checkpointer (MemorySaver or PostgresSaver) and in
the ``interview_sessions`` DB row, so a process restart loses
nothing.

Resume path:  ``submit_answer`` re-enters the graph with
``Command(resume=answer)`` on a short-lived background thread.
The thread runs until the graph either interrupts again or
finishes.

Rehydration:  ``rehydrate()`` scans ``interview_sessions`` for
rows with ``status='interrupted'`` and rebuilds lightweight
``SessionHandle`` objects so ``poll_question`` / ``submit_answer``
work immediately after a cold start.

Backwards compatibility:  callers that set
``runtime_config.use_sync_provider = True`` (CLI demo, tests) still
get the old ``QueueAnswerProvider`` path inside ``wait_answer_node``.
The session manager detects this and falls back to the legacy
blocking-thread model.
"""
from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from app.core.logging import bind_log_context, get_logger, reset_log_context
from app.core.settings import get_settings
from app.core.timing import reset_timing_trace, start_timing_trace
from app.services.session_registry import SessionRegistry

# Per-session LLM override, readable by call_chat via get_llm_override().
_llm_override_var: ContextVar[dict[str, Any] | None] = ContextVar(
    "llm_override", default=None
)

# Per-session SessionHandle pointer, so call_chat can attribute LLM calls to
# the right interview without importing the manager-level _sessions registry.
# Set at the top of every ``_run_segment`` / legacy worker; reset in finally.
# ``Any`` rather than the (forward-declared) SessionHandle keeps ruff UP037
# happy under ``from __future__ import annotations`` while still fully
# expressing the runtime contract via the function signatures below.
_current_session_handle_var: ContextVar[Any] = ContextVar(
    "current_session_handle", default=None
)


def get_llm_override() -> dict[str, Any] | None:
    """Read the per-session LLM config set by the session-manager thread."""
    return _llm_override_var.get()


def get_current_session_handle() -> SessionHandle | None:
    """Read the SessionHandle bound to the running interview thread, if any."""
    return _current_session_handle_var.get()


def record_session_llm_call(
    *,
    provider: str,
    model: str,
    status: str,
    prompt_tokens: int,
    completion_tokens: int,
    usage_estimated: bool = False,
) -> None:
    """Accumulate one LLM call's tokens onto the active SessionHandle.

    Called from ``call_chat`` exit (success / error / stub). When no
    handle is bound (e.g. ``temporary_llm_override`` for resume parse,
    background prefetch, or unit tests that don't go through the
    session manager), the function is a no-op.
    """
    handle = _current_session_handle_var.get()
    if handle is None:
        return
    handle.llm_call_count += 1
    if status == "stub":
        handle.llm_stub_call_count += 1
    elif status == "error":
        handle.llm_error_call_count += 1
    handle.prompt_tokens_total += max(0, int(prompt_tokens or 0))
    handle.completion_tokens_total += max(0, int(completion_tokens or 0))
    if usage_estimated:
        handle.cost_usage_estimated = True
    handle.touch()


@contextmanager
def temporary_llm_override(config: dict[str, Any] | None):
    """Temporarily expose BYOK config to ``call_chat`` outside a session.

    ``POST /resume/parse`` runs before a session exists, but it should
    still be able to use the same BYOK routing rules as in-session
    agents. This context manager reuses the existing ContextVar and
    resets it immediately after the upload request finishes.
    """
    token = _llm_override_var.set(config)
    try:
        yield
    finally:
        _llm_override_var.reset(token)


def _safe_llm_config_meta(config: dict[str, Any] | None) -> dict[str, Any] | None:
    if not config:
        return None

    requires_reauth = False

    def clean(value: Any) -> Any:
        nonlocal requires_reauth
        if isinstance(value, dict):
            result: dict[str, Any] = {}
            for key, item in value.items():
                if key == "api_key":
                    if item:
                        requires_reauth = True
                    continue
                cleaned = clean(item)
                if cleaned not in (None, {}, []):
                    result[key] = cleaned
            return result
        if isinstance(value, list):
            return [item for item in (clean(item) for item in value) if item is not None]
        return value

    meta = clean(config)
    if not isinstance(meta, dict):
        meta = {}
    meta["requires_reauth"] = requires_reauth
    return meta


HintSource = str


_NON_FEEDBACK_INTENTS = {"empty", "clarification", "repeat", "too_short", "skipped"}


def _extract_last_turn_evaluation(
    qa_history: list[dict[str, Any]] | None,
) -> dict[str, Any] | None:
    """Project the most recent ``qa_history`` entry's evaluation into the
    UI-friendly summary surfaced by ``GET /question`` and consumed by
    ``InterviewRoom``'s in-interview feedback card.

    Returns ``None`` (i.e. "no displayable feedback this turn") when:

    - There is no prior turn yet (first ask),
    - The candidate's answer was non-scoring (empty / clarification / repeat /
      too_short / skipped),
    - The evaluator fell back to a deterministic stub for that turn (LLM
      outage), so the score is not real signal,
    - The turn was an explicit skip.

    The projection is deliberately small (≤ 2 strengths / weaknesses) to
    keep the in-interview UI compact and to avoid leaking long-form
    rubric prose into the polling response body. The full structured
    evaluation still lives in ``state.qa_history`` for the report.
    """
    if not qa_history:
        return None
    last = qa_history[-1]
    if not isinstance(last, dict):
        return None
    if last.get("answer_intent") in _NON_FEEDBACK_INTENTS:
        return None
    evaluation = last.get("evaluation")
    if not isinstance(evaluation, dict) or not evaluation:
        return None
    if evaluation.get("source") == "fallback" or evaluation.get("fallback_reason"):
        return None
    if evaluation.get("skipped"):
        return None

    strengths = evaluation.get("strengths") or []
    weaknesses = evaluation.get("weaknesses") or []
    rubric_coverage = evaluation.get("rubric_coverage") or {}
    return {
        "turn_idx": last.get("turn_idx"),
        "dimension": last.get("dimension"),
        "score": evaluation.get("score"),
        "passed": bool(evaluation.get("passed", False)),
        "strengths": [str(s) for s in strengths[:2]] if isinstance(strengths, list) else [],
        "weaknesses": [str(w) for w in weaknesses[:2]] if isinstance(weaknesses, list) else [],
        "rubric_coverage": dict(rubric_coverage) if isinstance(rubric_coverage, dict) else {},
    }


def _hint_items(values: Any, *, limit: int = 3) -> list[str]:
    if not isinstance(values, list):
        return []
    items: list[str] = []
    for value in values:
        text = " ".join(str(value or "").strip().split())
        if not text or text in items:
            continue
        items.append(text)
        if len(items) >= limit:
            break
    return items


def _join_hint_items(items: list[str]) -> str:
    if len(items) <= 1:
        return items[0] if items else ""
    return "、".join(items[:-1]) + f"和{items[-1]}"


def _resume_anchor_label(anchor: Any) -> str:
    if not isinstance(anchor, dict):
        return ""
    return " ".join(
        str(
            anchor.get("project_name")
            or anchor.get("label")
            or anchor.get("project_id")
            or ""
        )
        .strip()
        .split()
    )


def _scrub_direct_answer_language(text: str) -> str:
    forbidden = {
        "标准答案": "参考方向",
        "完整答案": "完整思路",
        "你可以直接说": "可以考虑",
        "照抄": "展开",
        "直接回答": "先回应",
    }
    result = text
    for bad, replacement in forbidden.items():
        result = result.replace(bad, replacement)
    return result


def build_interview_hint(question: dict[str, Any]) -> dict[str, Any]:
    """Build a short candidate-facing hint without scoring or graph mutation."""
    contract = question.get("contract") if isinstance(question, dict) else None
    must_cover = _hint_items(
        contract.get("must_cover") if isinstance(contract, dict) else None,
        limit=3,
    )
    if must_cover:
        hint = (
            f"可以先围绕{_join_hint_items(must_cover)}组织回答；"
            "不用急着展开细节，先讲清你的判断顺序和取舍理由。"
        )
        return {"hint": _scrub_direct_answer_language(hint), "source": "contract"}

    target_skills = _hint_items(question.get("target_skills"), limit=3)
    if target_skills:
        hint = (
            f"可以把切入点放在{_join_hint_items(target_skills)}上，"
            "先说明它解决了什么问题，再补一句你如何验证效果。"
        )
        return {"hint": _scrub_direct_answer_language(hint), "source": "target_skills"}

    anchor_label = _resume_anchor_label(question.get("resume_anchor"))
    if anchor_label:
        hint = (
            f"可以先借{anchor_label}这个经历开场，"
            "按背景、你的动作、结果验证三个层次展开。"
        )
        return {"hint": _scrub_direct_answer_language(hint), "source": "resume_anchor"}

    return {
        "hint": (
            "可以先用三步整理：这个问题的核心目标是什么，主要约束有哪些，"
            "你会用什么信号验证方案有效。"
        ),
        "source": "fallback",
    }


# The imports below intentionally sit after ``get_llm_override`` so
# that ``app.engine.agents.llm_client`` — which runs a lazy
# ``from app.services.session_manager import get_llm_override`` the
# first time ``call_chat`` fires — finds the helper defined before
# the ``langgraph_workflow`` chain starts pulling more modules. The
# sequence breaks a latent circular import; ``ruff: noqa: E402`` is
# therefore deliberate and must survive future formatter passes.
from app.engine.workflow.langgraph_workflow import build_workflow  # noqa: E402
from app.engine.workflow.nodes.answer_provider import (  # noqa: E402
    QueueAnswerProvider,
    register_provider,
    unregister_provider,
)
from app.engine.workflow.state import InterviewState  # noqa: E402
from app.models.base import get_session as get_db_session  # noqa: E402

log = get_logger(__name__)


@dataclass
class SessionHandle:
    session_id: str
    trace_id: str
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    last_activity_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    current_question: dict[str, Any] | None = None
    final_state: InterviewState | None = None
    error: str | None = None
    error_kind: str | None = None
    cancelled: bool = False
    question_event: threading.Event = field(default_factory=threading.Event)
    done_event: threading.Event = field(default_factory=threading.Event)
    asked_turn: int = -1
    turn_idx: int = 0
    max_turns: int | None = None

    # Per-session LLM override (BYOK). When set, call_chat uses these
    # credentials instead of the server-wide Settings values.
    llm_config: dict[str, Any] | None = None
    llm_config_meta: dict[str, Any] | None = None
    session_token_hash: str | None = None

    # Session-level metadata cached on the handle so every
    # ``workflow.stream`` segment reuses the same LangSmith
    # ``metadata`` / ``tags`` / ``run_name`` without re-deriving them
    # from the graph state. The values are deliberately plain strings
    # (not a nested JobSpec) so ``rehydrate`` from ``InterviewSession``
    # can populate them without importing the state schema. Keep these
    # in sync with ``InterviewSession`` column names in
    # ``app/models/interview_session.py``.
    candidate_name: str | None = None
    job_title: str | None = None
    job_level: str | None = None
    mode: str | None = None

    # Compact projection of ``state.qa_history[-1].evaluation`` cached at
    # interrupt time so ``GET /question`` can ship the previous turn's
    # evaluation summary alongside the freshly arrived question. The
    # frontend uses it to render the in-interview "本轮表现" feedback card.
    # ``None`` on the very first turn or when ``recover_waiting_session``
    # cannot re-derive it from the checkpoint.
    last_turn_evaluation: dict[str, Any] | None = None

    # End-to-end wall-clock duration of the most recent ``_run_segment``
    # in milliseconds (#11). Captured via ``time.monotonic`` deltas in
    # ``_run_segment.finally`` so all paths (interrupt / END / cancelled
    # / errored) book a value. Surfaced through ``GET /question`` so the
    # frontend can render an ETA hint on the next loading state. Stays
    # ``None`` until at least one segment has finished; never restored
    # from checkpoint (a recovered session genuinely has no prior
    # latency on the in-memory handle).
    last_segment_latency_ms: int | None = None

    # Per-session LLM cost accounting (P1 #3 — LLM cost observability).
    # ``call_chat`` accumulates one increment per call into the active
    # handle via ``record_session_llm_call``. Counters are deliberately
    # additive across resumes so a recovered session keeps booking onto
    # the same totals; the values are not restored from checkpoint
    # (a rehydrated session starts from 0 because the original handle
    # already wrote the historic totals into the closing trace row).
    # ``cost_usage_estimated`` flips to True the first time any provider
    # call returns no ``usage`` block so the report UI can flag the
    # numbers as "approximate".
    llm_call_count: int = 0
    llm_stub_call_count: int = 0
    llm_error_call_count: int = 0
    prompt_tokens_total: int = 0
    completion_tokens_total: int = 0
    cost_usage_estimated: bool = False

    # Legacy sync-provider fields (only used when use_sync_provider=True)
    provider: QueueAnswerProvider | None = None
    thread: threading.Thread | None = None

    # Lock guards the _running flag to prevent overlapping stream segments
    _segment_lock: threading.Lock = field(default_factory=threading.Lock)
    _running: bool = False
    _cancel_event: threading.Event = field(default_factory=threading.Event)

    @property
    def use_sync_provider(self) -> bool:
        return self.provider is not None

    def touch(self) -> None:
        """Update ``last_activity_at`` to mark the handle as alive.

        Called from every public operation (poll / submit / resume)
        so the TTL reaper only evicts sessions that no client has
        touched for ``settings.session_idle_ttl_minutes``.
        """
        self.last_activity_at = datetime.now(UTC)


def _graph_config(
    session_id_or_handle: str | SessionHandle,
    *,
    turn_idx: int | None = None,
) -> dict[str, Any]:
    """Build the ``workflow.stream`` / ``workflow.get_state`` config.

    Accepts either a bare ``session_id`` (used by probes like
    ``_checkpoint_exists`` that have no handle context) or a full
    :class:`SessionHandle` so the LangSmith slice can be merged in
    without duplicating the handle → metadata mapping across callers.

    ``turn_idx`` overrides the handle's cached turn so that the
    LangSmith ``run_name`` line in the console log carries the
    *about-to-be-asked* turn number even before the graph has
    advanced. When omitted, the handle's current ``turn_idx`` wins.
    """
    from app.core.langsmith_utils import build_langsmith_config

    if isinstance(session_id_or_handle, SessionHandle):
        handle = session_id_or_handle
        session_id = handle.session_id
    else:
        handle = None
        session_id = session_id_or_handle

    cfg: dict[str, Any] = {
        "configurable": {"thread_id": session_id},
        "recursion_limit": 120,
    }

    if handle is None:
        return cfg

    settings = get_settings()
    effective_turn = turn_idx if turn_idx is not None else handle.turn_idx
    extra_metadata = _cost_summary_metadata(handle)
    ls_slice = build_langsmith_config(
        tracing_enabled=bool(settings.langsmith_tracing),
        session_id=session_id,
        trace_id=handle.trace_id,
        app_env=settings.app_env,
        candidate_name=handle.candidate_name,
        job_level=handle.job_level,
        job_title=handle.job_title,
        mode=handle.mode,
        turn_idx=effective_turn,
        extra_metadata=extra_metadata or None,
    )
    if ls_slice:
        cfg.update(ls_slice)
    return cfg


def _cost_summary_metadata(handle: SessionHandle) -> dict[str, Any]:
    """Project the handle's running LLM tallies into LangSmith metadata.

    Returns an empty dict before the first LLM call so a fresh session
    does not carry a noise row of zeros into the trace tree. Called
    from :func:`_graph_config` for every ``workflow.stream`` invocation,
    so each segment span carries the up-to-now totals.
    """
    if handle.llm_call_count <= 0:
        return {}
    from app.core.metrics import estimate_llm_cost_usd

    settings = get_settings()
    est_usd = estimate_llm_cost_usd(
        model=settings.llm_model,
        prompt_tokens=handle.prompt_tokens_total,
        completion_tokens=handle.completion_tokens_total,
    )
    return {
        "llm_calls_total": handle.llm_call_count,
        "llm_prompt_tokens_total": handle.prompt_tokens_total,
        "llm_completion_tokens_total": handle.completion_tokens_total,
        "llm_cost_usd_estimate": est_usd,
        "llm_cost_usage_estimated": handle.cost_usage_estimated,
    }


class SessionManager:
    def __init__(self) -> None:
        self._sessions: dict[str, SessionHandle] = {}
        self._lock = threading.Lock()
        self._registry = SessionRegistry(self._sessions, self._lock)
        self._workflow = build_workflow()
        self._reaper_thread: threading.Thread | None = None
        self._reaper_stop = threading.Event()
        self._maybe_start_reaper()

    def _session_registry(self) -> SessionRegistry:
        registry = getattr(self, "_registry", None)
        if registry is None:
            registry = SessionRegistry(self._sessions, self._lock)
            self._registry = registry
        return registry

    # ------------------------------------------------------------------
    # TTL reaper
    # ------------------------------------------------------------------

    def _maybe_start_reaper(self) -> None:
        """Start the idle-session reaper iff it's configured on.

        TTL=0 disables reaping entirely which is useful for deterministic
        tests that keep session handles around for minutes at a time.
        """
        settings = get_settings()
        if settings.session_idle_ttl_minutes <= 0:
            log.info("session TTL reaper disabled (ttl=%d)", settings.session_idle_ttl_minutes)
            return
        if self._reaper_thread and self._reaper_thread.is_alive():
            return
        self._reaper_stop.clear()
        self._reaper_thread = threading.Thread(
            target=self._reap_forever,
            name="session-reaper",
            daemon=True,
        )
        self._reaper_thread.start()

    def _reap_forever(self) -> None:
        settings = get_settings()
        interval = max(5, int(settings.session_reaper_interval_seconds))
        while not self._reaper_stop.wait(interval):
            try:
                self._reap_once()
            except Exception as e:  # pragma: no cover - defensive
                log.warning("session reaper pass failed: %s", e)

    def _reap_once(self) -> int:
        """Cancel + evict any handle idle beyond the configured TTL."""
        settings = get_settings()
        ttl = timedelta(minutes=settings.session_idle_ttl_minutes)
        now = datetime.now(UTC)
        victims = self._session_registry().expired_session_ids(now=now, ttl=ttl)
        if not victims:
            return 0
        for sid in victims:
            log.warning("session reaper: cancelling idle session %s", sid)
            try:
                self.cancel(sid)
            except Exception as e:
                log.warning("session reaper: cancel %s failed: %s", sid, e)
            self.remove(sid)
        return len(victims)

    def shutdown(self) -> None:
        """Signal the reaper to stop.  Used by tests and process shutdown."""
        self._reaper_stop.set()

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    def _persist_interrupt(
        self,
        handle: SessionHandle,
        question: dict[str, Any],
        turn_idx: int,
    ) -> None:
        """Write the current interrupt state to the DB row."""
        try:
            from app.models.interview_session import InterviewSession

            with get_db_session() as db:
                row = db.get(InterviewSession, handle.session_id)
                if row is None:
                    row = InterviewSession(
                        session_id=handle.session_id,
                        trace_id=handle.trace_id,
                    )
                    db.add(row)
                row.status = "interrupted"
                if handle.session_token_hash and not row.session_token_hash:
                    row.session_token_hash = handle.session_token_hash
                if handle.llm_config_meta:
                    row.llm_config_meta = handle.llm_config_meta
                row.current_question = question
                row.turn_idx = turn_idx
                row.asked_turn = handle.asked_turn
        except Exception as e:
            log.warning("persist_interrupt failed for %s: %s", handle.session_id, e)

    def _persist_completed(
        self,
        handle: SessionHandle,
        final_state: dict[str, Any] | None,
    ) -> None:
        try:
            from app.models.interview_session import InterviewSession

            with get_db_session() as db:
                row = db.get(InterviewSession, handle.session_id)
                if row is None:
                    row = InterviewSession(
                        session_id=handle.session_id,
                        trace_id=handle.trace_id,
                    )
                    db.add(row)
                status = (final_state or {}).get("status", "completed")
                if handle.session_token_hash and not row.session_token_hash:
                    row.session_token_hash = handle.session_token_hash
                if handle.llm_config_meta:
                    row.llm_config_meta = handle.llm_config_meta
                row.status = status if status != "running" else "completed"
                row.final_report = (final_state or {}).get("final_report")
                if status in {"error", "errored", "failed", "stale"}:
                    row.error = (final_state or {}).get("error") or handle.error
                    row.error_kind = (
                        (final_state or {}).get("error_kind") or handle.error_kind
                    )
                    row.retryable = bool((final_state or {}).get("retryable", False))
                else:
                    row.error = None
                    row.error_kind = None
                    row.retryable = False
                row.current_question = None
        except Exception as e:
            log.warning("persist_completed failed for %s: %s", handle.session_id, e)

    # ------------------------------------------------------------------
    # Graph-segment runner (interrupt-aware)
    # ------------------------------------------------------------------

    def _run_segment(
        self,
        handle: SessionHandle,
        stream_input: Any,
    ) -> None:
        """Drive ``workflow.stream`` until the next interrupt or END.

        Called on a short-lived background thread for both the initial
        ``start`` and every ``submit_answer``.
        """
        _llm_override_var.set(handle.llm_config)
        session_token = _current_session_handle_var.set(handle)
        timing_token = start_timing_trace()
        # Wall-clock start for the end-to-end latency trace (#11). We use
        # ``time.monotonic`` rather than ``time.time`` so a system clock
        # adjustment mid-segment cannot produce a negative duration.
        segment_started_at = time.monotonic()
        log_token = bind_log_context(
            session_id=handle.session_id,
            trace_id=handle.trace_id,
        )
        config = _graph_config(handle)
        last_state: dict[str, Any] = {}
        try:
            for partial in self._workflow.stream(
                stream_input, config=config, stream_mode="values"
            ):
                last_state.update(partial)
                if last_state.get("max_turns") is not None:
                    handle.max_turns = int(last_state.get("max_turns") or 0) or None
                if handle._cancel_event.is_set():
                    log.info(
                        "session %s: cancel detected mid-stream, aborting",
                        handle.session_id,
                    )
                    handle.final_state = {**last_state, "status": "cancelled"}
                    handle.done_event.set()
                    self._persist_completed(handle, handle.final_state)
                    return

            graph_state = self._workflow.get_state(config)

            if graph_state.next:
                # Graph is paused at an interrupt — extract question
                interrupt_data = None
                for task in getattr(graph_state, "tasks", []):
                    for intr in getattr(task, "interrupts", []):
                        interrupt_data = intr.value
                        break
                    if interrupt_data:
                        break

                if interrupt_data and isinstance(interrupt_data, dict):
                    question = interrupt_data.get("question", {})
                    turn_idx = interrupt_data.get("turn_idx", 0)
                else:
                    question = last_state.get("current_question", {})
                    turn_idx = last_state.get("turn_idx", 0)

                handle.current_question = question
                handle.turn_idx = turn_idx
                if last_state.get("max_turns") is not None:
                    handle.max_turns = int(last_state.get("max_turns") or 0) or None
                handle.last_turn_evaluation = _extract_last_turn_evaluation(
                    last_state.get("qa_history")
                )
                handle.question_event.set()
                self._persist_interrupt(handle, question, turn_idx)
                log.info(
                    "session %s interrupted at turn %d",
                    handle.session_id,
                    turn_idx,
                )
            else:
                # Graph reached END
                handle.final_state = last_state
                handle.done_event.set()
                self._persist_completed(handle, last_state)
                log.info("session %s completed", handle.session_id)

        except Exception as e:
            from app.engine.agents.llm_client import (
                classify_llm_error_kind,
                redact_llm_secrets,
            )

            safe_error = redact_llm_secrets(str(e), handle.llm_config)
            log.exception("session %s segment failed: %s", handle.session_id, safe_error)
            handle.error = safe_error
            handle.error_kind = classify_llm_error_kind(e)
            handle.done_event.set()
            self._persist_completed(
                handle,
                {
                    "status": "errored",
                    "error": safe_error,
                    "error_kind": handle.error_kind,
                },
            )
        finally:
            try:
                from app.engine.workflow.nodes.wait_answer import (
                    clear_raw_answer_for_state,
                )

                clear_raw_answer_for_state(last_state)
            except Exception as e:  # pragma: no cover - best-effort privacy cleanup
                log.debug("raw answer side-channel cleanup failed: %s", e)
            # Book the segment latency on the handle for #11. Runs on
            # every exit path (interrupt / END / cancel / error) so the
            # client always sees a fresh value on the next poll.
            handle.last_segment_latency_ms = int(
                (time.monotonic() - segment_started_at) * 1000
            )
            reset_timing_trace(timing_token)
            reset_log_context(log_token)
            _current_session_handle_var.reset(session_token)
            with handle._segment_lock:
                handle._running = False

    def _start_segment(
        self,
        handle: SessionHandle,
        stream_input: Any,
    ) -> bool:
        with handle._segment_lock:
            if handle._running:
                log.warning(
                    "session %s: segment already running, skipping",
                    handle.session_id,
                )
                return False
            handle._running = True

        t = threading.Thread(
            target=self._run_segment,
            args=(handle, stream_input),
            name=f"segment-{handle.session_id}",
            daemon=True,
        )
        try:
            t.start()
        except Exception:
            with handle._segment_lock:
                handle._running = False
            log.exception("session %s: segment thread failed to start", handle.session_id)
            return False
        return True

    def _wait_until_idle(
        self,
        handle: SessionHandle,
        *,
        timeout: float | None = None,
        interval: float = 0.01,
    ) -> bool:
        """Wait for a just-interrupted segment to clear its running flag.

        ``workflow.stream`` can yield the interrupt, set
        ``question_event``, and return control to an API poller a few
        milliseconds before ``_run_segment.finally`` flips
        ``handle._running`` back to False. If the client submits an
        answer immediately, the resume segment would otherwise be
        skipped as "already running".

        The default timeout used to be 2s which was too aggressive for
        cold LLM calls; it now comes from
        ``settings.session_resume_idle_timeout_seconds``.
        """
        if timeout is None:
            timeout = float(get_settings().session_resume_idle_timeout_seconds)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with handle._segment_lock:
                if not handle._running:
                    return True
            time.sleep(interval)
        return False

    # ------------------------------------------------------------------
    # Legacy sync-provider runner
    # ------------------------------------------------------------------

    def _observe_state_legacy(
        self, handle: SessionHandle, state: InterviewState
    ) -> None:
        question = state.get("current_question") or None
        if not question:
            return
        state_turn = state.get("turn_idx", 0)
        if state_turn <= handle.asked_turn:
            return
        handle.current_question = question
        handle.turn_idx = state_turn
        if state.get("max_turns") is not None:
            handle.max_turns = int(state.get("max_turns") or 0) or None
        handle.question_event.set()

    def _run_workflow_legacy(
        self, handle: SessionHandle, initial: InterviewState
    ) -> None:
        _llm_override_var.set(handle.llm_config)
        session_token = _current_session_handle_var.set(handle)
        timing_token = start_timing_trace()
        log_token = bind_log_context(
            session_id=handle.session_id,
            trace_id=handle.trace_id,
        )
        config = _graph_config(handle)
        try:
            last_state: dict[str, Any] = dict(initial)
            for partial in self._workflow.stream(
                initial, config=config, stream_mode="values"
            ):
                last_state.update(partial)
                self._observe_state_legacy(handle, last_state)
            handle.final_state = last_state
        except Exception as e:
            from app.engine.agents.llm_client import (
                classify_llm_error_kind,
                redact_llm_secrets,
            )

            safe_error = redact_llm_secrets(str(e), handle.llm_config)
            log.exception("session %s failed: %s", handle.session_id, safe_error)
            handle.error = safe_error
            handle.error_kind = classify_llm_error_kind(e)
        finally:
            reset_timing_trace(timing_token)
            reset_log_context(log_token)
            _current_session_handle_var.reset(session_token)
            if handle.provider:
                unregister_provider(handle.session_id)
            handle.done_event.set()

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def start(
        self,
        session_id: str,
        trace_id: str,
        initial: InterviewState,
        *,
        llm_config: dict[str, Any] | None = None,
        session_token_hash: str | None = None,
    ) -> SessionHandle:
        runtime_cfg = initial.get("runtime_config") or {}
        use_sync = bool(runtime_cfg.get("use_sync_provider"))
        # Pre-compute session-level metadata once so both code paths
        # (sync / durable) and every later stream segment reuse the
        # exact same LangSmith tags. Pulling from ``initial`` here -
        # instead of sniffing state on each stream call - also makes
        # ``SessionHandle`` self-describing for the ``/admin/sessions``
        # endpoint.
        candidate = initial.get("candidate") or {}
        job_spec = initial.get("job_spec") or {}
        session_meta: dict[str, Any] = {
            "candidate_name": candidate.get("name"),
            "job_title": job_spec.get("title"),
            "job_level": job_spec.get("level"),
            "mode": initial.get("mode"),
            "max_turns": int(initial.get("max_turns") or 0) or None,
        }
        llm_config_meta = _safe_llm_config_meta(llm_config)

        if use_sync:
            # Legacy path for CLI / demo / tests
            provider = QueueAnswerProvider()
            handle = SessionHandle(
                session_id=session_id,
                trace_id=trace_id,
                provider=provider,
                llm_config=llm_config,
                llm_config_meta=llm_config_meta,
                session_token_hash=session_token_hash,
                **session_meta,
            )
            self._session_registry().add(session_id, handle)
            register_provider(session_id, provider)
            t = threading.Thread(
                target=self._run_workflow_legacy,
                args=(handle, initial),
                name=f"workflow-{session_id}",
                daemon=True,
            )
            handle.thread = t
            t.start()
        else:
            # Durable interrupt path
            handle = SessionHandle(
                session_id=session_id,
                trace_id=trace_id,
                llm_config=llm_config,
                llm_config_meta=llm_config_meta,
                session_token_hash=session_token_hash,
                **session_meta,
            )
            self._session_registry().add(session_id, handle)
            self._start_segment(handle, initial)

        return handle

    def session_exists(self, session_id: str) -> bool:
        if self._session_registry().contains(session_id):
            return True
        try:
            from app.models.interview_session import InterviewSession

            with get_db_session() as db:
                return db.get(InterviewSession, session_id) is not None
        except Exception as e:
            log.warning("session existence check failed for %s: %s", session_id, e)
            return False

    def get(self, session_id: str) -> SessionHandle | None:
        return self._session_registry().get(session_id)

    def submit_answer(
        self,
        session_id: str,
        answer: str,
        *,
        turn_idx: int,
        video_signals: dict[str, Any] | None = None,
        llm_config: dict[str, Any] | None = None,
    ) -> None:
        handle = self.get(session_id)
        if handle is None:
            raise KeyError(session_id)

        handle.touch()
        if turn_idx != handle.turn_idx:
            raise ValueError(
                f"answer turn_idx={turn_idx} does not match current turn_idx={handle.turn_idx}"
            )
        if not handle.question_event.is_set():
            raise ValueError("session is not waiting for an answer")
        if llm_config is not None:
            handle.llm_config = llm_config
            handle.llm_config_meta = _safe_llm_config_meta(llm_config)
        elif (
            not handle.llm_config
            and isinstance(handle.llm_config_meta, dict)
            and handle.llm_config_meta.get("requires_reauth")
        ):
            raise ValueError("llm_config reauth_required")
        if handle.use_sync_provider:
            # Legacy path
            handle.provider.submit(handle.turn_idx, answer)  # type: ignore[union-attr]
            handle.asked_turn = handle.turn_idx
            handle.question_event.clear()
            return

        # Durable path: resume the graph with Command(resume=answer)
        from langgraph.types import Command

        if not self._wait_until_idle(handle):
            log.warning(
                "session %s: prior segment still running before resume",
                session_id,
            )
            raise ValueError("prior segment still running before resume")
        resume_payload: str | dict[str, Any] = answer
        if video_signals:
            resume_payload = {"answer": answer, "video_signals": video_signals}
        previous_asked_turn = handle.asked_turn
        handle.asked_turn = handle.turn_idx
        handle.question_event.clear()
        if self._start_segment(handle, Command(resume=resume_payload)) is False:
            handle.asked_turn = previous_asked_turn
            handle.question_event.set()
            raise ValueError("resume segment did not start")

    def skip_question(
        self,
        session_id: str,
        *,
        turn_idx: int,
        reason: str | None = None,
    ) -> None:
        handle = self.get(session_id)
        if handle is None:
            raise KeyError(session_id)

        handle.touch()
        if turn_idx != handle.turn_idx:
            raise ValueError(
                f"skip turn_idx={turn_idx} does not match current turn_idx={handle.turn_idx}"
            )
        if not handle.question_event.is_set():
            raise ValueError("session is not waiting for an answer")
        if handle.use_sync_provider:
            handle.provider.submit(handle.turn_idx, "__skip_question__")  # type: ignore[union-attr]
            handle.asked_turn = handle.turn_idx
            handle.question_event.clear()
            return

        from langgraph.types import Command

        if not self._wait_until_idle(handle):
            log.warning(
                "session %s: prior segment still running before skip",
                session_id,
            )
            raise ValueError("prior segment still running before skip")
        previous_asked_turn = handle.asked_turn
        handle.asked_turn = handle.turn_idx
        handle.question_event.clear()
        payload = {"__skipped__": True}
        if reason:
            payload["reason"] = reason
        if self._start_segment(handle, Command(resume=payload)) is False:
            handle.asked_turn = previous_asked_turn
            handle.question_event.set()
            raise ValueError("skip segment did not start")

    def request_hint(
        self,
        session_id: str,
        *,
        turn_idx: int,
        llm_config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        handle = self.get(session_id)
        if handle is None:
            raise KeyError(session_id)

        handle.touch()
        if turn_idx != handle.turn_idx:
            raise ValueError(
                f"hint turn_idx={turn_idx} does not match current turn_idx={handle.turn_idx}"
            )
        if not handle.question_event.is_set() or not isinstance(handle.current_question, dict):
            raise ValueError("session is not waiting for an answer")
        if llm_config is not None:
            handle.llm_config = llm_config
            handle.llm_config_meta = _safe_llm_config_meta(llm_config)
        elif (
            not handle.llm_config
            and isinstance(handle.llm_config_meta, dict)
            and handle.llm_config_meta.get("requires_reauth")
        ):
            raise ValueError("llm_config reauth_required")

        hint = build_interview_hint(handle.current_question)
        return {
            "session_id": session_id,
            "turn_idx": turn_idx,
            "hint": hint["hint"],
            "source": hint["source"],
        }

    def wait_for_next_question(
        self,
        session_id: str,
        timeout: float = 60.0,
    ) -> dict[str, Any] | None:
        handle = self.get(session_id)
        if handle is None:
            return None

        deadline = time.monotonic() + timeout
        while True:
            if handle.question_event.is_set():
                handle.touch()
                return handle.current_question
            if handle.done_event.is_set():
                handle.touch()
                return None
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            handle.question_event.wait(timeout=min(0.05, remaining))
        return None

    def cancel(self, session_id: str, *, join_timeout: float = 5.0) -> bool:
        handle = self.get(session_id)
        if handle is None:
            return False

        # Make cancel truly idempotent for already-finished sessions.
        # The WebSocket voice handler calls ``manager.cancel`` from its
        # ``finally`` block on every teardown, including the normal
        # end-of-interview path right after the final_report frame has
        # been sent. Without this guard, the flag ``handle.cancelled``
        # would be flipped to True on a graph that already reached
        # ``END``, and a subsequent HTTP ``GET /resume`` would falsely
        # report ``status: cancelled`` to the text InterviewRoom. The
        # done/errored state is terminal; nothing to cancel.
        if handle.done_event.is_set():
            return True

        handle.cancelled = True
        cancel_resume_started = True

        if handle.use_sync_provider and handle.provider:
            try:
                handle.provider.cancel()
            except Exception as e:
                log.warning("provider.cancel failed for %s: %s", session_id, e)
        else:
            # Signal any in-flight segment to abort at the next yield
            handle._cancel_event.set()
            with handle._segment_lock:
                resume_needed = not handle._running

            # If no segment is running (graph is interrupted / idle),
            # resume with a cancel marker so the graph reaches final_report.
            cancel_resume_started = True
            if resume_needed:
                from langgraph.types import Command

                try:
                    handle.question_event.clear()
                    start_result = self._start_segment(
                        handle,
                        Command(resume={"__cancelled__": True}),
                    )
                    cancel_resume_started = start_result is not False
                except Exception as e:
                    cancel_resume_started = False
                    log.warning("cancel resume failed for %s: %s", session_id, e)

        handle.question_event.set()

        if handle.thread and handle.thread.is_alive():
            handle.thread.join(timeout=join_timeout)
            if handle.thread.is_alive():
                log.warning(
                    "session %s still running after cancel join=%.1fs; detaching",
                    session_id,
                    join_timeout,
                )
        return cancel_resume_started

    def remove(self, session_id: str) -> None:
        self._session_registry().remove(session_id)

    def snapshot(self) -> list[dict[str, Any]]:
        """Return a read-only serialisable view of active sessions."""
        pairs = self._session_registry().snapshot_pairs()
        return [
            {
                "session_id": sid,
                "trace_id": handle.trace_id,
                "turn_idx": handle.turn_idx,
                "asked_turn": handle.asked_turn,
                "has_question": handle.current_question is not None,
                "done": handle.done_event.is_set(),
                "cancelled": handle.cancelled,
                "created_at": handle.created_at.isoformat(),
                "error": handle.error,
                "error_kind": handle.error_kind,
            }
            for sid, handle in pairs
        ]

    # ------------------------------------------------------------------
    # Rehydration
    # ------------------------------------------------------------------

    def _checkpoint_exists(self, session_id: str) -> bool:
        """Check whether the LangGraph checkpointer has state for *session_id*.

        With MemorySaver all checkpoints vanish on restart, so rehydrated
        handles would fail on the first ``submit_answer``.  We probe
        ``get_state`` and treat any missing / empty result as "no
        checkpoint".
        """
        config = _graph_config(session_id)
        try:
            state = self._workflow.get_state(config)
            values = getattr(state, "values", None) if state is not None else None
            return bool(values)
        except Exception as e:
            log.debug("checkpoint probe for %s: %s", session_id, e)
            return False

    def _checkpoint_retryable_question_failure(self, session_id: str) -> bool:
        """Return whether a checkpoint can safely retry question generation.

        This is intentionally narrow: we only retry a graph that is parked
        at ``ask_question`` and has not produced a ``current_question`` yet.
        Once a question has been shown, the next user action must be a normal
        answer resume rather than another generator run.
        """
        config = _graph_config(session_id)
        try:
            state = self._workflow.get_state(config)
        except Exception as e:
            log.warning("checkpoint retry probe failed for %s: %s", session_id, e)
            return False

        values = getattr(state, "values", None) or {}
        next_nodes = tuple(getattr(state, "next", ()) or ())
        if "ask_question" not in next_nodes:
            return False
        if values.get("final_report"):
            return False
        return not bool(values.get("current_question"))

    def _checkpoint_retryable_evaluator_failure(self, session_id: str) -> bool:
        """Return whether a checkpoint can safely retry answer evaluation.

        This covers the failure mode where the user already submitted an answer
        and the graph crashed before ``evaluator`` completed. Retrying resumes
        the parked graph from ``evaluator`` with the checkpointed
        ``current_answer`` and ``current_question`` instead of asking the user
        to answer the same question again.
        """
        config = _graph_config(session_id)
        try:
            state = self._workflow.get_state(config)
        except Exception as e:
            log.warning("checkpoint evaluator retry probe failed for %s: %s", session_id, e)
            return False

        values = getattr(state, "values", None) or {}
        next_nodes = tuple(getattr(state, "next", ()) or ())
        if "evaluator" not in next_nodes:
            return False
        if values.get("final_report"):
            return False
        if not isinstance(values.get("current_question"), dict):
            return False
        return bool(str(values.get("current_answer") or "").strip())

    def can_retry_failed_question(self, session_id: str) -> bool:
        """Public probe used by APIs to show a retry affordance."""
        return (
            self._checkpoint_retryable_question_failure(session_id)
            or self._checkpoint_retryable_evaluator_failure(session_id)
        )

    def _checkpoint_waiting_question(self, session_id: str) -> dict[str, Any] | None:
        """Return checkpoint values if the graph is paused for an answer."""
        config = _graph_config(session_id)
        try:
            state = self._workflow.get_state(config)
        except Exception as e:
            log.warning("checkpoint waiting probe failed for %s: %s", session_id, e)
            return None

        values = getattr(state, "values", None) or {}
        next_nodes = tuple(getattr(state, "next", ()) or ())
        question = values.get("current_question")
        if "wait_answer" not in next_nodes:
            return None
        if not isinstance(question, dict) or not question:
            return None
        if values.get("final_report"):
            return None
        return values

    def recover_waiting_session(self, session_id: str) -> SessionHandle | None:
        """Rebuild an in-memory handle from a waiting-for-answer checkpoint.

        This is a targeted recovery path for browser-local history entries
        whose DB row is stale or was incorrectly marked terminal by an older
        process. The checkpoint is the source of truth: if it still contains a
        pending question at ``wait_answer``, the interview can continue.
        """
        existing = self._session_registry().get(session_id)
        if existing is not None:
            return existing

        values = self._checkpoint_waiting_question(session_id)
        if values is None:
            return None

        data = self._load_persisted_session_for_retry(session_id) or {}
        candidate = values.get("candidate") or {}
        job_spec = values.get("job_spec") or {}
        question = values["current_question"]
        turn_idx = int(values.get("turn_idx") or data.get("turn_idx") or 0)
        asked_turn_raw = data.get("asked_turn")
        asked_turn = (
            int(asked_turn_raw)
            if asked_turn_raw is not None
            else max(turn_idx - 1, -1)
        )
        handle = SessionHandle(
            session_id=session_id,
            trace_id=str(data.get("trace_id") or values.get("trace_id") or session_id),
            session_token_hash=data.get("session_token_hash"),
            llm_config_meta=data.get("llm_config_meta"),
            current_question=question,
            turn_idx=turn_idx,
            asked_turn=asked_turn,
            max_turns=int(values.get("max_turns") or 0) or None,
            candidate_name=data.get("candidate_name") or candidate.get("name"),
            job_title=data.get("job_title") or job_spec.get("title"),
            job_level=data.get("job_level") or job_spec.get("level"),
            mode=data.get("mode") or values.get("mode"),
            last_turn_evaluation=_extract_last_turn_evaluation(
                values.get("qa_history")
            ),
        )
        handle.question_event.set()
        self._session_registry().add(session_id, handle, replace=True)
        self._persist_interrupt(handle, question, turn_idx)
        log.info("recovered waiting session %s at turn %d", session_id, turn_idx)
        return handle

    def _load_persisted_session_for_retry(
        self,
        session_id: str,
    ) -> dict[str, Any] | None:
        """Load minimal session metadata needed to rebuild a handle."""
        try:
            from app.models.interview_session import InterviewSession

            with get_db_session() as db:
                row = db.get(InterviewSession, session_id)
                if row is None:
                    return None
                return {
                    "trace_id": row.trace_id,
                    "candidate_name": row.candidate_name,
                    "job_title": row.job_title,
                    "job_level": row.job_level,
                    "mode": row.mode,
                    "session_token_hash": row.session_token_hash,
                    "llm_config_meta": row.llm_config_meta,
                    "turn_idx": row.turn_idx,
                    "asked_turn": row.asked_turn,
                }
        except Exception as e:
            log.warning("load retry session %s failed: %s", session_id, e)
            return None

    def _mark_retry_running(self, session_id: str) -> None:
        try:
            from app.models.interview_session import InterviewSession

            with get_db_session() as db:
                row = db.get(InterviewSession, session_id)
                if row is not None:
                    row.status = "running"
                    row.current_question = None
                    row.final_report = None
                    row.error = None
                    row.error_kind = None
                    row.retryable = False
        except Exception as e:
            log.warning("mark retry running failed for %s: %s", session_id, e)

    def retry_failed_question(self, session_id: str) -> SessionHandle | None:
        """Retry a failed graph segment from the latest checkpoint.

        The frontend uses this when the generator times out before a question
        exists, or when the evaluator fails after an answer was submitted. It
        does not retry cancellation or completed sessions.
        """
        if not self.can_retry_failed_question(session_id):
            return None

        handle = self._session_registry().get(session_id)

        created_handle = False
        if handle is None:
            data = self._load_persisted_session_for_retry(session_id)
            if data is None:
                return None
            handle = SessionHandle(
                session_id=session_id,
                trace_id=data.get("trace_id") or session_id,
                session_token_hash=data.get("session_token_hash"),
                llm_config_meta=data.get("llm_config_meta"),
                candidate_name=data.get("candidate_name"),
                job_title=data.get("job_title"),
                job_level=data.get("job_level"),
                mode=data.get("mode"),
                turn_idx=int(data.get("turn_idx") or 0),
                asked_turn=int(
                    data.get("asked_turn")
                    if data.get("asked_turn") is not None
                    else -1
                ),
            )
            self._session_registry().add(session_id, handle, replace=True)
            created_handle = True
        else:
            if not self._wait_until_idle(handle):
                log.warning(
                    "session %s: prior segment still running before question retry",
                    session_id,
                )
                return None

        previous_error = handle.error
        previous_error_kind = handle.error_kind
        previous_cancelled = handle.cancelled
        previous_current_question = handle.current_question
        previous_final_state = handle.final_state
        previous_question_event_set = handle.question_event.is_set()
        previous_done_event_set = handle.done_event.is_set()
        previous_cancel_event_set = handle._cancel_event.is_set()
        handle.touch()
        handle.error = None
        handle.error_kind = None
        handle.cancelled = False
        handle.current_question = None
        handle.final_state = None
        handle.question_event.clear()
        handle.done_event.clear()
        handle._cancel_event.clear()
        if self._start_segment(handle, None) is False:
            handle.error = previous_error
            handle.error_kind = previous_error_kind
            handle.cancelled = previous_cancelled
            handle.current_question = previous_current_question
            handle.final_state = previous_final_state
            if previous_question_event_set:
                handle.question_event.set()
            else:
                handle.question_event.clear()
            if previous_done_event_set:
                handle.done_event.set()
            else:
                handle.done_event.clear()
            if previous_cancel_event_set:
                handle._cancel_event.set()
            else:
                handle._cancel_event.clear()
            if created_handle:
                self._session_registry().remove(session_id)
            return None
        self._mark_retry_running(session_id)
        return handle

    def rehydrate(self) -> int:
        """Restore interrupted sessions from the DB after a process restart.

        Only sessions whose LangGraph checkpoint is still accessible are
        restored.  Under MemorySaver this will always be zero (checkpoints
        live in-process memory and are gone after restart).  Under
        PostgresSaver the checkpoints survive, so ``submit_answer`` can
        resume the graph.

        Sessions whose checkpoint is missing are marked ``stale`` in the
        DB so they don't block future rehydration attempts.

        Returns the number of sessions successfully rehydrated.
        """
        from app.core.settings import get_settings

        backend = get_settings().checkpoint_backend
        if backend == "memory":
            log.info(
                "checkpoint_backend=memory — skipping rehydrate "
                "(checkpoints do not survive restart)"
            )
            return 0

        try:
            from app.models.interview_session import InterviewSession

            with get_db_session() as db:
                rows = (
                    db.query(InterviewSession)
                    .filter(InterviewSession.status == "interrupted")
                    .all()
                )
        except Exception as e:
            log.warning("rehydrate query failed: %s", e)
            return 0

        count = 0
        stale = 0
        for row in rows:
            if self._session_registry().contains(row.session_id):
                continue

            if not self._checkpoint_exists(row.session_id):
                log.warning(
                    "session %s has no checkpoint — marking stale",
                    row.session_id,
                )
                try:
                    from app.models.interview_session import InterviewSession

                    with get_db_session() as db:
                        r = db.get(InterviewSession, row.session_id)
                        if r:
                            r.status = "stale"
                except Exception as e:
                    log.debug("mark stale failed for %s: %s", row.session_id, e)
                stale += 1
                continue

            handle = SessionHandle(
                session_id=row.session_id,
                trace_id=row.trace_id,
                session_token_hash=row.session_token_hash,
                llm_config_meta=row.llm_config_meta,
                current_question=row.current_question,
                turn_idx=row.turn_idx,
                asked_turn=row.asked_turn,
                candidate_name=row.candidate_name,
                job_title=row.job_title,
                job_level=row.job_level,
                mode=row.mode,
            )
            if row.current_question:
                handle.question_event.set()
            self._session_registry().add(row.session_id, handle, replace=True)
            count += 1
            log.info(
                "rehydrated session %s at turn %d",
                row.session_id,
                row.turn_idx,
            )

        if count or stale:
            log.info(
                "rehydrate: %d restored, %d stale (no checkpoint)", count, stale
            )
        return count


_manager: SessionManager | None = None


def get_session_manager() -> SessionManager:
    global _manager
    if _manager is None:
        _manager = SessionManager()
    return _manager
