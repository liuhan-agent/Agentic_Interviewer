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

from collections.abc import Mapping
from typing import Any

from app.core.logging import get_logger
from app.core.tracer import get_tracer
from app.engine.workflow.state import InterviewState
from app.services.resume_parse_artifacts import read_resume_parse_artifact
from app.services.resume_vector_jobs import start_resume_vector_job
from app.services.trace_nodes import trace_node_metadata, trace_status_summary

log = get_logger(__name__)


def resume_parse_node(state: InterviewState) -> dict[str, Any]:
    job_spec = state.get("job_spec", {})
    dims = list(job_spec.get("rubric_dimensions") or state.get("dimensions") or [])
    if not dims:
        dims = ["technical_depth", "problem_solving", "communication"]
    rubric = job_spec.get("rubric") or {d: f"Assess {d.replace('_', ' ')}." for d in dims}
    status = state.get("dimension_status") or {d: "pending" for d in dims}
    scores = state.get("scores_per_dim") or {d: None for d in dims}
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
    _trace_resume_parse_opening(
        state,
        dimensions=dims,
        rubric=rubric,
        dimension_status=status,
        scores_per_dim=scores,
        resume_vector_status=resume_vector_status,
    )
    return {
        "dimensions": dims,
        "rubric": rubric,
        "dimension_status": status,
        "scores_per_dim": scores,
        "candidate": {**candidate, "resume_vector_status": resume_vector_status},
    }


def _trace_resume_parse_opening(
    state: InterviewState,
    *,
    dimensions: list[str],
    rubric: dict[str, Any],
    dimension_status: Mapping[str, Any],
    scores_per_dim: Mapping[str, Any],
    resume_vector_status: dict[str, Any],
) -> None:
    candidate = state.get("candidate") or {}
    resume_parsed = (
        candidate.get("resume_parsed")
        if isinstance(candidate.get("resume_parsed"), dict)
        else {}
    )
    job_spec = state.get("job_spec") or {}
    payload = {
        **trace_node_metadata("resume_parse"),
        "phase": "opening",
        "dimensions": list(dimensions),
        "rubric_dimensions": list(dimensions),
        "required_skills": _text_list(job_spec.get("required_skills"), limit=12),
        "candidate_skills": _text_list(resume_parsed.get("skills"), limit=12),
        "resume_projects": _resume_projects_summary(resume_parsed.get("projects")),
        "resume_focus_areas": _resume_focus_areas_summary(
            resume_parsed.get("focus_areas"),
        ),
        "resume_anchors": _resume_anchor_summaries(
            projects_value=resume_parsed.get("projects"),
            focus_areas_value=resume_parsed.get("focus_areas"),
        ),
        "resume_projects_count": _list_count(resume_parsed.get("projects")),
        "resume_focus_areas_count": _list_count(resume_parsed.get("focus_areas")),
        "rubric_dimension_keys": _rubric_dimension_keys(rubric),
        "dimensions_count": len(dimensions),
        "rubric_count": len(rubric),
        "dimension_status_summary": _dimension_status_summary(
            dimensions,
            dimension_status,
        ),
        "scores_per_dim_summary": _scores_per_dim_summary(
            dimensions,
            scores_per_dim,
        ),
        "resume_vector_status": trace_status_summary(
            resume_vector_status,
            presence_fields=("resume_source_id", "resume_revision_id"),
        ),
    }
    trace_state = {
        "session_id": state.get("session_id", ""),
        "trace_id": state.get("trace_id", ""),
        "turn_idx": 0,
        "formal_turn_idx": state.get("formal_turn_idx", 0),
        "current_question": {},
    }
    try:
        get_tracer().trace_node_event(
            trace_state,
            node="resume_parse",
            payload=payload,
            logical_turn_idx=0,
        )
    except Exception as e:  # pragma: no cover
        log.warning("tracer.trace_node_event resume_parse failed: %s", e)


def _list_count(value: Any) -> int:
    return len(value) if isinstance(value, list) else 0


def _text_list(value: Any, *, limit: int = 8) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for raw in value:
        item = str(raw or "").strip()
        if not item or item in seen:
            continue
        out.append(item[:120])
        seen.add(item)
        if len(out) >= limit:
            break
    return out


def _resume_projects_summary(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    projects: list[dict[str, Any]] = []
    for idx, raw in enumerate(value[:5], start=1):
        if not isinstance(raw, Mapping):
            continue
        name = str(raw.get("name") or "").strip()
        if not name:
            continue
        projects.append(
            {
                "id": str(raw.get("id") or f"proj-{idx}")[:40],
                "name": name[:120],
                "role": str(raw.get("role") or "").strip()[:120],
                "tech_stack": _text_list(raw.get("tech_stack"), limit=8),
            }
        )
    return projects


def _resume_focus_areas_summary(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    focus_areas: list[dict[str, Any]] = []
    for idx, raw in enumerate(value[:6], start=1):
        if not isinstance(raw, Mapping):
            continue
        label = str(raw.get("label") or "").strip()
        if not label:
            continue
        priority: int | None
        try:
            priority = int(raw.get("priority")) if raw.get("priority") is not None else None
        except (TypeError, ValueError):
            priority = None
        focus_areas.append(
            {
                "id": str(raw.get("id") or f"focus-{idx}")[:40],
                "label": label[:120],
                "project_id": (
                    str(raw.get("project_id"))[:40]
                    if raw.get("project_id") is not None
                    else None
                ),
                "dimensions": _text_list(raw.get("dimensions"), limit=8),
                "skills": _text_list(raw.get("skills"), limit=8),
                "priority": priority,
            }
        )
    return focus_areas


def _project_by_id(value: Any) -> dict[str, Mapping[str, Any]]:
    if not isinstance(value, list):
        return {}
    return {
        str(raw.get("id")): raw
        for raw in value
        if isinstance(raw, Mapping) and raw.get("id") is not None
    }


def _resume_anchor_summaries(
    *,
    projects_value: Any,
    focus_areas_value: Any,
) -> list[dict[str, Any]]:
    projects = _project_by_id(projects_value)
    if isinstance(focus_areas_value, list) and focus_areas_value:
        anchors: list[dict[str, Any]] = []
        for raw in focus_areas_value[:6]:
            if not isinstance(raw, Mapping):
                continue
            project = projects.get(str(raw.get("project_id") or "")) or {}
            label = str(raw.get("label") or project.get("name") or "").strip()
            if not label:
                continue
            anchors.append(
                {
                    "label": label[:120],
                    "project_name": str(
                        project.get("name") or raw.get("project_name") or ""
                    ).strip()[:120],
                    "tech_stack": _text_list(
                        project.get("tech_stack") or raw.get("tech_stack"),
                        limit=8,
                    ),
                    "question_anchors": _text_list(
                        project.get("question_anchors") or raw.get("question_anchors"),
                        limit=5,
                    ),
                    "skills": _text_list(raw.get("skills"), limit=8),
                    "dimensions": _text_list(raw.get("dimensions"), limit=8),
                }
            )
        return anchors

    if not isinstance(projects_value, list):
        return []
    anchors = []
    for raw in projects_value[:5]:
        if not isinstance(raw, Mapping):
            continue
        label = str(raw.get("name") or raw.get("project_name") or "").strip()
        if not label:
            continue
        tech_stack = _text_list(raw.get("tech_stack"), limit=8)
        anchors.append(
            {
                "label": label[:120],
                "project_name": label[:120],
                "tech_stack": tech_stack,
                "question_anchors": _text_list(raw.get("question_anchors"), limit=5),
                "skills": tech_stack,
                "dimensions": ["project_experience", "technical_depth"],
            }
        )
    return anchors


def _rubric_dimension_keys(rubric: Mapping[str, Any]) -> list[str]:
    return [str(key) for key in rubric.keys()]


def _dimension_status_summary(
    dimensions: list[str],
    dimension_status: Mapping[str, Any],
) -> dict[str, int]:
    summary = {
        "total": len(dimensions),
        "pending": 0,
        "active": 0,
        "passed": 0,
        "failed": 0,
        "other": 0,
    }
    for dimension in dimensions:
        status = str(dimension_status.get(dimension) or "pending").strip().lower()
        if status in ("pending", "active", "passed", "failed"):
            summary[status] += 1
        else:
            summary["other"] += 1
    return summary


def _scores_per_dim_summary(
    dimensions: list[str],
    scores_per_dim: Mapping[str, Any],
) -> dict[str, int]:
    scored = 0
    for dimension in dimensions:
        value = scores_per_dim.get(dimension)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            scored += 1
    total = len(dimensions)
    return {
        "total": total,
        "scored": scored,
        "unscored": total - scored,
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
