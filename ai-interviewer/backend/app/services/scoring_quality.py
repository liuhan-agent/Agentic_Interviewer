"""Scoring quality aggregation for final reports and admin rollups.

This module keeps report-side scoring quality signals in one place:
contract verdict distribution, evidence-span health, credibility
inputs, and candidate-facing risk flags. It is deliberately
deterministic and reads only already-produced workflow artifacts.
"""
from __future__ import annotations

import re
from typing import Any

from app.engine.workflow.eval_helpers import is_system_fallback_text
from app.services.scoring_credibility import compute_credibility


_GATE_ENFORCEMENT_RISK_RE = re.compile(
    r"^\s*Reviewed core acceptance failed(?:\s*\([^)]+\))?:?\s*(.*)$",
    re.IGNORECASE,
)


def verdict_of(value: Any) -> str:
    """Extract a normalized acceptance verdict from legacy or dict shape."""
    if isinstance(value, dict):
        verdict = str(value.get("verdict", "")).strip().lower()
    else:
        verdict = str(value).strip().lower()
    return verdict if verdict in {"yes", "partial", "no"} else "no"


def acceptance_counts(checks: dict[str, Any] | None) -> dict[str, int]:
    """Count yes/partial/no verdicts across mixed acceptance shapes."""
    counts = {"yes": 0, "partial": 0, "no": 0, "total": 0}
    if not isinstance(checks, dict):
        return counts
    for raw in checks.values():
        counts[verdict_of(raw)] += 1
        counts["total"] += 1
    return counts


def merge_contract_checks(
    existing: dict[str, str],
    incoming: dict[str, Any] | None,
) -> dict[str, str]:
    """Merge check results by text, keeping only latest verdict strings."""
    merged = dict(existing)
    if not isinstance(incoming, dict):
        return merged
    for check, raw_value in incoming.items():
        if not check:
            continue
        merged[str(check)] = verdict_of(raw_value)
    return merged


def evidence_summary(qa_history: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate evidence-span match health for the final report."""
    total = 0
    exact = 0
    fuzzy = 0
    unmatched = 0
    for qa in qa_history:
        evaluation = _as_dict(qa.get("evaluation") if isinstance(qa, dict) else None)
        checks = _as_dict(evaluation.get("acceptance_check_results"))
        for raw in checks.values():
            if not isinstance(raw, dict):
                continue
            spans = raw.get("evidence_spans") or []
            if not isinstance(spans, list):
                continue
            for span in spans:
                if not isinstance(span, dict):
                    continue
                total += 1
                match = str(span.get("match") or "").strip().lower()
                if match == "exact":
                    exact += 1
                elif match == "fuzzy":
                    fuzzy += 1
                else:
                    unmatched += 1
    matched = exact + fuzzy
    return {
        "total_quotes": total,
        "matched_quotes": matched,
        "unmatched_quotes": unmatched,
        "exact_matches": exact,
        "fuzzy_matches": fuzzy,
        "match_rate": round(matched / total, 3) if total else 0.0,
    }


def acceptance_evidence_quality(checks: dict[str, Any] | None) -> dict[str, int]:
    """Count admin evidence-quality metrics across acceptance checks."""
    quality = {
        "total_acceptance_checks": 0,
        "yes_checks": 0,
        "unsupported_yes_checks": 0,
        "evidence_span_total": 0,
        "evidence_span_none_count": 0,
        "evidence_quote_total": 0,
    }
    if not isinstance(checks, dict):
        return quality

    for raw in checks.values():
        quality["total_acceptance_checks"] += 1
        verdict = verdict_of(raw)
        if verdict == "yes":
            quality["yes_checks"] += 1

        evidence = raw.get("evidence") if isinstance(raw, dict) else None
        quality["evidence_quote_total"] += _evidence_quote_count(evidence)
        if verdict == "yes" and not _is_non_empty_string_list(evidence):
            quality["unsupported_yes_checks"] += 1

        spans = raw.get("evidence_spans") if isinstance(raw, dict) else None
        if not isinstance(spans, list):
            continue
        for span in spans:
            if not isinstance(span, dict):
                continue
            quality["evidence_span_total"] += 1
            match = str(span.get("match") or "").strip().lower()
            if match == "none":
                quality["evidence_span_none_count"] += 1

    return quality


def build_scoring_quality_summary(
    *,
    qa_history: list[dict[str, Any]],
    verification: dict[str, Any] | None,
    evaluator_fallback_count: int,
) -> dict[str, Any]:
    """Build the report quality fields without changing their shape."""
    merged_contract_checks: dict[str, str] = {}
    for qa in qa_history:
        evaluation = _as_dict(qa.get("evaluation") if isinstance(qa, dict) else None)
        checks = _as_dict(evaluation.get("acceptance_check_results"))
        merged_contract_checks = merge_contract_checks(merged_contract_checks, checks)

    contract_counts = acceptance_counts(merged_contract_checks)
    contract_summary = {
        "total_checks": contract_counts["total"],
        "checks_yes": contract_counts["yes"],
        "checks_partial": contract_counts["partial"],
        "checks_no": contract_counts["no"],
    }
    ev_summary = evidence_summary(qa_history)
    normalized_verification = normalize_verification(verification, qa_history)
    credibility_summary = compute_credibility(
        total_turns=len(qa_history),
        evaluator_fallback_count=evaluator_fallback_count,
        evidence_summary=ev_summary,
        contract_summary=contract_summary,
        verification=normalized_verification,
    )

    return {
        "contract_summary": contract_summary,
        "evidence_summary": ev_summary,
        "credibility_summary": credibility_summary,
        "risk_flags": risk_flags_from_history(qa_history, normalized_verification),
    }


def normalize_verification(
    verification: dict[str, Any] | None,
    qa_history: list[dict[str, Any]],
) -> dict[str, Any]:
    """Normalize forced-refine aliases into the legacy key."""
    normalized = dict(verification or {})
    if verification_forced_refine(verification, qa_history):
        normalized["forced_refine"] = True
        normalized["verifier_forced_refine"] = True
    return normalized


def verification_forced_refine(
    verification: dict[str, Any] | None,
    qa_history: list[dict[str, Any]] | None = None,
) -> bool:
    """Return true when verifier forced refine was observed anywhere."""
    verification = _as_dict(verification)
    if _is_true(verification.get("forced_refine")):
        return True
    if _is_true(verification.get("verifier_forced_refine")):
        return True

    for qa in qa_history or []:
        evaluation = _as_dict(qa.get("evaluation") if isinstance(qa, dict) else None)
        if _is_true(evaluation.get("verifier_forced_refine")):
            return True
    return False


def risk_flags_from_history(
    qa_history: list[dict[str, Any]],
    verification: dict[str, Any] | None,
) -> list[Any]:
    """Collect report risk flags using the existing final-report semantics."""
    risk_flags: list[Any] = []
    for qa in qa_history:
        evaluation = _as_dict(qa.get("evaluation") if isinstance(qa, dict) else None)
        if not evaluation.get("passed"):
            risk_flags.extend(_candidate_weaknesses(evaluation))
        risk_flags.extend(
            item
            for item in (evaluation.get("soft_warnings") or [])
            if not is_system_fallback_text(item)
        )

    verification = _as_dict(verification)
    raw_flags = list(verification.get("reasons_to_doubt") or []) + risk_flags
    return _dedupe([_candidate_readable_risk_flag(item) for item in raw_flags])[:8]


def _candidate_weaknesses(evaluation: dict[str, Any]) -> list[Any]:
    return [
        item
        for item in (evaluation.get("weaknesses") or [])
        if not is_system_fallback_text(item)
    ]


def _candidate_readable_risk_flag(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text:
        return text
    match = _GATE_ENFORCEMENT_RISK_RE.match(text)
    if not match:
        return text
    detail = (match.group(1) or "").strip()
    if detail:
        return f"核心判定条款未满足：{detail}"
    return "核心判定条款未满足：需要补充核心判定条款的证据。"


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _is_true(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes"}
    return bool(value)


def _is_non_empty_string_list(value: Any) -> bool:
    return (
        isinstance(value, list)
        and bool(value)
        and all(isinstance(item, str) and bool(item.strip()) for item in value)
    )


def _evidence_quote_count(value: Any) -> int:
    if not isinstance(value, list):
        return 0
    return sum(1 for item in value if isinstance(item, str) and item.strip())


def _dedupe(items: list[Any]) -> list[Any]:
    seen: set[str] = set()
    out: list[Any] = []
    for item in items:
        if item in (None, ""):
            continue
        key = str(item)
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out
