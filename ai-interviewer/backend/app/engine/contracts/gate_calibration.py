"""Audit-only calibration signals for reviewed/core gate strictness."""
from __future__ import annotations

from typing import Any, TypedDict


class GateCalibrationFailedItem(TypedDict, total=False):
    check_id: str
    text: str
    verdict: str
    reason: str
    result_present: bool
    evidence_count: int


class GateCalibrationSummary(TypedDict):
    present: bool
    mode: str
    source: str
    score: float | None
    score_band: str
    passed: bool | None
    gate_mode: str
    gate_status: str
    gate_enforced: bool
    high_score_gate_failed: bool
    standard_score_gate_failed: bool
    partial_only_gate_failed: bool
    hard_failure_gate_failed: bool
    signals: list[str]
    reviewed_core: dict[str, int]
    failed_check_ids: list[str]
    partial_check_ids: list[str]
    no_check_ids: list[str]
    missing_check_ids: list[str]
    failed_items: list[GateCalibrationFailedItem]
    thresholds: dict[str, float]


HIGH_SCORE_THRESHOLD = 8.0
STANDARD_SCORE_THRESHOLD = 7.0


def build_gate_calibration_summary(
    *,
    score: Any,
    passed: Any,
    contract_gate_result: Any,
    gate_enforced: Any = None,
) -> GateCalibrationSummary:
    """Build a non-decision audit summary for reviewed/core gate calibration."""

    gate = contract_gate_result if isinstance(contract_gate_result, dict) else {}
    numeric_score = _score(score)
    gate_status = str(gate.get("status") or "").strip().lower()
    eligible_count = _int(gate.get("eligible_count"))
    satisfied_count = _int(gate.get("satisfied_count"))
    partial_count = _int(gate.get("partial_count"))
    no_count = _int(gate.get("no_count"))
    missing_count = _int(gate.get("missing_count"))
    failed_items = [_failed_item(item) for item in _dict_items(gate.get("failed_items"))]

    if not failed_items and _int(gate.get("failed_count")) > 0:
        failed_items = _failed_items_from_counts(
            partial_count=partial_count,
            no_count=no_count,
            missing_count=missing_count,
        )

    failed_check_ids = _check_ids(failed_items)
    partial_check_ids = _check_ids(
        [item for item in failed_items if _reason(item) == "partial"]
    )
    no_check_ids = _check_ids([item for item in failed_items if _reason(item) == "no"])
    missing_check_ids = _check_ids(
        [item for item in failed_items if _reason(item) == "missing_result"]
    )

    failed = gate_status == "failed"
    high_score_gate_failed = bool(
        failed and numeric_score is not None and numeric_score >= HIGH_SCORE_THRESHOLD
    )
    standard_score_gate_failed = bool(
        failed
        and numeric_score is not None
        and numeric_score >= STANDARD_SCORE_THRESHOLD
    )
    partial_only_gate_failed = bool(
        failed and partial_count > 0 and no_count == 0 and missing_count == 0
    )
    hard_failure_gate_failed = bool(failed and (no_count > 0 or missing_count > 0))

    signals: list[str] = []
    if high_score_gate_failed:
        signals.append("high_score_gate_failed")
    if partial_only_gate_failed:
        signals.append("partial_only_gate_failed")
    if hard_failure_gate_failed:
        signals.append("hard_failure_gate_failed")

    return {
        "present": bool(eligible_count > 0),
        "mode": "audit",
        "source": "contract_gate_result",
        "score": numeric_score,
        "score_band": _score_band(numeric_score),
        "passed": passed if isinstance(passed, bool) else None,
        "gate_mode": str(gate.get("mode") or ""),
        "gate_status": gate_status,
        "gate_enforced": bool(gate_enforced),
        "high_score_gate_failed": high_score_gate_failed,
        "standard_score_gate_failed": standard_score_gate_failed,
        "partial_only_gate_failed": partial_only_gate_failed,
        "hard_failure_gate_failed": hard_failure_gate_failed,
        "signals": signals,
        "reviewed_core": {
            "eligible": eligible_count,
            "yes": satisfied_count,
            "partial": partial_count,
            "no": no_count,
            "missing": missing_count,
            "failed": len(failed_items),
        },
        "failed_check_ids": failed_check_ids,
        "partial_check_ids": partial_check_ids,
        "no_check_ids": no_check_ids,
        "missing_check_ids": missing_check_ids,
        "failed_items": failed_items,
        "thresholds": {
            "standard_score": STANDARD_SCORE_THRESHOLD,
            "high_score": HIGH_SCORE_THRESHOLD,
        },
    }


def _score(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None


def _score_band(score: float | None) -> str:
    if score is None:
        return "unknown"
    if score >= HIGH_SCORE_THRESHOLD:
        return "high"
    if score >= STANDARD_SCORE_THRESHOLD:
        return "standard"
    return "low"


def _int(value: Any) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _dict_items(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _failed_item(item: dict[str, Any]) -> GateCalibrationFailedItem:
    verdict = str(item.get("verdict") or "").strip().lower()
    reason = str(item.get("reason") or "").strip().lower()
    if not reason:
        reason = verdict if verdict in {"partial", "no"} else "missing_result"
    return {
        "check_id": str(item.get("check_id") or ""),
        "text": str(item.get("text") or ""),
        "verdict": verdict,
        "reason": reason,
        "result_present": bool(item.get("result_present")),
        "evidence_count": _int(item.get("evidence_count")),
    }


def _failed_items_from_counts(
    *,
    partial_count: int,
    no_count: int,
    missing_count: int,
) -> list[GateCalibrationFailedItem]:
    items: list[GateCalibrationFailedItem] = []
    items.extend({"verdict": "partial", "reason": "partial"} for _ in range(partial_count))
    items.extend({"verdict": "no", "reason": "no"} for _ in range(no_count))
    items.extend(
        {"verdict": "", "reason": "missing_result"} for _ in range(missing_count)
    )
    return items


def _reason(item: GateCalibrationFailedItem) -> str:
    reason = str(item.get("reason") or "").strip().lower()
    if reason:
        return reason
    verdict = str(item.get("verdict") or "").strip().lower()
    return verdict if verdict in {"partial", "no"} else "missing_result"


def _check_ids(items: list[GateCalibrationFailedItem]) -> list[str]:
    return [
        str(item.get("check_id") or "")
        for item in items
        if str(item.get("check_id") or "").strip()
    ]
