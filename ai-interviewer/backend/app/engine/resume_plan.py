"""Resume-grounded interview anchor selection.

The workflow still rotates through rubric dimensions, but each round
can now carry a small resume anchor so the question is grounded in a
specific project or experience instead of generic skill labels.
"""
from __future__ import annotations

from typing import Any


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _normalise_str_list(value: Any) -> list[str]:
    return [str(v).strip() for v in _as_list(value) if str(v).strip()]


def _matches_any(text: Any, needles: list[str]) -> bool:
    haystack = str(text or "").lower()
    if not haystack:
        return False
    return any(needle.lower() in haystack for needle in needles if needle)


def _self_intro_terms(profile: dict[str, Any] | None) -> list[str]:
    if not isinstance(profile, dict):
        return []
    terms: list[str] = []
    terms.extend(_normalise_str_list(profile.get("emphasized_projects")))
    terms.extend(_normalise_str_list(profile.get("emphasized_skills")))
    terms.extend(_normalise_str_list(profile.get("preferred_focus")))
    return terms


def _used_anchor_ids(qa_history: list[dict[str, Any]]) -> set[str]:
    used: set[str] = set()
    for turn in qa_history:
        anchor = turn.get("resume_anchor")
        if isinstance(anchor, dict):
            anchor_id = anchor.get("focus_id") or anchor.get("project_id")
            if anchor_id:
                used.add(str(anchor_id))
    return used


def _project_by_id(projects: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(p.get("id")): p for p in projects if isinstance(p, dict)}


def _priority(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 999


def _anchor_from_focus(
    focus: dict[str, Any],
    project: dict[str, Any] | None,
) -> dict[str, Any]:
    project = project or {}
    return {
        "focus_id": focus.get("id"),
        "label": focus.get("label") or project.get("name") or "简历项目",
        "project_id": focus.get("project_id") or project.get("id"),
        "project_name": project.get("name") or "",
        "role": project.get("role") or "",
        "tech_stack": _normalise_str_list(
            project.get("tech_stack") or focus.get("skills")
        )[:8],
        "skills": _normalise_str_list(focus.get("skills"))[:8],
        "dimensions": _normalise_str_list(focus.get("dimensions"))[:5],
        "question_anchors": _normalise_str_list(project.get("question_anchors"))[:5],
        "achievements": _normalise_str_list(project.get("achievements"))[:4],
        "knowledge_source": "local",
    }


def _anchor_from_project(project: dict[str, Any]) -> dict[str, Any]:
    return {
        "focus_id": None,
        "label": project.get("name") or "简历项目",
        "project_id": project.get("id"),
        "project_name": project.get("name") or "",
        "role": project.get("role") or "",
        "tech_stack": _normalise_str_list(project.get("tech_stack"))[:8],
        "skills": _normalise_str_list(project.get("tech_stack"))[:8],
        "dimensions": ["project_experience", "technical_depth"],
        "question_anchors": _normalise_str_list(project.get("question_anchors"))[:5],
        "achievements": _normalise_str_list(project.get("achievements"))[:4],
        "knowledge_source": "local",
    }


def _anchor_from_self_intro(profile: dict[str, Any]) -> dict[str, Any] | None:
    projects = _normalise_str_list(profile.get("emphasized_projects"))
    skills = _normalise_str_list(profile.get("emphasized_skills"))
    focus = _normalise_str_list(profile.get("preferred_focus"))
    label = (projects or focus or skills or ["自我介绍重点"])[0]
    if not label:
        return None
    return {
        "focus_id": None,
        "label": label,
        "project_id": None,
        "project_name": projects[0] if projects else "",
        "role": "",
        "tech_stack": skills[:8],
        "skills": skills[:8],
        "dimensions": ["project_experience", "communication"],
        "question_anchors": focus[:5],
        "achievements": [],
        "knowledge_source": "self_intro",
    }


def select_resume_anchor(
    *,
    candidate: dict[str, Any],
    job_spec: dict[str, Any],
    dimension: str,
    qa_history: list[dict[str, Any]],
    turn_idx: int,
    self_intro_profile: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Pick the best resume anchor for the upcoming question.

    Priority:
    1. Unused focus area matching the current dimension.
    2. Any unused focus area.
    3. Any project not used recently.

    ``job_spec`` is accepted for future direction-specific weighting;
    v1 keeps the selector deterministic and local-only.
    """
    del job_spec  # reserved extension point for direction weighting
    parsed = candidate.get("resume_parsed") or {}
    if not isinstance(parsed, dict):
        return None
    projects = [p for p in _as_list(parsed.get("projects")) if isinstance(p, dict)]
    focus_areas = [
        f for f in _as_list(parsed.get("focus_areas")) if isinstance(f, dict)
    ]
    if not projects and not focus_areas:
        return None

    projects_by_id = _project_by_id(projects)
    used = _used_anchor_ids(qa_history)
    intro_terms = _self_intro_terms(self_intro_profile)
    ranked_focus = sorted(
        focus_areas,
        key=lambda f: _priority(f.get("priority")),
    )
    if intro_terms:
        intro_matching = [
            f
            for f in ranked_focus
            if str(f.get("id")) not in used
            and (
                _matches_any(f.get("label"), intro_terms)
                or any(_matches_any(skill, intro_terms) for skill in _normalise_str_list(f.get("skills")))
                or _matches_any(
                    (projects_by_id.get(str(f.get("project_id"))) or {}).get("name"),
                    intro_terms,
                )
            )
        ]
        if intro_matching:
            focus = intro_matching[turn_idx % len(intro_matching)]
            project = projects_by_id.get(str(focus.get("project_id")))
            return _anchor_from_focus(focus, project)

    matching = [
        f
        for f in ranked_focus
        if dimension in _normalise_str_list(f.get("dimensions"))
        and str(f.get("id")) not in used
    ]
    pool = matching or [
        f for f in ranked_focus if str(f.get("id")) not in used
    ] or ranked_focus
    if pool:
        focus = pool[turn_idx % len(pool)]
        project = projects_by_id.get(str(focus.get("project_id")))
        return _anchor_from_focus(focus, project)

    if intro_terms and isinstance(self_intro_profile, dict):
        anchor = _anchor_from_self_intro(self_intro_profile)
        if anchor:
            return anchor

    project_pool = [
        p for p in projects if str(p.get("id")) not in used
    ] or projects
    if not project_pool:
        return None
    return _anchor_from_project(project_pool[turn_idx % len(project_pool)])
