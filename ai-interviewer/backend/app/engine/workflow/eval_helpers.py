"""Cross-node helpers for inspecting an ``evaluation`` dict.

These were duplicated in ``final_report.py``, ``coach.py``, and
``ReportView.tsx`` for too long. Centralising them lets the
evaluator / router / final_report all agree on "is this turn the
result of a real LLM evaluation, or a degraded fallback?" — which is
the gate condition for whether the turn should affect:

- the running dim score (``_merge_score`` in ``evaluator``);
- the per-dim attempts counter that drives coverage advance
  (``_attempts_for_dimension`` in ``routers``);
- the ``training_plan`` source surfacing on the report card.

Keeping the markers + predicate in one module means future changes
(e.g. additional fallback reason codes, new sentinel strings) only
need to land here.
"""
from __future__ import annotations

from typing import Any

# Sentinel substrings the evaluator (or its callers) plant on a
# fallback evaluation's weaknesses / rationale. Searched
# case-insensitively so the predicate stays resilient against minor
# wording drifts.
SYSTEM_FALLBACK_MARKERS: tuple[str, ...] = (
    "Evaluator LLM unavailable",
    "Evaluator LLM failed",
    "conservative fallback",
    "评估模型暂时不可用",
    "保守兜底评价",
)


def is_system_fallback_text(value: Any) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    lowered = text.lower()
    return any(marker.lower() in lowered for marker in SYSTEM_FALLBACK_MARKERS)


def is_evaluator_fallback(evaluation: dict[str, Any] | None) -> bool:
    """Return True when the evaluation came from the conservative path.

    Three independent signals — any one is enough:

    1. ``source == "fallback"`` (set by ``evaluator_agent._fallback_evaluation``)
    2. ``fallback_reason`` is truthy (set by the same helper)
    3. any ``weaknesses`` entry contains a known fallback marker
       (legacy field on older checkpoints that pre-date ``source``)
    """
    if not evaluation:
        return False
    if evaluation.get("source") == "fallback":
        return True
    if evaluation.get("fallback_reason"):
        return True
    weaknesses = evaluation.get("weaknesses") or []
    return any(is_system_fallback_text(item) for item in weaknesses)
