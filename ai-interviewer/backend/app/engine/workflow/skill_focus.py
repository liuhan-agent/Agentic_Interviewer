"""Per-turn target skill selection for question generation."""
from __future__ import annotations

import re
from typing import Any


def _normalise_skill(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    return normalize_skill_alias(value)


def normalize_skill_alias(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = re.sub(r"\s+", "-", value.strip().lower()).replace("_", "-")
    compact = re.sub(r"[^a-z0-9+#.]+", "", cleaned)
    aliases = {
        "springsecurity": "spring-security",
        "springboot": "springboot",
    }
    return aliases.get(compact, cleaned) or None


def _normalise_list(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        skill = _normalise_skill(value)
        if skill and skill not in seen:
            out.append(skill)
            seen.add(skill)
    return out


def _covered_skills(qa_history: list[dict[str, Any]] | None) -> set[str]:
    covered: set[str] = set()
    for turn in qa_history or []:
        for bucket in (
            turn.get("target_skills"),
            (turn.get("current_question") or {}).get("target_skills"),
        ):
            covered.update(_normalise_list(bucket))
    return covered


def _action_limit(selected_action: dict[str, Any] | None) -> int:
    action = selected_action or {}
    marker = " ".join(
        str(action.get(key) or "")
        for key in ("id", "plan_template", "label")
    ).lower()
    if "deep_probe" in marker or "deep" in marker:
        return 3
    if "hint" in marker or "simple" in marker:
        return 1
    return 2


def _append_unique(out: list[str], items: list[str], *, limit: int) -> None:
    for item in items:
        if len(out) >= limit:
            return
        if item not in out:
            out.append(item)


def select_target_skills(
    *,
    job_spec: dict[str, Any],
    resume_anchor: dict[str, Any] | None,
    self_intro_profile: dict[str, Any] | None,
    qa_history: list[dict[str, Any]] | None,
    current_dimension: str,
    selected_action: dict[str, Any] | None,
) -> dict[str, Any]:
    """Select a small skill focus for the next question.

    Priority:
    1. JD skill that is also present on the chosen resume anchor.
    2. Skills emphasized in the self-introduction.
    3. JD skills not yet covered in previous turns.
    4. Resume-anchor skills as a final grounding fallback.
    """
    limit = _action_limit(selected_action)
    jd_skills = _normalise_list((job_spec or {}).get("required_skills"))
    anchor = resume_anchor or {}
    anchor_skills = _normalise_list(
        list(anchor.get("skills") or []) + list(anchor.get("tech_stack") or [])
    )
    intro_skills = _normalise_list(
        (self_intro_profile or {}).get("emphasized_skills")
    )
    covered = _covered_skills(qa_history)

    overlap = [
        skill
        for skill in jd_skills
        if skill in set(anchor_skills) and skill not in covered
    ]
    intro_uncovered = [skill for skill in intro_skills if skill not in covered]
    jd_uncovered = [skill for skill in jd_skills if skill not in covered]
    anchor_uncovered = [skill for skill in anchor_skills if skill not in covered]

    selected: list[str] = []
    if overlap:
        source = "jd_resume_overlap"
        _append_unique(selected, overlap, limit=limit)
        _append_unique(selected, intro_uncovered, limit=limit)
        _append_unique(selected, anchor_uncovered, limit=limit)
    elif intro_uncovered:
        source = "self_intro"
        _append_unique(selected, intro_uncovered, limit=limit)
        _append_unique(selected, jd_uncovered, limit=limit)
        _append_unique(selected, anchor_uncovered, limit=limit)
    elif jd_uncovered:
        source = "jd_uncovered"
        _append_unique(selected, jd_uncovered, limit=limit)
    elif anchor_uncovered:
        source = "resume_anchor"
        _append_unique(selected, anchor_uncovered, limit=limit)
    else:
        source = "none"

    return {
        "target_skills": selected,
        "focus_source": source,
        "current_dimension": current_dimension,
        "limit": limit,
    }
