"""Parse the candidate's opening self-introduction into lightweight context."""
from __future__ import annotations

import json
import re
from typing import Any

from app.core.logging import get_logger
from app.core.settings import get_settings

from .llm_client import ChatMessage, call_chat, parse_json_response

log = get_logger(__name__)

_SYSTEM = (
    "You turn a candidate's interview self-introduction into structured "
    "context for an interview question generator. Respond only JSON with "
    "keys: summary, emphasized_projects, emphasized_skills, preferred_focus, "
    "clarification_targets, communication_signal, anchor_cards."
)

ALLOWED_SELF_INTRO_CARD_KINDS = {
    "project",
    "responsibility",
    "tech",
    "difficulty",
    "result",
    "claim",
}


def _has_self_intro_llm_override_key() -> bool:
    try:
        from app.services.session_manager import get_llm_override
    except Exception:
        return False

    override = get_llm_override()
    if not isinstance(override, dict):
        return False
    if str(override.get("api_key") or "").strip():
        return True
    role_overrides = override.get("role_overrides")
    role_override = (
        role_overrides.get("self_intro_parser")
        if isinstance(role_overrides, dict)
        else None
    )
    return isinstance(role_override, dict) and bool(
        str(role_override.get("api_key") or "").strip()
    )


def _as_text_list(value: Any, *, limit: int = 6) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = str(item).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text[:80])
        if len(out) >= limit:
            break
    return out


def _resume_projects(candidate: dict[str, Any]) -> list[dict[str, Any]]:
    parsed = candidate.get("resume_parsed") or {}
    projects = parsed.get("projects") if isinstance(parsed, dict) else []
    if not isinstance(projects, list):
        return []
    return [p for p in projects if isinstance(p, dict)]


def _resume_focus_areas(candidate: dict[str, Any]) -> list[dict[str, Any]]:
    parsed = candidate.get("resume_parsed") or {}
    areas = parsed.get("focus_areas") if isinstance(parsed, dict) else []
    if not isinstance(areas, list):
        return []
    return [f for f in areas if isinstance(f, dict)]


def _candidate_skills(candidate: dict[str, Any]) -> list[str]:
    parsed = candidate.get("resume_parsed") or {}
    skills: list[str] = []
    if isinstance(parsed, dict):
        skills.extend(str(s) for s in (parsed.get("skills") or []) if s)
        for project in _resume_projects(candidate):
            skills.extend(str(s) for s in (project.get("tech_stack") or []) if s)
        for focus in _resume_focus_areas(candidate):
            skills.extend(str(s) for s in (focus.get("skills") or []) if s)
    return _as_text_list(skills, limit=12)


def _contains(haystack: str, needle: str) -> bool:
    needle = needle.strip()
    if not needle:
        return False
    return needle.lower() in haystack.lower()


def _heuristic_profile(
    *,
    answer: str,
    candidate: dict[str, Any],
) -> dict[str, Any]:
    text = re.sub(r"\s+", " ", (answer or "").strip())
    projects: list[str] = []
    for project in _resume_projects(candidate):
        name = str(project.get("name") or "").strip()
        if name and _contains(text, name):
            projects.append(name)
    for focus in _resume_focus_areas(candidate):
        label = str(focus.get("label") or "").strip()
        if label and _contains(text, label):
            projects.append(label)

    skills = [skill for skill in _candidate_skills(candidate) if _contains(text, skill)]

    preferred_focus: list[str] = []
    focus_markers = ("重点", "希望", "主要", "核心", "擅长", "关注")
    if any(marker in text for marker in focus_markers):
        preferred_focus = _as_text_list(projects + skills, limit=6)

    clarification_targets: list[str] = []
    if not projects and _resume_projects(candidate):
        clarification_targets.append("自我介绍没有明确点名简历项目")
    if len(text) < 40:
        clarification_targets.append("自我介绍较短，需要补充项目背景")

    if len(text) >= 120 and ("第一" in text or "首先" in text or "其次" in text):
        structure = "clear"
    elif len(text) < 40:
        structure = "unclear"
    else:
        structure = "average"

    return {
        "summary": text[:240] or "候选人完成了开场自我介绍。",
        "emphasized_projects": _as_text_list(projects, limit=6),
        "emphasized_skills": _as_text_list(skills, limit=8),
        "preferred_focus": _as_text_list(preferred_focus, limit=6),
        "clarification_targets": _as_text_list(clarification_targets, limit=4),
        "communication_signal": {
            "structure": structure,
            "notes": [],
        },
        "anchor_cards": [
            {
                "kind": "claim",
                "title": "Opening self-introduction",
                "text": text[:240] or "candidate completed the opening self-introduction.",
                "tech_keywords": _as_text_list(skills, limit=10),
            }
        ],
        "parse_status": "heuristic" if text else "fallback",
    }


def _clean_anchor_cards(raw: Any, fallback: dict[str, Any]) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    seen: set[str] = set()
    items = raw if isinstance(raw, list) else []
    for item in items:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or "").strip()
        text = re.sub(r"\s+", " ", str(item.get("text") or "").strip())
        if kind not in ALLOWED_SELF_INTRO_CARD_KINDS or not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        cards.append(
            {
                "kind": kind,
                "title": str(item.get("title") or kind).strip()[:80],
                "text": text[
                    : int(get_settings().session_anchor_self_intro_card_max_chars or 500)
                ],
                "tech_keywords": _as_text_list(item.get("tech_keywords"), limit=10),
            }
        )
        if len(cards) >= int(get_settings().session_anchor_self_intro_max_cards or 8):
            break
    if cards:
        return cards
    fallback_cards = fallback.get("anchor_cards")
    return fallback_cards if isinstance(fallback_cards, list) else []


def _clean_profile(raw: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
    signal = raw.get("communication_signal")
    if not isinstance(signal, dict):
        signal = fallback.get("communication_signal") or {}
    structure = str(signal.get("structure") or "").strip()
    if structure not in {"clear", "average", "unclear"}:
        structure = (fallback.get("communication_signal") or {}).get(
            "structure",
            "average",
        )

    cleaned = {
        "summary": str(raw.get("summary") or fallback.get("summary") or "").strip()[:240],
        "emphasized_projects": _as_text_list(
            raw.get("emphasized_projects") or fallback.get("emphasized_projects"),
            limit=6,
        ),
        "emphasized_skills": _as_text_list(
            raw.get("emphasized_skills") or fallback.get("emphasized_skills"),
            limit=8,
        ),
        "preferred_focus": _as_text_list(
            raw.get("preferred_focus") or fallback.get("preferred_focus"),
            limit=6,
        ),
        "clarification_targets": _as_text_list(
            raw.get("clarification_targets") or fallback.get("clarification_targets"),
            limit=4,
        ),
        "communication_signal": {
            "structure": structure,
            "notes": _as_text_list(signal.get("notes"), limit=4),
        },
        "anchor_cards": _clean_anchor_cards(raw.get("anchor_cards"), fallback),
        "parse_status": "llm",
    }
    if not cleaned["summary"]:
        cleaned["summary"] = fallback.get("summary") or "候选人完成了开场自我介绍。"
        cleaned["parse_status"] = fallback.get("parse_status") or "fallback"
    return cleaned


def parse_self_intro_profile(
    *,
    answer: str,
    candidate: dict[str, Any],
    job_spec: dict[str, Any],
) -> dict[str, Any]:
    """Return a robust self-introduction profile.

    The LLM path is best-effort. Any timeout or malformed reply falls back to
    deterministic heuristics so the interview can continue. Server stub mode is
    also heuristic-only unless the browser supplied a BYOK key for this session.
    """
    fallback = _heuristic_profile(answer=answer, candidate=candidate)
    try:
        if get_settings().use_stub_llm and not _has_self_intro_llm_override_key():
            return fallback
    except Exception:
        return fallback

    project_names = [
        str(p.get("name") or "").strip()
        for p in _resume_projects(candidate)
        if str(p.get("name") or "").strip()
    ][:8]
    skills = _candidate_skills(candidate)[:12]
    prompt = (
        "Extract an interview self-introduction profile.\n"
        "Return JSON with keys: summary, emphasized_projects, emphasized_skills, "
        "preferred_focus, clarification_targets, communication_signal, anchor_cards.\n"
        "anchor_cards must be an array of concise evidence cards with kind in "
        "project, responsibility, tech, difficulty, result, claim; each card has "
        "title, text, and tech_keywords.\n"
        "Only use facts supported by the self-introduction. Use resume/JD only "
        "to normalize project and skill names.\n\n"
        f"JOB_SPEC={json.dumps(job_spec or {}, ensure_ascii=False)}\n"
        f"RESUME_PROJECT_NAMES={json.dumps(project_names, ensure_ascii=False)}\n"
        f"RESUME_SKILLS={json.dumps(skills, ensure_ascii=False)}\n"
        f"SELF_INTRO={answer or ''}"
    )
    try:
        raw = call_chat(
            [
                ChatMessage("system", _SYSTEM),
                ChatMessage("user", prompt),
            ],
            json_mode=True,
            temperature=0.1,
            max_tokens=800,
            max_retries=0,
            provider_max_retries=0,
            agent_role="self_intro_parser",
        )
        data = parse_json_response(raw)
        if not isinstance(data, dict) or not data:
            return fallback
        return _clean_profile(data, fallback)
    except Exception as exc:  # pragma: no cover - provider flakes
        log.warning("self_intro_parser failed; using heuristic profile: %s", exc)
        return fallback
