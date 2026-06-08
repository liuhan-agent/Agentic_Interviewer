"""Source-aware summaries for structured acceptance-check results."""
from __future__ import annotations

import copy
from typing import Any, TypedDict


class AcceptanceGapItem(TypedDict, total=False):
    check_id: str
    text: str
    source: str
    severity: str
    verdict: str
    result_present: bool
    reason: str
    evidence: list[Any]
    evidence_count: int


class AcceptanceBucketSummary(TypedDict):
    total: int
    yes: int
    partial: int
    no: int
    missing: int


class GapBucketSummary(AcceptanceBucketSummary, total=False):
    failed_items: list[AcceptanceGapItem]
    gap_items: list[AcceptanceGapItem]


def build_contract_semantics_summary(
    acceptance_check_result_items: Any,
) -> dict[str, Any]:
    """Summarise contract semantics without changing scoring decisions."""

    summary: dict[str, Any] = {
        "reviewed_core": _bucket(failed_items=[]),
        "reviewed_supporting": _bucket(gap_items=[]),
        "adaptive_context": _bucket(gap_items=[]),
        "evaluator_extra": {"total": 0, "items": []},
        "hard_gap_count": 0,
        "soft_quality_gap_count": 0,
        "context_gap_count": 0,
        "semantics": {
            "reviewed_core": "hard_gate",
            "reviewed_supporting": "quality_signal",
            "adaptive_context": "context_signal",
            "evaluator_extra": "observation_only",
        },
    }

    for item in _dict_items(acceptance_check_result_items):
        source = _source(item)
        severity = _severity(item)
        if source == "reviewed" and severity == "core":
            _record_verdict(summary["reviewed_core"], item)
            reason = _gap_reason(item)
            if reason is not None:
                gap = _gap_item(item, reason=reason)
                summary["reviewed_core"]["failed_items"].append(gap)
                summary["hard_gap_count"] += 1
            continue
        if source == "reviewed" and severity == "supporting":
            _record_verdict(summary["reviewed_supporting"], item)
            reason = _gap_reason(item)
            if reason is not None:
                gap = _gap_item(item, reason=reason)
                summary["reviewed_supporting"]["gap_items"].append(gap)
                summary["soft_quality_gap_count"] += 1
            continue
        if source == "adaptive_context":
            _record_verdict(summary["adaptive_context"], item)
            reason = _gap_reason(item)
            if reason is not None:
                gap = _gap_item(item, reason=reason)
                summary["adaptive_context"]["gap_items"].append(gap)
                summary["context_gap_count"] += 1
            continue
        if source == "evaluator_extra":
            summary["evaluator_extra"]["total"] += 1
            summary["evaluator_extra"]["items"].append(_observation_item(item))

    return summary


def _bucket(**extra: Any) -> dict[str, Any]:
    out: dict[str, Any] = {
        "total": 0,
        "yes": 0,
        "partial": 0,
        "no": 0,
        "missing": 0,
    }
    out.update(extra)
    return out


def _record_verdict(bucket: dict[str, Any], item: dict[str, Any]) -> None:
    bucket["total"] += 1
    verdict = _verdict(item)
    if _is_missing(item, verdict):
        bucket["missing"] += 1
    elif verdict == "yes":
        bucket["yes"] += 1
    elif verdict == "partial":
        bucket["partial"] += 1
    elif verdict == "no":
        bucket["no"] += 1
    else:
        bucket["missing"] += 1


def _gap_reason(item: dict[str, Any]) -> str | None:
    verdict = _verdict(item)
    if _is_missing(item, verdict):
        return "missing_result"
    if verdict in {"partial", "no"}:
        return verdict
    return None


def _gap_item(item: dict[str, Any], *, reason: str) -> AcceptanceGapItem:
    payload: AcceptanceGapItem = {
        "check_id": str(item.get("check_id") or ""),
        "text": str(item.get("text") or ""),
        "source": _source(item),
        "severity": _severity(item),
        "verdict": _verdict(item),
        "result_present": bool(item.get("result_present")),
        "reason": reason,
        "evidence_count": _evidence_count(item),
    }
    evidence = item.get("evidence")
    if isinstance(evidence, list) and evidence:
        payload["evidence"] = copy.deepcopy(evidence)
    return payload


def _observation_item(item: dict[str, Any]) -> dict[str, Any]:
    payload = _gap_item(item, reason=_gap_reason(item) or "observed")
    evidence = item.get("evidence")
    if isinstance(evidence, list) and evidence:
        payload["evidence"] = copy.deepcopy(evidence)
    return payload


def _dict_items(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _source(item: dict[str, Any]) -> str:
    return str(item.get("source") or "").strip().lower()


def _severity(item: dict[str, Any]) -> str:
    return str(item.get("severity") or "supporting").strip().lower()


def _verdict(item: dict[str, Any]) -> str:
    verdict = str(item.get("verdict") or "").strip().lower()
    return verdict if verdict in {"yes", "partial", "no"} else ""


def _is_missing(item: dict[str, Any], verdict: str) -> bool:
    return not bool(item.get("result_present")) or not verdict


def _evidence_count(item: dict[str, Any]) -> int:
    evidence = item.get("evidence")
    return len(evidence) if isinstance(evidence, list) else 0
