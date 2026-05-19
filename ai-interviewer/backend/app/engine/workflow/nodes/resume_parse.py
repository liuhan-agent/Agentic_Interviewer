"""Lock in the working rubric for the rest of the LangGraph run.

The node name is historical: this graph step does NOT itself parse
raw resume bytes. File ingestion lives outside the graph in
:mod:`app.services.resume_parser`, exposed via
``POST /api/v1/interview/resume/parse``. The frontend calls that
endpoint first and lets the user review/edit the extraction before
``POST /sessions`` is called with the structured ``resume_parsed``
and ``job_spec`` dicts (see ``scripts.run_demo`` for the same
contract). This node then simply locks in the rubric and the
ordered list of dimensions so every downstream node sees a stable
reference, regardless of how the upstream extraction was produced.
"""
from __future__ import annotations

from typing import Any

from app.core.logging import get_logger
from app.core.tracer import get_tracer
from app.engine.workflow.state import InterviewState

log = get_logger(__name__)


def resume_parse_node(state: InterviewState) -> dict[str, Any]:
    job_spec = state.get("job_spec", {})
    dims = list(job_spec.get("rubric_dimensions") or state.get("dimensions") or [])
    if not dims:
        dims = ["technical_depth", "problem_solving", "communication"]
    rubric = job_spec.get("rubric") or {d: f"Assess {d.replace('_', ' ')}." for d in dims}
    status = state.get("dimension_status") or {d: "pending" for d in dims}
    log.info(
        "resume_parse: session=%s dims=%s title=%r",
        state.get("session_id"),
        dims,
        job_spec.get("title"),
    )
    try:
        get_tracer().trace_session_started(dict(state))
    except Exception as e:  # pragma: no cover
        log.warning("tracer.trace_session_started failed: %s", e)
    return {
        "dimensions": dims,
        "rubric": rubric,
        "dimension_status": status,
        "scores_per_dim": state.get("scores_per_dim") or {d: None for d in dims},
    }
