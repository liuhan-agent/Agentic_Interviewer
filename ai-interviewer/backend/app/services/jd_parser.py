"""Job-description (JD) ingestion: free-text -> structured rubric hints."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.core.logging import get_logger
from app.core.settings import get_settings
from app.services.job_directions import (
    InterviewDirection,
    InterviewDirectionNotFound,
    get_interview_direction,
)
from app.services.job_directions import (
    all_dimension_options as direction_dimension_options,
)
from app.services.job_directions import (
    dimension_label as direction_dimension_label,
)
from app.services.resume_parser import _SKILL_DICTIONARY

log = get_logger(__name__)


MAX_TEXT_CHARS = 20_000


# Backwards-compatible default catalog for callers that do not pass an
# interview direction yet. Direction-scoped parsing uses
# ``interview_directions.json`` instead.
_DIMENSION_CATALOG: dict[str, tuple[str, ...]] = {
    "technical_depth": (
        "technical depth",
        "deep expertise",
        "expert in",
        "strong fundamentals",
        "技术深度",
        "技术功底",
    ),
    "system_design": (
        "system design",
        "architecture",
        "distributed",
        "scalability",
        "scale",
        "high availability",
        "microservice",
        "系统设计",
        "架构",
        "分布式",
        "高可用",
    ),
    "problem_solving": (
        "problem solving",
        "troubleshoot",
        "debug",
        "incident",
        "root cause",
        "问题解决",
        "排查",
        "调优",
    ),
    "coding_quality": (
        "code quality",
        "clean code",
        "code review",
        "test coverage",
        "代码质量",
        "代码评审",
    ),
    "project_experience": (
        "project experience",
        "delivered",
        "shipped",
        "owned",
        "end-to-end",
        "项目经验",
        "落地",
        "交付",
    ),
    "communication": (
        "communication",
        "stakeholder",
        "collaborate",
        "cross-team",
        "cross-functional",
        "沟通",
        "跨团队",
        "协作",
    ),
    "leadership": (
        "leadership",
        "lead a team",
        "mentor",
        "manage",
        "tech lead",
        "engineering manager",
        "领导力",
        "带团队",
        "管理",
    ),
    "product_thinking": (
        "product thinking",
        "product sense",
        "user empathy",
        "business impact",
        "产品思维",
        "业务理解",
    ),
}

_DEFAULT_DIMENSIONS = ("technical_depth", "problem_solving", "communication")
_LEVEL_KEYWORDS = {
    "principal": ("principal",),
    "staff": ("staff", "tech lead", "技术专家"),
    "senior": ("senior", "高级", "sr.", "lead"),
    "mid": ("mid-level", "intermediate", "中级"),
    "junior": ("junior", "entry", "associate", "初级"),
}
_VALID_LEVELS = frozenset(_LEVEL_KEYWORDS)


class JDParseError(ValueError):
    """Raised when the JD text is empty or otherwise unusable."""


@dataclass(frozen=True)
class ParsedJobSpec:
    required_skills: list[str]
    rubric_dimensions: list[str]
    suggested_level: str | None
    rationale: str
    unmapped_requirements: list[str] | None = None


def _direction_catalog(direction: str | None) -> InterviewDirection | None:
    if not direction:
        return None
    try:
        return get_interview_direction(direction)
    except InterviewDirectionNotFound as e:
        raise JDParseError(f"Unknown interview direction: {direction}") from e


def _dimension_triggers(
    direction_info: InterviewDirection | None,
) -> dict[str, tuple[str, ...]]:
    if direction_info is None:
        return _DIMENSION_CATALOG
    return {
        item.id: tuple(item.triggers)
        for item in direction_info.dimension_catalog
    }


def _default_dimensions(direction_info: InterviewDirection | None) -> list[str]:
    if direction_info is None:
        return list(_DEFAULT_DIMENSIONS)
    return direction_info.rubric_dimensions[:5]


def _valid_dimensions(direction_info: InterviewDirection | None) -> set[str]:
    if direction_info is None:
        return set(_DIMENSION_CATALOG)
    return set(direction_info.rubric_dimensions)


def _format_dimension_catalog(direction_info: InterviewDirection | None) -> str:
    if direction_info is None:
        return "\n".join(f"- {dim}: {', '.join(triggers[:4])}" for dim, triggers in _DIMENSION_CATALOG.items())
    return "\n".join(
        f"- {item.id}: {item.label}; {item.description}"
        for item in direction_info.dimension_catalog
    )


# ---------------------------------------------------------------------------
# Heuristic baseline
# ---------------------------------------------------------------------------


def _normalise_skill(s: Any) -> str | None:
    if not isinstance(s, str):
        return None
    cleaned = re.sub(r"\s+", "-", s.strip().lower())
    return cleaned or None


def _heuristic_required_skills(
    text: str,
    *,
    direction_info: InterviewDirection | None = None,
) -> list[str]:
    lower = text.lower()
    found: list[str] = []
    seen: set[str] = set()
    candidates = list(_SKILL_DICTIONARY)
    if direction_info is not None:
        candidates.extend(direction_info.skills)
    for skill in candidates:
        normalised = _normalise_skill(skill)
        if not normalised or normalised in seen:
            continue
        pattern = r"(?<![a-z0-9])" + re.escape(skill.lower()) + r"(?![a-z0-9])"
        if re.search(pattern, lower) or skill.lower() in lower:
            found.append(normalised)
            seen.add(normalised)
    return found


def _heuristic_rubric_dimensions(
    text: str,
    *,
    direction_info: InterviewDirection | None = None,
) -> list[str]:
    if not text.strip():
        return _default_dimensions(direction_info)
    lower = text.lower()
    matched: list[str] = []
    for dim, triggers in _dimension_triggers(direction_info).items():
        if any(t.lower() in lower for t in triggers):
            matched.append(dim)
    if not matched:
        return _default_dimensions(direction_info)
    return matched[:5]


def _heuristic_level(text: str) -> str | None:
    lower = text.lower()
    for level, keys in _LEVEL_KEYWORDS.items():
        for k in keys:
            if k in lower:
                return level
    return None


def _clean_context_value(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = " ".join(value.strip().split())
    return cleaned or None


def _normalise_level(value: str | None) -> str | None:
    cleaned = _clean_context_value(value)
    if not cleaned:
        return None
    level = cleaned.lower()
    return level if level in _VALID_LEVELS else None


def _contextual_text(
    text: str,
    *,
    title: str | None = None,
    level: str | None = None,
) -> str:
    parts: list[str] = []
    clean_title = _clean_context_value(title)
    clean_level = _clean_context_value(level)
    if clean_title:
        parts.append(f"Job title: {clean_title}")
    if clean_level:
        parts.append(f"Target level: {clean_level}")
    parts.append(text)
    return "\n".join(parts)


def heuristic_parse_jd(
    text: str,
    *,
    direction: str | None = None,
    title: str | None = None,
    level: str | None = None,
) -> ParsedJobSpec:
    direction_info = _direction_catalog(direction)
    contextual_text = _contextual_text(text, title=title, level=level)
    return ParsedJobSpec(
        required_skills=_heuristic_required_skills(
            contextual_text,
            direction_info=direction_info,
        ),
        rubric_dimensions=_heuristic_rubric_dimensions(
            contextual_text,
            direction_info=direction_info,
        ),
        suggested_level=_normalise_level(level) or _heuristic_level(contextual_text),
        rationale="heuristic",
        unmapped_requirements=[],
    )


# ---------------------------------------------------------------------------
# LLM refinement
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """You are a precise hiring rubric architect.

Read the job description (JD) the user provides and return ONLY a
JSON object with these fields:

- "required_skills": array of normalized lowercase skill keywords the
  role actually demands. 4-10 entries is typical.
- "rubric_dimensions": array of 3-5 evaluation dimensions, picked ONLY
  from this fixed catalog. Use the IDs as-is:
{dimension_catalog}
- "rubric_dimension_labels": optional array matching the selected ids.
- "unmapped_requirements": optional array of concise requirements from
  the JD that do not fit the fixed catalog cleanly. Do not force them
  into a weak dimension match.
- "suggested_level": one of "junior" | "mid" | "senior" | "staff"
  | "principal", or null when unclear.
- "rationale": one short sentence (<=140 chars) explaining the
  dimension picks.

Hard rules:
- Output ONLY valid JSON. No markdown fences, no commentary.
- If the JD is too sparse, return empty arrays / null fields rather
  than inventing demands the JD does not state.
- Never use dimension IDs outside the catalog. Reject custom ones.
"""


def _llm_refine(
    text: str,
    *,
    direction_info: InterviewDirection | None = None,
    title: str | None = None,
    level: str | None = None,
) -> dict[str, Any]:
    from app.engine.agents.llm_client import (
        ChatMessage,
        call_chat,
        parse_json_response,
    )

    messages = [
        ChatMessage(
            role="system",
            content=_SYSTEM_PROMPT.format(
                dimension_catalog=_format_dimension_catalog(direction_info)
            ),
        ),
        ChatMessage(
            role="user",
            content=(
                "Parse the following job description into the JSON schema described.\n\n"
                f"{_contextual_text('', title=title, level=level).strip()}\n\n"
                "----- JD START -----\n"
                f"{text}\n"
                "----- JD END -----"
            ),
        ),
    ]
    try:
        raw = call_chat(
            messages,
            json_mode=True,
            temperature=0.1,
            agent_role="jd_parser",
        )
    except Exception as e:
        log.warning("jd_parser: LLM call failed, falling back to heuristic: %s", e)
        return {}
    parsed = parse_json_response(raw)
    return parsed if isinstance(parsed, dict) else {}


def _filter_dims(
    values: Any,
    *,
    direction_info: InterviewDirection | None = None,
) -> list[str]:
    if not isinstance(values, list):
        return []
    valid = _valid_dimensions(direction_info)
    out: list[str] = []
    seen: set[str] = set()
    for v in values:
        if isinstance(v, str):
            clean = v.strip().lower()
            if clean in valid and clean not in seen:
                out.append(clean)
                seen.add(clean)
    return out


def _normalise_unmapped(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, str):
            continue
        item = " ".join(value.strip().split())[:160]
        if item and item not in seen:
            out.append(item)
            seen.add(item)
        if len(out) >= 8:
            break
    return out


def _merge(
    heuristic: ParsedJobSpec,
    llm: dict[str, Any],
    *,
    direction: str | None = None,
) -> ParsedJobSpec:
    direction_info = _direction_catalog(direction)
    skills_out: list[str] = []
    seen: set[str] = set()
    if isinstance(llm.get("required_skills"), list):
        for s in llm["required_skills"]:
            n = _normalise_skill(s)
            if n and n not in seen:
                skills_out.append(n)
                seen.add(n)
    for s in heuristic.required_skills:
        n = _normalise_skill(s)
        if n and n not in seen:
            skills_out.append(n)
            seen.add(n)

    dims = _filter_dims(
        llm.get("rubric_dimensions"),
        direction_info=direction_info,
    ) or [
        dim
        for dim in heuristic.rubric_dimensions
        if dim in _valid_dimensions(direction_info)
    ]
    if not dims:
        dims = _default_dimensions(direction_info)
    if len(dims) > 5:
        dims = dims[:5]

    level = heuristic.suggested_level
    if isinstance(llm.get("suggested_level"), str):
        candidate = llm["suggested_level"].strip().lower()
        if candidate in {"junior", "mid", "senior", "staff", "principal"}:
            level = candidate

    rationale = heuristic.rationale
    if isinstance(llm.get("rationale"), str) and llm["rationale"].strip():
        rationale = llm["rationale"].strip()[:200]

    return ParsedJobSpec(
        required_skills=skills_out,
        rubric_dimensions=dims,
        suggested_level=level,
        rationale=rationale,
        unmapped_requirements=_normalise_unmapped(llm.get("unmapped_requirements")),
    )


def parse_job_spec(
    text: str,
    *,
    direction: str | None = None,
    title: str | None = None,
    level: str | None = None,
    force_llm: bool = False,
) -> ParsedJobSpec:
    """Public entrypoint: heuristic baseline + optional LLM refinement."""
    text = (text or "").strip()
    if not text:
        raise JDParseError("Job description is empty")
    if len(text) > MAX_TEXT_CHARS:
        text = text[:MAX_TEXT_CHARS]

    direction_info = _direction_catalog(direction)
    baseline = heuristic_parse_jd(text, direction=direction, title=title, level=level)
    if get_settings().use_stub_llm and not force_llm:
        return baseline
    refined = _llm_refine(
        text,
        direction_info=direction_info,
        title=title,
        level=level,
    )
    if not refined:
        return baseline
    return _merge(baseline, refined, direction=direction)


def dimension_label(dim: str) -> str:
    """UI label for a canonical dimension id."""
    return direction_dimension_label(dim)


def all_dimension_options() -> list[dict[str, str]]:
    """Full catalog with labels used by the frontend's dimension picker."""
    return direction_dimension_options()
