"""Out-of-band trace writer.

The tracer does *not* touch the LangGraph state. It reads the latest
state snapshot from a node and writes a row to ``generation_traces``.
Keeping it out of the main chain mirrors the ACO pattern: "reward /
trace as side channel, not a blocking dependency of the generator
path".

Usage pattern::

    from app.core.tracer import get_tracer
    tracer = get_tracer()

    tracer.trace_session_started(state)
    tracer.trace_evaluator(state, immediate_reward=reward)
    tracer.trace_final_report(state)

Tracer calls are fire-and-forget: if the database is unavailable we
log and continue. This is important because an interview in progress
must not fail just because the observability stack is temporarily
down.
"""
from __future__ import annotations

import copy
from datetime import UTC, datetime
from typing import Any

from app.core.logging import get_logger
from app.core.metrics import (
    record_trace_write_failure,
    record_trace_write_success,
)
from app.core.metrics import (
    trace_write_failures_total as _metric_trace_write_failures_total,
)
from app.core.timing import consume_llm_timing_events
from app.models import InterviewSession, get_session, init_db
from app.models.generation_trace import GenerationTrace

log = get_logger(__name__)


_INIT_CALLED = False


def _ensure_db() -> None:
    global _INIT_CALLED
    if _INIT_CALLED:
        return
    try:
        init_db()
    except Exception as e:  # pragma: no cover
        log.warning("tracer: init_db failed (%s); traces will be dropped", e)
    _INIT_CALLED = True


def _current_langsmith_run_id() -> str | None:
    """Return the LangSmith run-tree root id for the current call, if any.

    When ``langsmith_tracing=False`` (the default), LangSmith's callback
    pipeline never installs a run tree, so :func:`get_current_run_tree`
    returns ``None`` and we drop the ``langsmith_run_id`` field. This
    keeps the tracer usable without the ``langsmith`` package present
    on older deployments; we defer the import into the function body
    and treat any ``ImportError`` / unexpected exception as "no id".
    """
    try:
        from langsmith.run_helpers import get_current_run_tree

        tree = get_current_run_tree()
    except Exception:  # pragma: no cover - langsmith optional / version drift
        return None
    if tree is None:
        return None
    rid = getattr(tree, "id", None)
    return str(rid) if rid else None


_SNAPSHOT_FIELDS = (
    "session_id", "trace_id", "turn_idx", "formal_turn_idx",
    "current_dimension", "current_answer", "scores_per_dim",
    "dimension_status", "quality_threshold", "turn_budget_remaining",
    "mode", "refine_mode", "target_difficulty", "status",
    "selected_action", "policy_id", "policy_context_keys",
    "qa_history", "video_signals",
    "retrieval_block", "strategy_hits", "skill_hits",
)


def _qa_history_window() -> int:
    """Resolve how many ``qa_history`` entries each trace row should keep.

    Reads the value lazily from settings so tests can override the
    knob without re-importing this module. Negative or non-integer
    values fall back to ``0`` (keep the counter, drop the tail) to
    avoid producing a slice with unbounded width.
    """
    try:
        from app.core.settings import get_settings

        raw = getattr(get_settings(), "tracer_qa_history_window", 5)
    except Exception:  # pragma: no cover - settings should always import
        return 5
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return 5
    return max(0, n)


def _strip_messages(state: dict[str, Any]) -> dict[str, Any]:
    """Build a compact snapshot that is safe to serialise into JSON.

    Only copies fields that downstream analytics actually uses, avoiding
    a full ``deepcopy`` of the entire workflow state (which can be
    several hundred KB in later turns). ``qa_history`` in particular is
    truncated to the last ``settings.tracer_qa_history_window`` entries
    and accompanied by ``qa_history_total`` so downstream readers can
    still reason about how far the interview had progressed when the
    row was written.
    """
    snapshot: dict[str, Any] = {}
    window = _qa_history_window()
    for key in _SNAPSHOT_FIELDS:
        if key not in state:
            continue
        if key == "qa_history":
            history = state.get(key) or []
            try:
                total = len(history)
            except TypeError:
                total = 0
            snapshot["qa_history_total"] = total
            tail = list(history)[-window:] if window > 0 else []
            snapshot[key] = copy.deepcopy(tail)
            continue
        if key == "retrieval_block":
            raw = state.get(key) or ""
            snapshot[key] = raw[:500] if isinstance(raw, str) and len(raw) > 500 else copy.deepcopy(raw)
            continue
        snapshot[key] = copy.deepcopy(state[key])
    return snapshot


def _node_result_fields(
    node: str,
    state: dict[str, Any],
    evaluation: dict[str, Any],
) -> tuple[str | None, dict[str, Any] | None]:
    if node == "ask_question":
        return None, None
    return state.get("current_answer"), evaluation or None


def _node_state_snapshot(node: str, state: dict[str, Any]) -> dict[str, Any]:
    snapshot = _strip_messages(state)
    if node == "ask_question":
        snapshot.pop("current_answer", None)
    return snapshot


def _timing_snapshot(*, node_elapsed_ms: int | None = None) -> dict[str, Any] | None:
    timing: dict[str, Any] = {}
    if node_elapsed_ms is not None:
        timing["node_elapsed_ms"] = max(0, int(node_elapsed_ms))
    llm_calls = consume_llm_timing_events()
    if llm_calls:
        timing["llm_calls"] = llm_calls
        timing["llm_total_ms"] = sum(
            int(call.get("elapsed_ms") or 0) for call in llm_calls
        )
    return timing or None


def _attach_timing(
    payload: dict[str, Any],
    *,
    node_elapsed_ms: int | None = None,
) -> dict[str, Any]:
    timing = _timing_snapshot(node_elapsed_ms=node_elapsed_ms)
    if not timing:
        return payload
    enriched = dict(payload)
    enriched["timing"] = timing
    return enriched


def _list_or_empty(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _record_or_empty(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _evaluator_contract_and_source(
    state: dict[str, Any],
    question: dict[str, Any],
) -> tuple[dict[str, Any], str]:
    """Mirror the evaluator's contract lookup without changing scoring."""
    current_contract = state.get("current_contract")
    if isinstance(current_contract, dict) and current_contract:
        return copy.deepcopy(current_contract), "current_contract"

    question_contract = question.get("contract")
    if isinstance(question_contract, dict) and question_contract:
        return copy.deepcopy(question_contract), "current_question.contract"

    rubric_points = question.get("rubric_points")
    if isinstance(rubric_points, list) and rubric_points:
        return {}, "legacy_rubric_points"

    return {}, "missing"


def _evaluator_trace_payload(
    state: dict[str, Any],
    question: dict[str, Any],
    evaluation: dict[str, Any],
) -> dict[str, Any]:
    contract, contract_source = _evaluator_contract_and_source(state, question)
    rubric_points = _list_or_empty(question.get("rubric_points"))
    must_cover = _list_or_empty(contract.get("must_cover"))
    acceptance_checks = _list_or_empty(contract.get("acceptance_checks"))
    signed_by = _list_or_empty(contract.get("signed_by"))

    return {
        "contract_source": contract_source,
        "contract": copy.deepcopy(contract),
        "contract_must_cover_count": len(must_cover),
        "contract_acceptance_check_count": len(acceptance_checks),
        "contract_bar_level": contract.get("bar_level"),
        "signed_by": copy.deepcopy(signed_by),
        "rubric_points": copy.deepcopy(rubric_points),
        "rubric_coverage": copy.deepcopy(
            _record_or_empty(evaluation.get("rubric_coverage"))
        ),
        "acceptance_check_results": copy.deepcopy(
            _record_or_empty(evaluation.get("acceptance_check_results"))
        ),
        "recommended_next": evaluation.get("recommended_next"),
        "recommended_next_plan": evaluation.get("recommended_next_plan"),
        "recommended_probe_intent": evaluation.get("recommended_probe_intent"),
        "failure_reason": evaluation.get("failure_reason"),
        "failure_categories": copy.deepcopy(
            _list_or_empty(evaluation.get("failure_categories"))
        ),
    }


def trace_write_failures_total(operation: str) -> int:
    """Return the current failure counter for tests/admin diagnostics."""
    return _metric_trace_write_failures_total(operation)


def _record_trace_success(operation: str) -> None:
    record_trace_write_success(operation)


def _record_trace_failure(operation: str) -> None:
    record_trace_write_failure(operation)


class Tracer:
    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled

    def _context_key(self, state: dict[str, Any]) -> str:
        keys = self._policy_context_keys(state)
        if keys:
            return keys[0]
        job_level = state.get("job_spec", {}).get("level", "mid")
        dim = state.get("current_dimension") or "general"
        return f"{job_level}:{dim}"

    def _policy_context_keys(self, state: dict[str, Any]) -> list[str]:
        keys = state.get("policy_context_keys")
        if not isinstance(keys, list):
            keys = (state.get("selected_action") or {}).get("policy_context_keys")
        if not isinstance(keys, list):
            return []
        out: list[str] = []
        seen: set[str] = set()
        for key in keys:
            item = str(key or "").strip()
            if item and item not in seen:
                out.append(item)
                seen.add(item)
        return out

    def _enable_video_analysis(self, state: dict[str, Any]) -> bool:
        runtime = state.get("runtime_config") or {}
        return bool(runtime.get("enable_video_analysis"))

    def trace_session_started(self, state: dict[str, Any]) -> None:
        if not self.enabled:
            return
        _ensure_db()
        try:
            with get_session() as sess:
                existing = sess.get(InterviewSession, state.get("session_id"))
                if existing is not None:
                    setup_snapshot = state.get("setup_snapshot")
                    if (
                        existing.setup_snapshot is None
                        and isinstance(setup_snapshot, dict)
                    ):
                        existing.setup_snapshot = setup_snapshot
                    _record_trace_success("session_started")
                    return
                sess.add(
                    InterviewSession(
                        session_id=state.get("session_id", ""),
                        trace_id=state.get("trace_id", ""),
                        candidate_name=(state.get("candidate") or {}).get("name"),
                        job_title=(state.get("job_spec") or {}).get("title"),
                        job_level=(state.get("job_spec") or {}).get("level"),
                        mode=state.get("mode", "mixed"),
                        enable_video_analysis=self._enable_video_analysis(state),
                        setup_snapshot=state.get("setup_snapshot")
                        if isinstance(state.get("setup_snapshot"), dict)
                        else None,
                        status="running",
                    )
                )
            _record_trace_success("session_started")
        except Exception as e:  # pragma: no cover
            _record_trace_failure("session_started")
            log.warning("trace_session_started failed: %s", e)

    def trace_director_sample(self, state: dict[str, Any]) -> None:
        """Write a trace row at the moment the director picks an arm.

        This captures the counterfactual context: which arms were
        allowed, what the posterior looked like, whether we sampled
        Thompson-style or explored uniformly, and what the director
        picked.  Without this row, downstream policy analytics can
        only see "chosen arm + reward" and are blind to masked or
        runner-up arms.
        """
        if not self.enabled:
            return
        _ensure_db()
        try:
            action = state.get("selected_action") or {}
            diagnostics = action.get("diagnostics") or {}
            snapshot = _strip_messages(state)
            run_id = _current_langsmith_run_id()
            with get_session() as sess:
                sess.add(
                    GenerationTrace(
                        trace_id=state.get("trace_id", ""),
                        session_id=state.get("session_id", ""),
                        # Director runs *before* evaluator increments,
                        # so the current turn_idx already refers to the
                        # turn we are about to ask.
                        turn_idx=state.get("turn_idx", 0),
                        node="director_sample",
                        dimension=state.get("current_dimension"),
                        action_id=action.get("id"),
                        policy_id=state.get("policy_id"),
                        context_key=self._context_key(state),
                        policy_context_keys=self._policy_context_keys(state) or None,
                        score=None,
                        passed=None,
                        immediate_reward=None,
                        state_snapshot={
                            "diagnostics": diagnostics,
                            "selected_action": action,
                            "refine_mode": bool(state.get("refine_mode")),
                            "current_dimension": state.get("current_dimension"),
                            "target_difficulty": state.get("target_difficulty"),
                            "dimension_status": snapshot.get("dimension_status"),
                        },
                        question=None,
                        answer=None,
                        evaluation=None,
                        langsmith_run_id=run_id,
                    )
                )
            _record_trace_success("director_sample")
        except Exception as e:  # pragma: no cover - fire-and-forget
            _record_trace_failure("director_sample")
            log.warning("trace_director_sample failed: %s", e)

    def trace_evaluator(
        self,
        state: dict[str, Any],
        *,
        immediate_reward: float,
        immediate_reward_applied: bool = True,
        node_elapsed_ms: int | None = None,
    ) -> None:
        """Write a trace row after the evaluator node runs.

        We only record one trace per (session, turn) so downstream joins
        with the outcome table stay 1:1 per turn.
        ``immediate_reward_applied`` defaults to True because
        ``evaluator_node`` calls ``bandit.update`` inline.  Callers
        that write traces without fusing into the bandit (e.g. dry
        runs, replays) should pass ``False`` so rehydrate skips them.
        """
        if not self.enabled:
            return
        _ensure_db()
        try:
            question = state.get("current_question") or {}
            evaluation = state.get("evaluation") or {}
            action = (state.get("selected_action") or {})
            run_id = _current_langsmith_run_id()
            snapshot = _strip_messages(state)
            payload = _evaluator_trace_payload(state, question, evaluation)
            timing = _timing_snapshot(node_elapsed_ms=node_elapsed_ms)
            if timing:
                snapshot["timing"] = timing
                payload["timing"] = timing
            snapshot["payload"] = payload
            with get_session() as sess:
                sess.add(
                    GenerationTrace(
                        trace_id=state.get("trace_id", ""),
                        session_id=state.get("session_id", ""),
                        turn_idx=state.get("turn_idx", 0) - 1,
                        # evaluator node increments turn_idx, so the
                        # turn being traced is turn_idx - 1
                        node="evaluator",
                        dimension=state.get("current_dimension"),
                        action_id=action.get("id"),
                        policy_id=state.get("policy_id"),
                        context_key=self._context_key(state),
                        policy_context_keys=self._policy_context_keys(state) or None,
                        score=float(evaluation.get("score", 0.0)),
                        passed=bool(evaluation.get("passed", False)),
                        immediate_reward=immediate_reward,
                        immediate_reward_applied=bool(immediate_reward_applied),
                        state_snapshot=snapshot,
                        question=question.get("question"),
                        answer=state.get("current_answer"),
                        evaluation=evaluation,
                        langsmith_run_id=run_id,
                    )
                )
            _record_trace_success("evaluator")
        except Exception as e:
            _record_trace_failure("evaluator")
            log.warning("trace_evaluator failed: %s", e)

    def trace_node_event(
        self,
        state: dict[str, Any],
        *,
        node: str,
        payload: dict[str, Any] | None = None,
        node_elapsed_ms: int | None = None,
        logical_turn_idx: int | None = None,
    ) -> None:
        """Write a generic trace row for non-RL workflow nodes."""
        if not self.enabled:
            return
        _ensure_db()
        operation = f"node:{node}"
        try:
            run_id = _current_langsmith_run_id()
            action = state.get("selected_action") or {}
            question = state.get("current_question") or {}
            evaluation = state.get("evaluation") or {}
            payload = payload or {}
            answer, row_evaluation = _node_result_fields(node, state, evaluation)
            state_snapshot = _node_state_snapshot(node, state)
            immediate_reward = None
            immediate_reward_applied = False
            if node == "reward_update":
                try:
                    raw_reward = payload.get("immediate_reward")
                    if raw_reward is not None:
                        immediate_reward = float(raw_reward)
                    immediate_reward_applied = bool(
                        payload.get("immediate_reward_applied")
                    )
                except (TypeError, ValueError):
                    immediate_reward = None
                    immediate_reward_applied = False
            with get_session() as sess:
                sess.add(
                    GenerationTrace(
                        trace_id=state.get("trace_id", ""),
                        session_id=state.get("session_id", ""),
                        turn_idx=(
                            int(logical_turn_idx)
                            if logical_turn_idx is not None
                            else state.get("turn_idx", 0)
                        ),
                        node=node,
                        dimension=state.get("current_dimension")
                        or question.get("dimension"),
                        action_id=action.get("id"),
                        policy_id=state.get("policy_id"),
                        context_key=self._context_key(state),
                        policy_context_keys=self._policy_context_keys(state) or None,
                        score=None,
                        passed=None,
                        immediate_reward=immediate_reward,
                        immediate_reward_applied=immediate_reward_applied,
                        state_snapshot={
                            "payload": _attach_timing(
                                payload,
                                node_elapsed_ms=node_elapsed_ms,
                            ),
                            "state": state_snapshot,
                        },
                        question=question.get("question"),
                        answer=answer,
                        evaluation=row_evaluation,
                        langsmith_run_id=run_id,
                    )
                )
            _record_trace_success(operation)
        except Exception as e:  # pragma: no cover - fire-and-forget
            _record_trace_failure(operation)
            log.warning("trace_%s failed: %s", node, e)

    def trace_final_report(self, state: dict[str, Any]) -> None:
        if not self.enabled:
            return
        _ensure_db()
        try:
            with get_session() as sess:
                sess_row = sess.get(InterviewSession, state.get("session_id"))
                if sess_row is not None:
                    sess_row.status = "completed"
                    sess_row.final_report = state.get("final_report")
                    sess_row.enable_video_analysis = self._enable_video_analysis(state)
                    sess_row.updated_at = datetime.now(UTC)
                else:
                    sess.add(
                        InterviewSession(
                            session_id=state.get("session_id", ""),
                            trace_id=state.get("trace_id", ""),
                            candidate_name=(state.get("candidate") or {}).get("name"),
                            job_title=(state.get("job_spec") or {}).get("title"),
                            job_level=(state.get("job_spec") or {}).get("level"),
                            mode=state.get("mode", "mixed"),
                            enable_video_analysis=self._enable_video_analysis(state),
                            status="completed",
                            final_report=state.get("final_report"),
                        )
                    )
            _record_trace_success("final_report")
        except Exception as e:  # pragma: no cover
            _record_trace_failure("final_report")
            log.warning("trace_final_report failed: %s", e)


_tracer: Tracer | None = None


def get_tracer() -> Tracer:
    global _tracer
    if _tracer is None:
        _tracer = Tracer()
    return _tracer
