"""Deterministic training suggestions from soft contract gaps."""
from __future__ import annotations

import hashlib
from typing import Any, TypedDict


class SoftGapTrainingSuggestion(TypedDict, total=False):
    suggestion_id: str
    source: str
    severity: str
    check_id: str
    title: str
    description: str
    text: str
    verdict: str
    reason: str
    evidence: list[Any]
    evidence_count: int
    result_present: bool


def build_soft_gap_training_suggestions(
    contract_semantics_summary: Any,
) -> dict[str, Any]:
    """Build metadata-only training suggestions from soft contract gaps.

    This function is intentionally deterministic and does not call an LLM.  It
    only consumes the soft lanes from ``contract_semantics_summary``:
    reviewed/supporting quality gaps and adaptive-context gaps.
    """

    summary = contract_semantics_summary if isinstance(contract_semantics_summary, dict) else {}
    quality_suggestions = [
        _suggestion(item, source="reviewed_supporting")
        for item in _gap_items(summary.get("reviewed_supporting"))
        if _is_actionable_soft_gap(item)
    ]
    context_suggestions = [
        _suggestion(item, source="adaptive_context")
        for item in _gap_items(summary.get("adaptive_context"))
        if _is_actionable_soft_gap(item)
    ]
    quality_suggestions = [item for item in quality_suggestions if item is not None]
    context_suggestions = [item for item in context_suggestions if item is not None]
    counts = {
        "quality": len(quality_suggestions),
        "context": len(context_suggestions),
        "total": len(quality_suggestions) + len(context_suggestions),
    }
    return {
        "present": counts["total"] > 0,
        "source": "contract_semantics_summary",
        "quality_suggestions": quality_suggestions,
        "context_suggestions": context_suggestions,
        "counts": counts,
    }


def _gap_items(bucket_value: Any) -> list[dict[str, Any]]:
    bucket = bucket_value if isinstance(bucket_value, dict) else {}
    items = bucket.get("gap_items")
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict)]


def _is_actionable_soft_gap(item: dict[str, Any]) -> bool:
    verdict = _verdict(item)
    reason = str(item.get("reason") or "").strip().lower()
    return verdict in {"partial", "no"} or reason == "missing_result"


def _suggestion(
    item: dict[str, Any],
    *,
    source: str,
) -> SoftGapTrainingSuggestion | None:
    text = str(item.get("text") or "").strip()
    check_id = str(item.get("check_id") or "").strip()
    if not text and not check_id:
        return None

    verdict = _verdict(item)
    reason = str(item.get("reason") or "").strip().lower()
    suggestion: SoftGapTrainingSuggestion = {
        "suggestion_id": _stable_suggestion_id(
            source=source,
            check_id=check_id,
            text=text,
        ),
        "source": source,
        "severity": "supporting",
        "check_id": check_id,
        "title": _title(source, text),
        "description": _description(source, text),
        "text": text,
        "verdict": verdict,
        "reason": reason or verdict or "missing_result",
        "evidence": _evidence(item),
        "evidence_count": _evidence_count(item),
        "result_present": bool(item.get("result_present")),
    }
    return suggestion


def _title(source: str, text: str) -> str:
    prefix = (
        "Quality gap"
        if source == "reviewed_supporting"
        else "Context gap"
    )
    short = _shorten(text)
    return f"{prefix}: {short}" if short else prefix


def _description(source: str, text: str) -> str:
    if source == "reviewed_supporting":
        return (
            "Improve the answer by covering this reviewed supporting criterion: "
            f"{text}"
        ).strip()
    return (
        "Add evidence tied to the resume, JD, or question context for this "
        f"criterion: {text}"
    ).strip()


def _stable_suggestion_id(*, source: str, check_id: str, text: str) -> str:
    key = "|".join([source, check_id, text])
    digest = hashlib.sha1(
        key.encode("utf-8"),
        usedforsecurity=False,
    ).hexdigest()
    return f"soft_gap:{digest[:16]}"


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


def _shorten(text: str, limit: int = 72) -> str:
    compact = " ".join(str(text or "").split())
    if len(compact) <= limit:
        return compact
    return f"{compact[: limit - 1].rstrip()}..."
