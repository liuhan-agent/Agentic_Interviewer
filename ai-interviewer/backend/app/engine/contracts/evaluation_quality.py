"""Quality guards for evaluator output before deterministic gates run."""
from __future__ import annotations

from typing import Any, TypedDict


QUALITY_GUARD_REASON = "empty_evidence_all_reviewed_core_partial"
QUALITY_INVALID_REASON = "quality_guard_retry_exhausted"
QUALITY_INVALID_FALLBACK_REASON = "evaluator_quality_guard_failed"
QUALITY_INVALID_GATE_WARNING = "evaluation_quality_invalid"
_MIN_RATIONALE_CHARS = 8


class EvaluationQualityWarning(TypedDict):
    evaluation_quality_warning: bool
    evaluation_quality_warning_reason: str
    evaluation_quality_warning_check_ids: list[str]


def build_evaluation_quality_warning(
    evaluation: dict[str, Any] | None,
    *,
    contract: dict[str, Any] | None,
    answer: Any,
) -> EvaluationQualityWarning | None:
    """Detect low-information reviewed/core evaluator outputs.

    This guard intentionally does not judge whether a candidate answer
    is good. It catches a narrow output-quality failure mode: a non-empty
    answer, reviewed/core checks available, every reviewed/core result
    marked ``partial``, all evidence empty, and the rationale empty or
    too short to explain the judgment.
    """

    if not str(answer or "").strip():
        return None

    reviewed_core_contract_items = [
        item for item in _dict_items((contract or {}).get("acceptance_check_items"))
        if _is_reviewed_core(item)
    ]
    if not reviewed_core_contract_items:
        return None

    result_items = [
        item for item in _dict_items((evaluation or {}).get("acceptance_check_result_items"))
        if _is_reviewed_core(item)
    ]
    if not result_items:
        return None

    if not all(_verdict(item) == "partial" for item in result_items):
        return None
    if any(_has_item_evidence(item) for item in result_items):
        return None
    if not _short_rationale((evaluation or {}).get("rationale")):
        return None

    check_ids = [
        str(item.get("check_id") or "").strip()
        for item in result_items
        if str(item.get("check_id") or "").strip()
    ]
    return {
        "evaluation_quality_warning": True,
        "evaluation_quality_warning_reason": QUALITY_GUARD_REASON,
        "evaluation_quality_warning_check_ids": check_ids,
    }


def mark_evaluation_quality_invalid(
    evaluation: dict[str, Any],
    warning: dict[str, Any],
) -> dict[str, Any]:
    """Mark retry-exhausted evaluator output as unscorable metadata.

    The transcript and raw evaluator fields are preserved for audit, but
    downstream routing/reward treat the turn like an evaluator fallback.
    """

    out = dict(evaluation or {})
    out.update(warning)
    out["evaluation_quality_invalid"] = True
    out["evaluation_quality_invalid_reason"] = QUALITY_INVALID_REASON
    out["source"] = "fallback"
    out["fallback_reason"] = QUALITY_INVALID_FALLBACK_REASON
    out["passed"] = False
    out["recommended_next"] = "next_question"
    out["recommended_next_plan"] = None
    warnings = list(out.get("system_warnings") or [])
    message = (
        "Evaluator output failed quality guard after retry; "
        "this turn is not used as a scoring signal."
    )
    if message not in warnings:
        warnings.append(message)
    out["system_warnings"] = warnings
    return out


def _dict_items(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _is_reviewed_core(item: dict[str, Any]) -> bool:
    source = str(item.get("source") or "").strip().lower()
    severity = str(item.get("severity") or "").strip().lower()
    return source == "reviewed" and severity == "core"


def _verdict(item: dict[str, Any]) -> str:
    verdict = str(item.get("verdict") or "").strip().lower()
    return verdict if verdict in {"yes", "partial", "no"} else ""


def _has_evidence(value: Any) -> bool:
    if isinstance(value, list):
        return any(str(item or "").strip() for item in value)
    if isinstance(value, str):
        return bool(value.strip())
    return bool(value)


def _has_item_evidence(item: dict[str, Any]) -> bool:
    return _has_evidence(item.get("evidence")) or _has_evidence(
        item.get("evidence_spans")
    )


def _short_rationale(value: Any) -> bool:
    return len(str(value or "").strip()) < _MIN_RATIONALE_CHARS
