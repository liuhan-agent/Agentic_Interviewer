"""Scoring credibility metrics for report and admin observability.

Computes a lightweight credibility assessment from interview session
data (qa_history, contract_summary, evidence_summary, verification).
No LLM calls — pure arithmetic on the already-computed session
artifacts.

Used by:
- ``final_report_node``: injects ``credibility_summary`` into the
  report payload so the frontend can surface trust signals.
- admin endpoints: rollup view reuses the same calculation to avoid
  frontend/backend drift.
"""
from __future__ import annotations

from typing import Any


def compute_credibility(
    *,
    total_turns: int,
    evaluator_fallback_count: int,
    evidence_summary: dict[str, Any] | None = None,
    contract_summary: dict[str, Any] | None = None,
    verification: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a credibility assessment dict.

    All rate fields are floats in [0.0, 1.0]; ``credibility_level``
    is one of ``"high"`` / ``"medium"`` / ``"low"``.

    Returns a stable dict shape even when input data is sparse or
    missing so downstream consumers never need conditional access.
    """
    evidence_summary = evidence_summary or {}
    contract_summary = contract_summary or {}
    verification = verification or {}

    fallback_rate = _safe_rate(evaluator_fallback_count, total_turns)

    total_quotes = int(evidence_summary.get("total_quotes", 0) or 0)
    unmatched = int(evidence_summary.get("unmatched_quotes", 0) or 0)
    span_miss_rate = _safe_rate(unmatched, total_quotes)

    total_checks = int(contract_summary.get("total_checks", 0) or 0)
    checks_no = int(contract_summary.get("checks_no", 0) or 0)
    contract_no_rate = _safe_rate(checks_no, total_checks)

    forced_refine = bool(verification.get("forced_refine", False))

    level = _assess_level(
        fallback_rate=fallback_rate,
        span_miss_rate=span_miss_rate,
        contract_no_rate=contract_no_rate,
        forced_refine=forced_refine,
        total_turns=total_turns,
    )

    return {
        "credibility_level": level,
        "fallback_rate": round(fallback_rate, 4),
        "evidence_span_miss_rate": round(span_miss_rate, 4),
        "contract_no_rate": round(contract_no_rate, 4),
        "verification_forced_refine": forced_refine,
        "total_turns": total_turns,
        "evaluator_fallback_count": evaluator_fallback_count,
    }


def _safe_rate(numerator: int, denominator: int) -> float:
    if denominator <= 0 or numerator < 0:
        return 0.0
    return min(1.0, numerator / denominator)


def _assess_level(
    *,
    fallback_rate: float,
    span_miss_rate: float,
    contract_no_rate: float,
    forced_refine: bool,
    total_turns: int,
) -> str:
    """Conservative rule-based credibility classification.

    Thresholds are intentionally strict so the first version
    over-flags rather than under-flags. Production tuning should
    be driven by observing the admin dashboard distribution.
    """
    if total_turns <= 0:
        return "low"

    low_signals = 0

    if fallback_rate > 0.5:
        low_signals += 2
    elif fallback_rate > 0.25:
        low_signals += 1

    if span_miss_rate > 0.5:
        low_signals += 2
    elif span_miss_rate > 0.3:
        low_signals += 1

    if contract_no_rate > 0.5:
        low_signals += 1

    if forced_refine:
        low_signals += 1

    if low_signals >= 3:
        return "low"
    if low_signals >= 1:
        return "medium"
    return "high"
