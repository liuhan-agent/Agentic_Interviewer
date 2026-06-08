"""Consistency helpers for evaluator / verifier scoring semantics."""
from __future__ import annotations

from typing import Any

from app.engine.workflow.eval_helpers import is_evaluator_fallback

_HIGH_SCORE_WARNING_THRESHOLD = 9.95
_REFINE_NEXT_PLANS = {"refine", "deep_probe"}


def _finite_score(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        score = float(value)
    except (TypeError, ValueError):
        return None
    return score if score == score else None


def _verdict_of(value: Any) -> str:
    if isinstance(value, dict):
        raw = value.get("verdict")
    else:
        raw = value
    verdict = str(raw or "").strip().lower()
    return verdict if verdict in {"yes", "partial", "no"} else ""


def _coverage_of(value: Any) -> str:
    coverage = str(value or "").strip().lower()
    return coverage if coverage in {"covered", "partial", "missing"} else ""


def _append_unique(items: list[Any], value: str) -> list[Any]:
    if value and value not in items:
        items.append(value)
    return items


def _append_unique_many(items: list[Any], values: list[Any]) -> list[Any]:
    for raw in values:
        value = str(raw or "").strip()
        if value:
            _append_unique(items, value)
    return items


def _mark_normalized(out: dict[str, Any], reason: str) -> None:
    out["consistency_normalized"] = True
    out["normalization_reason"] = reason


def _is_hard_acceptance_item(item: dict[str, Any]) -> bool:
    source = str(item.get("source") or "").strip().lower()
    severity = str(item.get("severity") or "").strip().lower()
    return source == "reviewed" and severity == "core"


def _structured_acceptance_verdicts(evaluation: dict[str, Any]) -> list[str] | None:
    items = evaluation.get("acceptance_check_result_items")
    if not isinstance(items, list) or not items:
        return None

    verdicts: list[str] = []
    for raw in items:
        if not isinstance(raw, dict) or not _is_hard_acceptance_item(raw):
            continue
        verdict = _verdict_of(raw)
        if verdict:
            verdicts.append(verdict)
    return verdicts


def _legacy_acceptance_verdicts(evaluation: dict[str, Any]) -> list[str]:
    acceptance = evaluation.get("acceptance_check_results") or {}
    verdicts: list[str] = []
    if isinstance(acceptance, dict):
        for raw in acceptance.values():
            verdict = _verdict_of(raw)
            if verdict:
                verdicts.append(verdict)
    return verdicts


def _coverage_signals(evaluation: dict[str, Any]) -> tuple[list[str], list[str]]:
    structured_verdicts = _structured_acceptance_verdicts(evaluation)
    acceptance_verdicts = (
        structured_verdicts
        if structured_verdicts is not None
        else _legacy_acceptance_verdicts(evaluation)
    )

    rubric = evaluation.get("rubric_coverage") or {}
    rubric_values: list[str] = []
    if isinstance(rubric, dict):
        for raw in rubric.values():
            coverage = _coverage_of(raw)
            if coverage:
                rubric_values.append(coverage)

    return acceptance_verdicts, rubric_values


def _has_explicit_required_gap(evaluation: dict[str, Any]) -> bool:
    acceptance_verdicts, rubric_values = _coverage_signals(evaluation)
    return "no" in acceptance_verdicts or "missing" in rubric_values


def _has_complete_or_partial_required_coverage(evaluation: dict[str, Any]) -> bool:
    acceptance_verdicts, rubric_values = _coverage_signals(evaluation)
    has_signal = bool(acceptance_verdicts or rubric_values)
    if not has_signal:
        return False
    if any(v == "no" for v in acceptance_verdicts):
        return False
    if any(v == "missing" for v in rubric_values):
        return False
    return all(v in {"yes", "partial"} for v in acceptance_verdicts) and all(
        v in {"covered", "partial"} for v in rubric_values
    )


def _verification_override(
    verification: dict[str, Any] | None,
    *,
    verifier_min_override_confidence: float,
) -> tuple[bool, bool, list[Any]]:
    if not verification or not verification.get("verifier_available"):
        return False, False, []
    verdict = str(verification.get("verdict") or "pass").strip().lower()
    if verdict not in {"partial", "fail"}:
        return False, False, []
    try:
        confidence = float(verification.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
    reasons = list(verification.get("reasons_to_doubt") or [])
    return True, confidence >= verifier_min_override_confidence, reasons


def normalize_evaluation_consistency(
    evaluation: dict[str, Any],
    *,
    contract: dict[str, Any] | None,
    quality_threshold: float,
    verification: dict[str, Any] | None = None,
    verifier_min_override_confidence: float = 0.55,
) -> dict[str, Any]:
    """Return a copy with score / passed / routing fields made coherent.

    The contract is accepted for call-site symmetry and future exact
    must-cover matching. This first pass intentionally relies only on
    explicit evaluator signals to avoid false negatives from wording
    mismatches between ``must_cover`` and check labels.
    """
    del contract
    out = dict(evaluation or {})
    if is_evaluator_fallback(out):
        return out

    score = _finite_score(out.get("score"))
    hard_gap = _has_explicit_required_gap(out)
    enough_coverage = _has_complete_or_partial_required_coverage(out)
    verifier_present, verifier_high_confidence, verifier_reasons = _verification_override(
        verification,
        verifier_min_override_confidence=verifier_min_override_confidence,
    )

    if verifier_present and not verifier_high_confidence:
        soft_warnings = list(out.get("soft_warnings") or [])
        out["soft_warnings"] = _append_unique_many(soft_warnings, verifier_reasons)
        out["verifier_abstained"] = True

    if verifier_high_confidence:
        out["passed"] = False
        out["recommended_next"] = "refine"
        out["recommended_next_plan"] = "deep_probe"
        return out

    if score is not None and score < quality_threshold:
        if out.get("passed") or out.get("recommended_next") != "refine":
            _mark_normalized(out, "score_below_threshold")
        out["passed"] = False
        out["recommended_next"] = "refine"
        return out

    if hard_gap:
        if (
            out.get("passed")
            or out.get("recommended_next") != "refine"
            or (score is not None and score >= quality_threshold)
        ):
            _mark_normalized(out, "required_evidence_missing")
        out["passed"] = False
        out["recommended_next"] = "refine"
        if score is not None and score >= _HIGH_SCORE_WARNING_THRESHOLD:
            warnings = list(out.get("consistency_warnings") or [])
            out["consistency_warnings"] = _append_unique(
                warnings,
                "score is high but required evidence is missing",
            )
        return out

    if score is not None and score >= quality_threshold:
        if (
            not out.get("passed")
            or out.get("recommended_next") != "advance"
            or str(out.get("recommended_next_plan") or "") in _REFINE_NEXT_PLANS
        ):
            reason = (
                "score_and_coverage_promoted_pass"
                if enough_coverage
                else "score_without_hard_blocker_promoted_pass"
            )
            _mark_normalized(out, reason)
        out["passed"] = True
        out["recommended_next"] = "advance"
        if str(out.get("recommended_next_plan") or "") in _REFINE_NEXT_PLANS:
            out["recommended_next_plan"] = None

    return out


def sync_dimension_status(
    dimension_status: dict[str, str],
    dimension: str,
    evaluation: dict[str, Any],
) -> dict[str, str]:
    status = dict(dimension_status or {})
    if not dimension:
        return status
    if is_evaluator_fallback(evaluation):
        return status
    if evaluation.get("passed"):
        status[dimension] = "passed"
    else:
        status[dimension] = "active"
    return status
