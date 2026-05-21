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
from app.services.resume_parse_artifacts import read_resume_parse_artifact
from app.services.resume_vector_jobs import start_resume_vector_job

log = get_logger(__name__)


def resume_parse_node(state: InterviewState) -> dict[str, Any]:
    job_spec = state.get("job_spec", {})
    dims = list(job_spec.get("rubric_dimensions") or state.get("dimensions") or [])
    if not dims:
        dims = ["technical_depth", "problem_solving", "communication"]
    rubric = job_spec.get("rubric") or {d: f"Assess {d.replace('_', ' ')}." for d in dims}
    status = state.get("dimension_status") or {d: "pending" for d in dims}
    candidate = state.get("candidate") or {}
    resume_vector_status = _vectorize_resume_for_node(
        session_id=str(state.get("session_id") or ""),
        candidate=candidate,
    )
    log.info(
        "resume_parse: session=%s dims=%s title=%r vector_status=%s",
        state.get("session_id"),
        dims,
        job_spec.get("title"),
        resume_vector_status.get("status"),
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
        "candidate": {**candidate, "resume_vector_status": resume_vector_status},
    }


def _vectorize_resume_for_node(
    *,
    session_id: str,
    candidate: dict[str, Any],
) -> dict[str, Any]:
    """Start setup parse artifact vectorization in the background."""

    prior = candidate.get("resume_vector_status") or {}
    source_id = candidate.get("resume_source_id") or prior.get("resume_source_id")
    if not source_id:
        return {
            "status": "skipped",
            "skipped_reason": prior.get("skipped_reason") or "no_parse_artifact",
            "resume_source_id": None,
            "resume_revision_id": None,
        }
    try:
        artifact = read_resume_parse_artifact(str(source_id))
        if artifact is None:
            return {
                "status": "skipped",
                "skipped_reason": "parse_artifact_missing_or_expired",
                "resume_source_id": source_id,
                "resume_revision_id": None,
            }
        status = start_resume_vector_job(
            session_id=session_id,
            resume_source_id=artifact.artifact_id,
            parsed=candidate.get("resume_parsed") or getattr(artifact, "parsed", {}),
            embedding_override=_runtime_embedding_override(),
        )
        status.setdefault("resume_source_id", artifact.artifact_id)
        status.setdefault("resume_revision_id", None)
        return status
    except Exception as exc:  # pragma: no cover - workflow must degrade
        log.warning("resume_parse vectorization failed: %s", exc)
        return {
            "status": "failed",
            "error": str(exc) or exc.__class__.__name__,
            "resume_source_id": source_id,
            "resume_revision_id": None,
        }


def _runtime_embedding_override() -> dict[str, Any] | None:
    try:
        from app.services.session_manager import get_llm_override

        llm_config = get_llm_override()
    except Exception:
        return None
    if not isinstance(llm_config, dict):
        return None
    override = llm_config.get("embedding_override")
    return override if isinstance(override, dict) else None
