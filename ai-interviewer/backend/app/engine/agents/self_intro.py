"""Parse the candidate's opening self-introduction into lightweight context."""
from __future__ import annotations

import json
import re
from typing import Any

from app.core.logging import get_logger
from app.core.settings import get_settings
from app.services.resume_chunker import extract_tech_keywords

from .llm_client import ChatMessage, call_chat, parse_json_response

log = get_logger(__name__)

_SYSTEM = (
    "You turn a candidate's interview self-introduction into structured "
    "context for an interview question generator. Respond only JSON with "
    "keys: summary, emphasized_projects, emphasized_skills, preferred_focus, "
    "clarification_targets, communication_signal, anchor_cards. Each "
    "anchor_card must be one concrete follow-up target from the candidate's "
    "self-introduction, not a summary of the whole answer."
)

ALLOWED_SELF_INTRO_CARD_KINDS = {
    "project",
    "responsibility",
    "tech",
    "difficulty",
    "result",
    "claim",
}

_LONG_SELF_INTRO_CHARS = 800
_GENERIC_CARD_MARKERS = (
    "丰富项目经验",
    "丰富的项目经验",
    "多个后端项目",
    "完成了自我介绍",
    "有项目经验",
    "rich project experience",
    "many backend projects",
    "completed the opening self-introduction",
)
_RESPONSIBILITY_MARKERS = (
    "负责",
    "主导",
    "设计",
    "实现",
    "搭建",
    "优化",
    "owner",
    "owned",
    "led",
    "designed",
    "implemented",
    "built",
    "optimized",
)
_DIFFICULTY_MARKERS = (
    "难点",
    "挑战",
    "瓶颈",
    "一致性",
    "高并发",
    "权限",
    "隔离",
    "故障",
    "定位",
    "补偿",
    "幂等",
    "difficulty",
    "challenge",
    "bottleneck",
    "consistency",
    "concurrency",
    "isolation",
    "idempotent",
)
_RESULT_MARKERS = (
    "提升",
    "降低",
    "减少",
    "优化到",
    "命中率",
    "准确率",
    "倍",
    "%",
    "qps",
    "latency",
    "improved",
    "reduced",
    "increased",
)
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[。！？.!?])\s*|[；;]\s*")


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


def _self_intro_max_cards() -> int:
    return int(getattr(get_settings(), "session_anchor_self_intro_max_cards", 8) or 8)


def _self_intro_card_max_chars() -> int:
    return int(
        getattr(get_settings(), "session_anchor_self_intro_card_max_chars", 500)
        or 500
    )


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

    profile = {
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
                "source": "fallback",
            }
        ],
        "parse_status": "heuristic" if text else "fallback",
    }
    supplement = _build_self_intro_supplement_cards(
        answer=text,
        candidate=candidate,
        profile=profile,
    )
    profile["anchor_cards"] = _merge_anchor_cards(
        supplement,
        _source_cards(profile["anchor_cards"], "fallback"),
    )
    return profile


def _clean_anchor_cards(
    raw: Any,
    fallback: dict[str, Any] | None = None,
    *,
    source: str = "llm",
) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    seen: set[str] = set()
    items = raw if isinstance(raw, list) else []
    for item in items:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or "").strip()
        text = re.sub(r"\s+", " ", str(item.get("text") or "").strip())
        if (
            kind not in ALLOWED_SELF_INTRO_CARD_KINDS
            or not text
            or not _is_high_value_anchor_text(text)
        ):
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        keywords = _as_text_list(item.get("tech_keywords"), limit=10)
        if not keywords:
            keywords = extract_tech_keywords(text)
        cards.append(
            {
                "kind": kind,
                "title": str(item.get("title") or kind).strip()[:80],
                "text": text[:_self_intro_card_max_chars()],
                "tech_keywords": keywords[:10],
                "source": str(item.get("source") or source or "llm"),
            }
        )
        if len(cards) >= _self_intro_max_cards():
            break
    if cards:
        return cards
    fallback_cards = (fallback or {}).get("anchor_cards")
    return _source_cards(fallback_cards, "fallback") if isinstance(fallback_cards, list) else []


def _clean_profile(
    raw: dict[str, Any],
    fallback: dict[str, Any],
    *,
    answer: str = "",
    candidate: dict[str, Any] | None = None,
) -> dict[str, Any]:
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
        "parse_status": "llm",
    }
    llm_cards = _clean_anchor_cards(raw.get("anchor_cards"), source="llm")
    supplement_cards = _build_self_intro_supplement_cards(
        answer=answer,
        candidate=candidate or {},
        profile=cleaned,
    )
    fallback_cards = _clean_anchor_cards(fallback.get("anchor_cards"), source="fallback")
    merged_cards = _merge_anchor_cards(
        llm_cards,
        supplement_cards,
    )
    cleaned["anchor_cards"] = merged_cards or fallback_cards
    if not cleaned["summary"]:
        cleaned["summary"] = fallback.get("summary") or "候选人完成了开场自我介绍。"
        cleaned["parse_status"] = fallback.get("parse_status") or "fallback"
    if not cleaned["anchor_cards"]:
        cleaned["anchor_cards"] = _source_cards(
            fallback.get("anchor_cards"),
            "fallback",
        )
    return cleaned


def _is_high_value_anchor_text(text: str) -> bool:
    value = " ".join(str(text or "").split())
    if not value:
        return False
    lower = value.lower()
    if any(marker.lower() in lower for marker in _GENERIC_CARD_MARKERS):
        return False
    if len(value) < 10 and not extract_tech_keywords(value):
        return False
    return True


def _source_cards(cards: Any, source: str) -> list[dict[str, Any]]:
    items = cards if isinstance(cards, list) else []
    sourced: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        card = dict(item)
        card["source"] = str(card.get("source") or source)
        sourced.append(card)
    return sourced


def _merge_anchor_cards(*groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    limit = _self_intro_max_cards()
    for group in groups:
        for card in group:
            if not isinstance(card, dict):
                continue
            kind = str(card.get("kind") or "claim").strip()
            text = " ".join(str(card.get("text") or "").split())
            if kind not in ALLOWED_SELF_INTRO_CARD_KINDS or not _is_high_value_anchor_text(text):
                continue
            title = str(card.get("title") or kind).strip()[:80] or kind
            keywords = _as_text_list(card.get("tech_keywords"), limit=10)
            if not keywords:
                keywords = extract_tech_keywords(text)
            key = (kind, title.lower(), text.lower())
            if key in seen:
                continue
            seen.add(key)
            merged.append(
                {
                    "kind": kind,
                    "title": title,
                    "text": text[
                        : _self_intro_card_max_chars()
                    ],
                    "tech_keywords": keywords[:10],
                    "source": str(card.get("source") or "supplement"),
                }
            )
            if len(merged) >= limit:
                return merged
    return merged


def _build_self_intro_supplement_cards(
    *,
    answer: str,
    candidate: dict[str, Any],
    profile: dict[str, Any],
) -> list[dict[str, Any]]:
    text = re.sub(r"\s+", " ", str(answer or "").strip())
    if not text:
        return []
    segments = _self_intro_segments(text)
    cards: list[dict[str, Any]] = []
    cards.extend(_project_supplement_cards(text, segments, candidate))
    cards.extend(_tech_supplement_cards(segments, candidate, profile))
    cards.extend(_marker_supplement_cards(segments, "result", "Self-intro result", _RESULT_MARKERS))
    cards.extend(
        _marker_supplement_cards(
            segments,
            "difficulty",
            "Self-intro difficulty",
            _DIFFICULTY_MARKERS,
        )
    )
    cards.extend(
        _marker_supplement_cards(
            segments,
            "responsibility",
            "Self-intro responsibility",
            _RESPONSIBILITY_MARKERS,
        )
    )
    return _merge_anchor_cards(cards)


def _self_intro_segments(text: str) -> list[str]:
    normalized = re.sub(
        r"(首先|第一|其次|第二|另外|然后|最后|同时|还有|first|second|then|finally)",
        r"。\1",
        text,
        flags=re.IGNORECASE,
    )
    raw_segments = [
        segment.strip(" ，,。")
        for segment in _SENTENCE_SPLIT_RE.split(normalized)
        if segment and segment.strip(" ，,。")
    ]
    if len(text) < _LONG_SELF_INTRO_CHARS:
        return raw_segments[:12] or [text]
    scored = sorted(raw_segments, key=_segment_signal_score, reverse=True)
    return scored[:16] or [text[:500]]


def _segment_signal_score(segment: str) -> int:
    score = len(extract_tech_keywords(segment)) * 3
    score += sum(2 for marker in _RESULT_MARKERS if marker.lower() in segment.lower())
    score += sum(2 for marker in _DIFFICULTY_MARKERS if marker.lower() in segment.lower())
    score += sum(1 for marker in _RESPONSIBILITY_MARKERS if marker.lower() in segment.lower())
    if re.search(r"\d", segment):
        score += 2
    return score


def _project_supplement_cards(
    text: str,
    segments: list[str],
    candidate: dict[str, Any],
) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    for project in _resume_projects(candidate):
        name = str(project.get("name") or "").strip()
        if not name or not _contains(text, name):
            continue
        evidence = _best_segment_for_terms(segments, [name]) or name
        skills = _as_text_list(project.get("tech_stack"), limit=8)
        cards.append(
            {
                "kind": "project",
                "title": name[:80],
                "text": _contextual_text(name, skills, evidence),
                "tech_keywords": extract_tech_keywords(evidence) or skills,
                "source": "supplement",
            }
        )
    return cards


def _tech_supplement_cards(
    segments: list[str],
    candidate: dict[str, Any],
    profile: dict[str, Any],
) -> list[dict[str, Any]]:
    skill_candidates = _as_text_list(
        [
            *_candidate_skills(candidate),
            *((profile or {}).get("emphasized_skills") or []),
        ],
        limit=16,
    )
    hits = [skill for skill in skill_candidates if any(_contains(s, skill) for s in segments)]
    if not hits:
        hits = list({kw for segment in segments for kw in extract_tech_keywords(segment)})
    cards: list[dict[str, Any]] = []
    for skill in hits[:4]:
        evidence = _best_segment_for_terms(segments, [skill]) or skill
        cards.append(
            {
                "kind": "tech",
                "title": skill[:80],
                "text": evidence,
                "tech_keywords": extract_tech_keywords(evidence) or [skill],
                "source": "supplement",
            }
        )
    return cards


def _marker_supplement_cards(
    segments: list[str],
    kind: str,
    fallback_title: str,
    markers: tuple[str, ...],
) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    for segment in segments:
        lower = segment.lower()
        if not any(marker.lower() in lower for marker in markers):
            continue
        cards.append(
            {
                "kind": kind,
                "title": _heading_from_text(segment) or fallback_title,
                "text": segment,
                "tech_keywords": extract_tech_keywords(segment),
                "source": "supplement",
            }
        )
        if len(cards) >= 2:
            break
    return cards


def _best_segment_for_terms(segments: list[str], terms: list[str]) -> str:
    for segment in segments:
        if any(_contains(segment, term) for term in terms):
            return segment
    return ""


def _contextual_text(project_name: str, skills: list[str], evidence: str) -> str:
    parts = [f"Project: {project_name}"]
    if skills:
        parts.append(f"Tech: {', '.join(skills[:8])}")
    if evidence and evidence != project_name:
        parts.append(f"Evidence: {evidence}")
    return " | ".join(parts)


def _heading_from_text(text: str) -> str:
    return " ".join(str(text or "").split())[:80]


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
        "anchor_cards must be concrete follow-up targets, not a summary of the "
        "whole answer. Normal answers should return 3-6 cards; long answers can "
        "return up to 8 cards. Each card must contain exactly one supported "
        "fact with kind in project, responsibility, tech, difficulty, result, "
        "claim; each card has title, text, and tech_keywords. Prefer cards "
        "about projects, responsibilities, technology, hard problems, and "
        "measurable outcomes. Include enough context in card text, such as the "
        "project name plus the technology/responsibility/result. Only use facts "
        "supported by SELF_INTRO. Use resume/JD only to normalize project and "
        "skill names; never add resume facts that the candidate did not mention.\n\n"
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
        return _clean_profile(
            data,
            fallback,
            answer=answer,
            candidate=candidate,
        )
    except Exception as exc:  # pragma: no cover - provider flakes
        log.warning("self_intro_parser failed; using heuristic profile: %s", exc)
        return fallback
