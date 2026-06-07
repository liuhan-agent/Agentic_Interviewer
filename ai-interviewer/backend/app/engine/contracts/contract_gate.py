"""Deterministic gates over structured acceptance-check results."""
from __future__ import annotations

import copy
from typing import Any, TypedDict


class ContractGateFailedItem(TypedDict, total=False):
    check_id: str
    text: str
    source: str
    severity: str
    verdict: str
    result_present: bool
    reason: str
    evidence_count: int


class ContractGateResult(TypedDict):
    gate_id: str
    mode: str
    status: str
    would_pass: bool | None
    eligible_count: int
    satisfied_count: int
    failed_count: int
    partial_count: int
    no_count: int
    missing_count: int
    failed_items: list[ContractGateFailedItem]
    scope: dict[str, Any]
    warnings: list[str]


GATE_ID = "reviewed_core_acceptance"
GATE_MODE = "shadow"
GATE_MODES = {"shadow", "enforce"}
INVALID_MODE_FALLBACK_WARNING = "invalid_contract_gate_mode_fallback"
GATE_SCOPE = {
    "sources": ["reviewed"],
    "severities": ["core"],
    "partial_policy": "fail",
}


def build_contract_gate_result(
    acceptance_check_result_items: Any,
    *,
    mode: str = GATE_MODE,
    warnings: list[str] | None = None,
) -> ContractGateResult:
    """Evaluate the reviewed/core gate without mutating scoring state."""

    eligible_items = [
        item
        for item in _dict_items(acceptance_check_result_items)
        if _is_reviewed_core(item)
    ]
    if not eligible_items:
        return _result(
            status="not_applicable",
            would_pass=None,
            eligible_count=0,
            satisfied_count=0,
            failed_items=[],
            partial_count=0,
            no_count=0,
            missing_count=0,
            mode=mode,
            warnings=warnings,
        )

    satisfied_count = 0
    partial_count = 0
    no_count = 0
    missing_count = 0
    failed_items: list[ContractGateFailedItem] = []

    for item in eligible_items:
        verdict = str(item.get("verdict") or "").strip().lower()
        result_present = bool(item.get("result_present"))
        if result_present and verdict == "yes":
            satisfied_count += 1
            continue
        reason = _failure_reason(verdict=verdict, result_present=result_present)
        if reason == "partial":
            partial_count += 1
        elif reason == "no":
            no_count += 1
        else:
            missing_count += 1
        failed_items.append(_failed_item(item, verdict=verdict, reason=reason))

    return _result(
        status="failed" if failed_items else "passed",
        would_pass=not failed_items,
        eligible_count=len(eligible_items),
        satisfied_count=satisfied_count,
        failed_items=failed_items,
        partial_count=partial_count,
        no_count=no_count,
        missing_count=missing_count,
        mode=mode,
        warnings=warnings,
    )


def resolve_contract_gate_mode(
    *,
    runtime_config: dict[str, Any] | None,
    settings: Any,
) -> tuple[str, list[str]]:
    """Resolve the gate mode, preferring runtime config over settings."""

    raw = None
    if isinstance(runtime_config, dict):
        raw = runtime_config.get("contract_gate_mode")
    if raw is None:
        raw = getattr(settings, "contract_gate_mode", GATE_MODE)

    mode = str(raw or GATE_MODE).strip().lower()
    if mode in GATE_MODES:
        return mode, []
    return GATE_MODE, [INVALID_MODE_FALLBACK_WARNING]


def apply_contract_gate_enforcement(
    evaluation: dict[str, Any],
    gate_result: dict[str, Any] | None,
    *,
    mode: str,
) -> dict[str, Any]:
    """Force refine when enforce mode sees failed reviewed/core checks."""

    if mode != "enforce":
        return dict(evaluation or {})
    if not isinstance(gate_result, dict) or gate_result.get("status") != "failed":
        return dict(evaluation or {})

    failed_items = _dict_items(gate_result.get("failed_items"))
    if not failed_items:
        return dict(evaluation or {})

    out = dict(evaluation or {})
    out["passed"] = False
    out["recommended_next"] = "refine"
    out["recommended_next_plan"] = "deep_probe"
    out["contract_gate_enforced"] = True
    out["contract_gate_enforcement_reason"] = "reviewed_core_failed"
    out["contract_gate_failed_count"] = len(failed_items)
    out["contract_gate_failed_check_ids"] = [
        str(item.get("check_id") or "")
        for item in failed_items
        if str(item.get("check_id") or "").strip()
    ]
    out["weaknesses"] = _append_unique_many(
        list(out.get("weaknesses") or []),
        [_weakness_for_failed_item(item) for item in failed_items],
    )
    out["failure_categories"] = _append_unique_many(
        list(out.get("failure_categories") or []),
        ["contract_gate_reviewed_core_failed"],
    )
    return out


def _result(
    *,
    status: str,
    would_pass: bool | None,
    eligible_count: int,
    satisfied_count: int,
    failed_items: list[ContractGateFailedItem],
    partial_count: int,
    no_count: int,
    missing_count: int,
    mode: str,
    warnings: list[str] | None,
) -> ContractGateResult:
    return {
        "gate_id": GATE_ID,
        "mode": mode if mode in GATE_MODES else GATE_MODE,
        "status": status,
        "would_pass": would_pass,
        "eligible_count": eligible_count,
        "satisfied_count": satisfied_count,
        "failed_count": len(failed_items),
        "partial_count": partial_count,
        "no_count": no_count,
        "missing_count": missing_count,
        "failed_items": failed_items,
        "scope": copy.deepcopy(GATE_SCOPE),
        "warnings": list(warnings or []),
    }


def _dict_items(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _is_reviewed_core(item: dict[str, Any]) -> bool:
    source = str(item.get("source") or "").strip().lower()
    severity = str(item.get("severity") or "").strip().lower()
    return source == "reviewed" and severity == "core"


def _failure_reason(*, verdict: str, result_present: bool) -> str:
    if not result_present or not verdict:
        return "missing_result"
    if verdict == "partial":
        return "partial"
    if verdict == "no":
        return "no"
    return "missing_result"


def _failed_item(
    item: dict[str, Any],
    *,
    verdict: str,
    reason: str,
) -> ContractGateFailedItem:
    return {
        "check_id": str(item.get("check_id") or ""),
        "text": str(item.get("text") or ""),
        "source": str(item.get("source") or ""),
        "severity": str(item.get("severity") or ""),
        "verdict": verdict,
        "result_present": bool(item.get("result_present")),
        "reason": reason,
        "evidence_count": _evidence_count(item),
    }


def _evidence_count(item: dict[str, Any]) -> int:
    evidence = item.get("evidence")
    return len(evidence) if isinstance(evidence, list) else 0


def _weakness_for_failed_item(item: dict[str, Any]) -> str:
    text = str(item.get("text") or "").strip()
    reason = str(item.get("reason") or "missing_result").strip()
    if text:
        return f"Reviewed core acceptance failed ({reason}): {text}"
    check_id = str(item.get("check_id") or "").strip()
    if check_id:
        return f"Reviewed core acceptance failed ({reason}): {check_id}"
    return f"Reviewed core acceptance failed ({reason})"


def _append_unique_many(items: list[Any], values: list[Any]) -> list[Any]:
    for raw in values:
        value = str(raw or "").strip()
        if value and value not in items:
            items.append(value)
    return items
