"""Shadow follow-up intent hints from soft training suggestions."""
from __future__ import annotations

import hashlib
from typing import Any, TypedDict


class SoftFollowupHint(TypedDict, total=False):
    hint_id: str
    suggestion_id: str
    source: str
    intent: str
    check_id: str
    verdict: str
    reason: str
    text: str
    focus: str
    evidence: list[Any]
    evidence_count: int


def build_soft_followup_hints(
    soft_gap_training_suggestions: Any,
) -> dict[str, Any]:
    """Project soft training suggestions into shadow follow-up intent hints."""

    suggestions = (
        soft_gap_training_suggestions
        if isinstance(soft_gap_training_suggestions, dict)
        else {}
    )
    quality_hints = [
        _hint(item, source="reviewed_supporting", intent="probe_quality_gap")
        for item in _suggestion_items(suggestions.get("quality_suggestions"))
    ]
    context_hints = [
        _hint(item, source="adaptive_context", intent="probe_context_gap")
        for item in _suggestion_items(suggestions.get("context_suggestions"))
    ]
    quality_hints = [item for item in quality_hints if item is not None]
    context_hints = [item for item in context_hints if item is not None]
    priority_order = [
        str(item.get("hint_id"))
        for item in [*quality_hints, *context_hints]
        if item.get("hint_id")
    ]
    counts = {
        "quality": len(quality_hints),
        "context": len(context_hints),
        "total": len(priority_order),
    }
    return {
        "present": counts["total"] > 0,
        "mode": "shadow",
        "applied": False,
        "source": "soft_gap_training_suggestions",
        "quality_hints": quality_hints,
        "context_hints": context_hints,
        "priority_order": priority_order,
        "counts": counts,
    }


def _suggestion_items(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _hint(
    item: dict[str, Any],
    *,
    source: str,
    intent: str,
) -> SoftFollowupHint | None:
    text = str(item.get("text") or item.get("description") or "").strip()
    suggestion_id = str(item.get("suggestion_id") or "").strip()
    check_id = str(item.get("check_id") or "").strip()
    if not text and not suggestion_id and not check_id:
        return None
    hint: SoftFollowupHint = {
        "hint_id": _stable_hint_id(
            source=source,
            suggestion_id=suggestion_id,
            check_id=check_id,
            text=text,
        ),
        "suggestion_id": suggestion_id,
        "source": source,
        "intent": intent,
        "check_id": check_id,
        "verdict": _verdict(item),
        "reason": str(item.get("reason") or "").strip().lower(),
        "text": text,
        "focus": _focus(intent=intent, text=text),
        "evidence": _evidence(item),
        "evidence_count": _evidence_count(item),
    }
    return hint


def _stable_hint_id(
    *,
    source: str,
    suggestion_id: str,
    check_id: str,
    text: str,
) -> str:
    key = "|".join([source, suggestion_id, check_id, text])
    digest = hashlib.sha1(
        key.encode("utf-8"),
        usedforsecurity=False,
    ).hexdigest()
    return f"soft_followup:{digest[:16]}"


def _focus(*, intent: str, text: str) -> str:
    if intent == "probe_quality_gap":
        return f"Probe quality gap without treating it as a hard gate: {text}".strip()
    return f"Probe context gap without overriding reviewed core: {text}".strip()


def _verdict(item: dict[str, Any]) -> str:
    verdict = str(item.get("verdict") or "").strip().lower()
    return verdict if verdict in {"yes", "partial", "no"} else ""


def _evidence(item: dict[str, Any]) -> list[Any]:
    evidence = item.get("evidence")
    return list(evidence) if isinstance(evidence, list) else []


def _evidence_count(item: dict[str, Any]) -> int:
    if isinstance(item.get("evidence_count"), int):
        return max(0, int(item.get("evidence_count") or 0))
    return len(_evidence(item))
