"""Resume-grounded interview anchor selection.

The workflow still rotates through rubric dimensions, but each round
can now carry a small resume anchor so the question is grounded in a
specific project or experience instead of generic skill labels.
"""
from __future__ import annotations

from typing import Any

from app.services.resume_parser import (
    normalise_resume_focus_dimensions,
    resume_focus_anchor_key,
)

_INTERVIEW_DEPTHS = {"short", "standard", "deep"}


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


def _identity_key(kind: str, value: Any) -> str:
    text = str(value or "").strip()
    return f"{kind}:{text}" if text else ""


def _used_anchor_ids(qa_history: list[dict[str, Any]]) -> set[str]:
    used: set[str] = set()
    for turn in qa_history:
        anchor = turn.get("resume_anchor")
        if isinstance(anchor, dict):
            for kind, key in (
                ("anchor", "anchor_key"),
                ("focus", "focus_id"),
                ("project", "project_id"),
            ):
                anchor_id = _identity_key(kind, anchor.get(key))
                if anchor_id:
                    used.add(anchor_id)
    return used


def _anchor_attempt_counts(qa_history: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for turn in qa_history:
        anchor = turn.get("resume_anchor")
        if not isinstance(anchor, dict):
            continue
        keys: list[str] = []
        for kind, key in (
            ("anchor", "anchor_key"),
            ("focus", "focus_id"),
            ("project", "project_id"),
        ):
            identity = _identity_key(kind, anchor.get(key))
            if identity:
                keys.append(identity)
        for key in set(keys):
            counts[key] = counts.get(key, 0) + 1
    return counts


def _attempt_count(values: list[Any], counts: dict[str, int]) -> int:
    return max(
        [counts.get(str(value), 0) for value in values if value not in (None, "")]
        or [0]
    )


def _focus_used(focus: dict[str, Any], used: set[str]) -> bool:
    focus_id = focus.get("id")
    project_id = focus.get("project_id")
    anchor_key = focus.get("anchor_key") or resume_focus_anchor_key(
        focus_id,
        project_id=project_id,
        label=focus.get("label"),
    )
    return any(
        value in used
        for value in (
            _identity_key("anchor", anchor_key),
            _identity_key("focus", focus_id),
            _identity_key("project", project_id),
        )
        if value
    )


def _project_by_id(projects: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(p.get("id")): p for p in projects if isinstance(p, dict)}


def _priority(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 999


def _normalise_depth(value: Any) -> str:
    return value if isinstance(value, str) and value in _INTERVIEW_DEPTHS else "standard"


def _lower_terms(values: list[Any]) -> set[str]:
    return {str(value).strip().lower() for value in values if str(value).strip()}


def _skill_overlap(focus: dict[str, Any], project: dict[str, Any], job_spec: dict[str, Any]) -> bool:
    required = _lower_terms(_normalise_str_list(job_spec.get("required_skills")))
    if not required:
        return False
    skills = _lower_terms(
        _normalise_str_list(focus.get("skills"))
        + _normalise_str_list(project.get("tech_stack"))
    )
    return bool(required & skills)


def _focus_anchor_key(focus: dict[str, Any], project: dict[str, Any] | None) -> str:
    project = project or {}
    project_id = focus.get("project_id") or project.get("id")
    label = focus.get("label") or project.get("name")
    return str(
        focus.get("anchor_key")
        or resume_focus_anchor_key(focus.get("id"), project_id=project_id, label=label)
    )


def _focus_identity_values(
    focus: dict[str, Any],
    project: dict[str, Any] | None,
) -> list[Any]:
    return [
        _identity_key("anchor", _focus_anchor_key(focus, project)),
        _identity_key("focus", focus.get("id")),
    ]


def _project_identity_values(project: dict[str, Any]) -> list[Any]:
    return [
        _identity_key(
            "anchor",
            resume_focus_anchor_key(
                None,
                project_id=project.get("id"),
                label=project.get("name"),
            ),
        ),
        _identity_key("project", project.get("id")),
    ]


def _anchor_project_identity_values(anchor: dict[str, Any]) -> list[Any]:
    return [
        _identity_key("anchor", anchor.get("anchor_key")),
        _identity_key("project", anchor.get("project_id")),
    ]


def _high_value_reasons(
    focus: dict[str, Any],
    project: dict[str, Any] | None,
    *,
    job_spec: dict[str, Any],
    focus_dimensions: list[str] | None,
    self_intro_profile: dict[str, Any] | None,
) -> list[str]:
    project = project or {}
    reasons: list[str] = []
    if _priority(focus.get("priority")) <= 2:
        reasons.append("priority")
    if _skill_overlap(focus, project, job_spec):
        reasons.append("required_skill_overlap")
    dimensions = set(
        normalise_resume_focus_dimensions(
            focus.get("dimensions"),
            text_parts=[
                str(focus.get("label") or ""),
                " ".join(_normalise_str_list(focus.get("skills"))),
            ],
        )
    )
    if dimensions & set(focus_dimensions or []):
        reasons.append("focus_dimension")
    intro_terms = _self_intro_terms(self_intro_profile)
    if intro_terms and (
        _matches_any(focus.get("label"), intro_terms)
        or any(_matches_any(skill, intro_terms) for skill in _normalise_str_list(focus.get("skills")))
        or _matches_any(project.get("name"), intro_terms)
    ):
        reasons.append("self_intro")
    return reasons


def _max_attempts_for_anchor(depth: str, high_value_reasons: list[str]) -> int:
    if depth == "short":
        return 1
    return 2 if high_value_reasons else 1


def _empty_selection(depth: str) -> dict[str, Any]:
    return {
        "resume_anchor": None,
        "scheduler": {
            "available": False,
            "interview_depth": depth,
            "anchor_key": None,
            "anchor_attempt": 0,
            "max_anchor_attempts": 0,
            "expansion_reason": "none",
            "high_value_reasons": [],
        },
    }


def _selection_payload(
    *,
    anchor: dict[str, Any],
    depth: str,
    attempts: int,
    max_attempts: int,
    expansion_reason: str,
    high_value_reasons: list[str],
) -> dict[str, Any]:
    return {
        "resume_anchor": anchor,
        "scheduler": {
            "available": True,
            "interview_depth": depth,
            "anchor_key": anchor.get("anchor_key"),
            "anchor_attempt": attempts + 1,
            "max_anchor_attempts": max_attempts,
            "expansion_reason": expansion_reason,
            "high_value_reasons": high_value_reasons,
        },
    }


def _anchor_from_focus(
    focus: dict[str, Any],
    project: dict[str, Any] | None,
) -> dict[str, Any]:
    project = project or {}
    focus_id = focus.get("id")
    project_id = focus.get("project_id") or project.get("id")
    label = focus.get("label") or project.get("name") or "简历项目"
    dimensions = normalise_resume_focus_dimensions(
        focus.get("dimensions"),
        text_parts=[
            str(label),
            " ".join(_normalise_str_list(focus.get("skills"))),
            " ".join(_normalise_str_list(project.get("question_anchors"))),
            " ".join(_normalise_str_list(project.get("achievements"))),
        ],
    )
    return {
        "focus_id": focus_id,
        "anchor_key": focus.get("anchor_key")
        or resume_focus_anchor_key(focus_id, project_id=project_id, label=label),
        "label": label,
        "project_id": project_id,
        "project_name": project.get("name") or "",
        "role": project.get("role") or "",
        "tech_stack": _normalise_str_list(
            project.get("tech_stack") or focus.get("skills")
        )[:8],
        "skills": _normalise_str_list(focus.get("skills"))[:8],
        "dimensions": dimensions,
        "question_anchors": _normalise_str_list(project.get("question_anchors"))[:5],
        "achievements": _normalise_str_list(project.get("achievements"))[:4],
        "knowledge_source": "local",
    }


def _anchor_from_project(project: dict[str, Any]) -> dict[str, Any]:
    project_id = project.get("id")
    label = project.get("name") or "简历项目"
    return {
        "focus_id": None,
        "anchor_key": resume_focus_anchor_key(None, project_id=project_id, label=label),
        "label": label,
        "project_id": project_id,
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
        "anchor_key": resume_focus_anchor_key(None, project_id=None, label=label),
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


def select_resume_anchor_with_schedule(
    *,
    candidate: dict[str, Any],
    job_spec: dict[str, Any],
    dimension: str,
    qa_history: list[dict[str, Any]],
    turn_idx: int,
    self_intro_profile: dict[str, Any] | None = None,
    interview_depth: str = "standard",
    focus_dimensions: list[str] | None = None,
) -> dict[str, Any]:
    """Pick the best resume anchor for the upcoming question.

    Priority:
    1. Unused focus area matching the current dimension.
    2. Any unused focus area.
    3. Any project not used recently.

    ``job_spec`` is accepted for future direction-specific weighting;
    v1 keeps the selector deterministic and local-only.
    """
    depth = _normalise_depth(interview_depth)
    parsed = candidate.get("resume_parsed") or {}
    if not isinstance(parsed, dict):
        return _empty_selection(depth)
    projects = [p for p in _as_list(parsed.get("projects")) if isinstance(p, dict)]
    focus_areas = [
        f for f in _as_list(parsed.get("focus_areas")) if isinstance(f, dict)
    ]
    if not projects and not focus_areas:
        return _empty_selection(depth)

    projects_by_id = _project_by_id(projects)
    intro_terms = _self_intro_terms(self_intro_profile)
    ranked_focus = sorted(
        focus_areas,
        key=lambda f: _priority(f.get("priority")),
    )
    counts = _anchor_attempt_counts(qa_history)

    records: list[dict[str, Any]] = []
    for focus in ranked_focus:
        project = projects_by_id.get(str(focus.get("project_id")))
        dimensions = normalise_resume_focus_dimensions(
            focus.get("dimensions"),
            text_parts=[
                str(focus.get("label") or ""),
                " ".join(_normalise_str_list(focus.get("skills"))),
            ],
        )
        high_value_reasons = _high_value_reasons(
            focus,
            project,
            job_spec=job_spec,
            focus_dimensions=focus_dimensions,
            self_intro_profile=self_intro_profile,
        )
        max_attempts = _max_attempts_for_anchor(depth, high_value_reasons)
        attempts = _attempt_count(_focus_identity_values(focus, project), counts)
        records.append(
            {
                "focus": focus,
                "project": project,
                "dimensions": dimensions,
                "attempts": attempts,
                "max_attempts": max_attempts,
                "high_value_reasons": high_value_reasons,
                "intro_match": bool(
                    intro_terms
                    and (
                        _matches_any(focus.get("label"), intro_terms)
                        or any(
                            _matches_any(skill, intro_terms)
                            for skill in _normalise_str_list(focus.get("skills"))
                        )
                        or _matches_any((project or {}).get("name"), intro_terms)
                    )
                ),
            }
        )

    def choose(pool: list[dict[str, Any]], reason: str) -> dict[str, Any] | None:
        if not pool:
            return None
        record = pool[0]
        anchor = _anchor_from_focus(record["focus"], record["project"])
        return _selection_payload(
            anchor=anchor,
            depth=depth,
            attempts=int(record["attempts"]),
            max_attempts=int(record["max_attempts"]),
            expansion_reason=reason,
            high_value_reasons=list(record["high_value_reasons"]),
        )

    if intro_terms:
        selected = choose(
            [record for record in records if record["intro_match"] and record["attempts"] == 0],
            "first_pass_self_intro_match",
        )
        if selected:
            return selected

    selected = choose(
        [
            record
            for record in records
            if dimension and dimension in record["dimensions"] and record["attempts"] == 0
        ],
        "first_pass_dimension_match",
    )
    if selected:
        return selected

    selected = choose(
        [record for record in records if record["attempts"] == 0],
        "first_pass_any_anchor",
    )
    if selected:
        return selected

    selected = choose(
        [
            record
            for record in records
            if dimension
            and dimension in record["dimensions"]
            and record["attempts"] < record["max_attempts"]
        ],
        "high_value_second_pass",
    )
    if selected:
        return selected

    selected = choose(
        [record for record in records if record["attempts"] < record["max_attempts"]],
        "high_value_second_pass",
    )
    if selected:
        return selected

    if records:
        return _empty_selection(depth)

    if intro_terms and isinstance(self_intro_profile, dict):
        anchor = _anchor_from_self_intro(self_intro_profile)
        if anchor:
            return _selection_payload(
                anchor=anchor,
                depth=depth,
                attempts=0,
                max_attempts=1,
                expansion_reason="self_intro_fallback",
                high_value_reasons=["self_intro"],
            )

    project_pool = [
        p for p in projects if _attempt_count(_project_identity_values(p), counts) == 0
    ] or projects
    if not project_pool:
        return _empty_selection(depth)
    anchor = _anchor_from_project(project_pool[turn_idx % len(project_pool)])
    attempts = _attempt_count(_anchor_project_identity_values(anchor), counts)
    if attempts > 0:
        return _empty_selection(depth)
    return _selection_payload(
        anchor=anchor,
        depth=depth,
        attempts=attempts,
        max_attempts=1,
        expansion_reason="project_fallback",
        high_value_reasons=[],
    )


def has_available_resume_anchor_slot(
    *,
    candidate: dict[str, Any],
    job_spec: dict[str, Any],
    qa_history: list[dict[str, Any]],
    interview_depth: str = "standard",
    focus_dimensions: list[str] | None = None,
    self_intro_profile: dict[str, Any] | None = None,
) -> bool:
    selection = select_resume_anchor_with_schedule(
        candidate=candidate,
        job_spec=job_spec,
        dimension="",
        qa_history=qa_history,
        turn_idx=0,
        self_intro_profile=self_intro_profile,
        interview_depth=interview_depth,
        focus_dimensions=focus_dimensions,
    )
    return bool((selection.get("scheduler") or {}).get("available"))


def select_resume_anchor(
    *,
    candidate: dict[str, Any],
    job_spec: dict[str, Any],
    dimension: str,
    qa_history: list[dict[str, Any]],
    turn_idx: int,
    self_intro_profile: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    selection = select_resume_anchor_with_schedule(
        candidate=candidate,
        job_spec=job_spec,
        dimension=dimension,
        qa_history=qa_history,
        turn_idx=turn_idx,
        self_intro_profile=self_intro_profile,
    )
    anchor = selection.get("resume_anchor")
    return anchor if isinstance(anchor, dict) else None
