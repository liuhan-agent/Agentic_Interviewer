"""Training plan node: invoke the Coach and attach its plan to the report.

Runs after ``final_report_node`` so the Coach has access to the
aggregated scores and verdict. The node mutates ``state.final_report``
in-place (via a fresh copy) so the plan is the candidate's final
visible artefact.
"""
from __future__ import annotations

from typing import Any

from app.core.logging import get_logger
from app.core.tracer import get_tracer
from app.engine.agents.coach import build_training_plan
from app.engine.workflow.state import InterviewState

log = get_logger(__name__)


def _list_of_dicts(value: Any, *, limit: int = 5) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value[:limit] if isinstance(item, dict)]


def _goals_complete(goals: Any) -> bool:
    if not isinstance(goals, dict):
        return False
    return all(
        isinstance(goals.get(key), list)
        for key in ("30_days", "60_days", "90_days")
    )


def _goals_bucket_count(goals: Any) -> int:
    if not isinstance(goals, dict):
        return 0
    return sum(
        1
        for key in ("30_days", "60_days", "90_days")
        if isinstance(goals.get(key), list)
    )


def _training_plan_trace_payload(
    training_plan: dict[str, Any],
    *,
    reason: str,
    source: str = "",
    fallback_reason: str = "",
) -> dict[str, Any]:
    priority_weaknesses = training_plan.get("priority_weaknesses") or []
    practice_plan = training_plan.get("practice_plan") or []
    goals = training_plan.get("goals_30_60_90") or {}
    diagnosis = training_plan.get("diagnosis") or {}
    return {
        "reason": reason,
        "source": source,
        "fallback_reason": fallback_reason,
        "plan_summary": {
            "priority_weakness_count": (
                len(priority_weaknesses)
                if isinstance(priority_weaknesses, list)
                else 0
            ),
            "practice_task_count": (
                len(practice_plan) if isinstance(practice_plan, list) else 0
            ),
            "goals_count": _goals_bucket_count(goals),
            "goals_complete": _goals_complete(goals),
            "diagnosis_recorded": isinstance(diagnosis, dict) and bool(diagnosis),
        },
        "diagnosis": dict(diagnosis) if isinstance(diagnosis, dict) else {},
        "priority_weaknesses": _list_of_dicts(priority_weaknesses),
        "practice_plan": _list_of_dicts(practice_plan),
        "goals_30_60_90": dict(goals) if isinstance(goals, dict) else {},
    }


def training_plan_node(state: InterviewState) -> dict[str, Any]:
    # Skip when the session did not complete normally; cancelled or
    # errored runs have no coherent signal for the coach.
    if state.get("status") in {"cancelled", "errored"}:
        log.info("training_plan: skipped (status=%s)", state.get("status"))
        _trace_training_plan(state, {}, reason="status_skip")
        return {}

    final_report = dict(state.get("final_report") or {})
    if not final_report:
        log.info("training_plan: skipped (no final_report on state)")
        _trace_training_plan(state, {}, reason="missing_report")
        return {}

    training_plan = build_training_plan(
        job_spec=state.get("job_spec") or {},
        candidate=state.get("candidate") or {},
        final_report=final_report,
        qa_history=list(state.get("qa_history") or []),
        self_intro_profile=state.get("self_intro_profile") or None,
        verification=state.get("verification") or None,
    )

    final_report["training_plan"] = training_plan
    # Surface the coach's ``signal_summary`` as the report-level
    # ``summary`` field so the Next.js ``ReportView`` can render a
    # human-readable paragraph without reaching into
    # ``training_plan.signal_summary``. Only populate when the plan
    # actually produced one (fallback plans always do; LLM plans do
    # when the prompt is respected) and never overwrite a value an
    # earlier node already provided.
    signal_summary = training_plan.get("signal_summary")
    if signal_summary and not final_report.get("summary"):
        final_report["summary"] = signal_summary

    artifacts = dict(final_report.get("workflow_artifacts") or {})
    artifacts["training_plan_attached"] = True
    artifacts["training_plan_source"] = training_plan.get("source")
    fallback_reason = training_plan.get("fallback_reason")
    if fallback_reason:
        artifacts["training_plan_fallback_reason"] = fallback_reason
    final_report["workflow_artifacts"] = artifacts
    log.info(
        "training_plan: source=%s fallback_reason=%s priorities=%d",
        training_plan.get("source"),
        fallback_reason,
        len(training_plan.get("priority_weaknesses") or []),
    )
    update = {"final_report": final_report}
    _trace_training_plan(
        state,
        update,
        reason="attached",
        source=str(training_plan.get("source") or ""),
        fallback_reason=str(fallback_reason or ""),
    )
    return update


def _trace_training_plan(
    state: InterviewState,
    update: dict[str, Any],
    *,
    reason: str,
    source: str = "",
    fallback_reason: str = "",
) -> None:
    try:
        training_plan = {}
        final_report = update.get("final_report") if isinstance(update, dict) else None
        if isinstance(final_report, dict):
            training_plan = final_report.get("training_plan") or {}
        if not isinstance(training_plan, dict):
            training_plan = {}
        get_tracer().trace_node_event(
            {**state, **update},
            node="training_plan",
            payload=_training_plan_trace_payload(
                training_plan,
                reason=reason,
                source=source,
                fallback_reason=fallback_reason,
            ),
        )
    except Exception as e:  # pragma: no cover - side channel
        log.warning("training_plan tracer side-channel failed: %s", e)
