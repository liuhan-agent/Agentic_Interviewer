"""Shared classifier for the ``trace_health`` admin / report signal.

Two callers consume the classifier today:

- ``app/api/v1/admin.py`` decorates each session row in
  ``GET /admin/interview-sessions`` and the per-session detail in
  ``GET /admin/interview-sessions/{id}/traces``.
- ``app/api/v1/interview.py`` enriches the candidate-facing
  ``GET /sessions/{id}/report`` payload so the **Quality Center** card
  on the report page agrees with the engineer view in *Trace Explorer*.

Keeping the rules in one module lets us evolve the heuristic without
hunting two grep paths or copy-pasting subtle status overrides
(``cancelled`` / ``running`` must downgrade ``complete`` to
``partial``, see :func:`classify_trace_health`).
"""
from __future__ import annotations

from typing import Any, Literal

from app.core.logging import get_logger

TraceHealth = Literal["missing", "partial", "complete"]

log = get_logger(__name__)

KEY_TRACE_NODES = [
    "director_sample",
    "ask_question",
    "evaluator",
    "verification",
    "reward_update",
    "final_report",
]


def classify_trace_health(
    nodes: list[dict[str, Any]],
    *,
    session_status: str | None = None,
) -> TraceHealth:
    """Pure node-coverage classifier reused by every visible surface.

    ``nodes`` is a list of dicts each carrying a ``"node"`` key — the
    node name as written by ``Tracer`` (``evaluator``, ``reward_update``,
    ``final_report``, …).  ``session_status`` (when provided) gates the
    transition from ``partial`` to ``complete``: an interview that was
    cancelled mid-flight may already have ``evaluator`` and
    ``reward_update`` rows, but the panel must not report it as a
    closed loop.
    """
    if not nodes:
        return "missing"
    node_names = {str(node.get("node") or "") for node in nodes}
    has_evaluator = "evaluator" in node_names
    has_learning_close = bool({"reward_update", "final_report"} & node_names)
    if not (has_evaluator and has_learning_close):
        return "partial"
    if session_status and session_status != "completed":
        return "partial"
    return "complete"


def trace_diagnostics(
    nodes: list[dict[str, Any]],
    *,
    session_status: str | None = None,
) -> dict[str, Any]:
    """Return a human-readable coverage summary for Trace Explorer."""
    node_names = [str(node.get("node") or "") for node in nodes]
    present = {node for node in node_names if node}
    return {
        "health": classify_trace_health(nodes, session_status=session_status),
        "present_nodes": sorted(present),
        "missing_key_nodes": [
            node for node in KEY_TRACE_NODES if node not in present
        ],
        "last_node": node_names[-1] if node_names else None,
        "session_status": session_status,
    }


def compute_session_trace_health(session_id: str) -> TraceHealth:
    """Resolve the ``trace_health`` for a single persisted session.

    Performs a single grouped SQL query against ``generation_traces``
    plus a ``InterviewSession`` lookup, and feeds both into
    :func:`classify_trace_health`. Falls back to ``"missing"`` on any
    error so the caller (typically the report API) stays available
    even if the trace DB is temporarily unreachable — this mirrors the
    fire-and-forget posture the rest of the tracer already takes.
    """
    if not session_id:
        return "missing"
    try:
        from sqlalchemy import func

        from app.models import GenerationTrace, InterviewSession, get_session

        with get_session() as sess:
            row = sess.get(InterviewSession, session_id)
            session_status = row.status if row is not None else None
            node_rows = (
                sess.query(GenerationTrace.node, func.count(GenerationTrace.id))
                .filter(GenerationTrace.session_id == session_id)
                .group_by(GenerationTrace.node)
                .all()
            )
    except Exception as e:  # pragma: no cover - DB outages must not 500 the report
        log.warning("compute_session_trace_health failed for %s: %s", session_id, e)
        return "missing"
    nodes = [{"node": str(node_name)} for node_name, _ in node_rows]
    return classify_trace_health(nodes, session_status=session_status)
