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
    final_report["workflow_artifacts"] = artifacts
    log.info(
        "training_plan: source=%s priorities=%d",
        training_plan.get("source"),
        len(training_plan.get("priority_weaknesses") or []),
    )
    update = {"final_report": final_report}
    _trace_training_plan(
        state,
        update,
        reason="attached",
        source=str(training_plan.get("source") or ""),
    )
    return update


def _trace_training_plan(
    state: InterviewState,
    update: dict[str, Any],
    *,
    reason: str,
    source: str = "",
) -> None:
    try:
        get_tracer().trace_node_event(
            {**state, **update},
            node="training_plan",
            payload={"reason": reason, "source": source},
        )
    except Exception as e:  # pragma: no cover - side channel
        log.warning("training_plan tracer side-channel failed: %s", e)
