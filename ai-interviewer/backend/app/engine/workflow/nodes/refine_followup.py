"""Refine-followup node: mark the dimension for another pass.

The node itself does no LLM call; it just performs the minimal state
update so the router re-enters ``director_sample`` / ``ask_question``
with a fresh context. Keeping logic thin here mirrors ACO's approach
of putting routing decisions in routers rather than nodes.

P0 additions
------------
In addition to ``refine_mode=True``, the node now writes two more
fields that drive the next ``ask_question_node`` plan resolution:

- ``pending_plan_template``: taken from
  ``evaluation.recommended_next_plan`` when the evaluator made a
  concrete recommendation; otherwise defaults to ``"deep_probe"``
  because the evaluator implicitly said "not passed".
- ``pending_contract_hints``: a small bag of structured hints the
  generator can consume, most importantly ``must_address`` (the
  weaknesses list) so the next draft question homes in on what the
  previous answer missed.

Both fields are consumed and cleared by the next round
(``director_sample_node`` clears ``pending_plan_template``;
``ask_question_node`` clears ``pending_contract_hints``).
"""
from __future__ import annotations

import re
import time
from typing import Any

from app.core.logging import get_logger
from app.core.tracer import get_tracer
from app.engine.workflow.probe_intent import (
    normalize_failure_category,
    resolve_probe_intent,
)
from app.engine.workflow.state import FailureCategory, InterviewState, PlanTemplate

_VALID_FAILURE_CATEGORIES: set[str] = set(FailureCategory.__args__)  # type: ignore[attr-defined]

log = get_logger(__name__)


_ALLOWED_TEMPLATES: set[str] = {
    "simple", "adaptive", "deep_probe",
}

_OPERATIONAL_GAP_TERMS = (
    "compensation",
    "success rate",
    "retry",
    "time window",
    "manual",
    "fallback",
    "\u8865\u507f",
    "\u6210\u529f\u7387",
    "\u91cd\u8bd5",
    "\u65f6\u95f4\u7a97\u53e3",
    "\u4eba\u5de5",
    "\u515c\u5e95",
    "\u5b57\u6bb5",
)


def _gap_key(value: Any) -> str:
    lowered = str(value or "").strip().lower()
    if any(term in lowered for term in _OPERATIONAL_GAP_TERMS):
        return "operational_recovery_evidence"
    compact = re.sub(r"[^0-9a-z\u4e00-\u9fff]+", " ", lowered)
    return " ".join(compact.split())[:120] or lowered[:120]


def _dedupe_gap_hints(values: list[Any]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for raw in values:
        text = str(raw or "").strip()
        if not text:
            continue
        key = _gap_key(text)
        if key in seen:
            continue
        result.append(text)
        seen.add(key)
    return result


def _list_or_empty(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _record_or_empty(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _resolve_failure_categories(
    *,
    evaluation_categories: Any,
    failure_reason: str | None,
    weaknesses: list[str],
    missing_must_cover: list[str],
) -> list[str]:
    """Pick the structured failure-category list to forward into hints.

    Evaluator output wins when it contains at least one legal value;
    otherwise we wrap the keyword-driven inference as a one-item list.
    Empty result means "no category" — callers omit the key so the
    pre-PR2 ``contract_hints`` shape stays byte-identical for clean
    refines.
    """
    if isinstance(evaluation_categories, list):
        cleaned: list[str] = []
        seen: set[str] = set()
        for item in evaluation_categories:
            value = str(item or "").strip()
            if not value or value not in _VALID_FAILURE_CATEGORIES or value in seen:
                continue
            cleaned.append(value)
            seen.add(value)
        if cleaned:
            return cleaned

    inferred = normalize_failure_category(
        failure_reason=failure_reason,
        weaknesses=weaknesses,
        missing_must_cover=missing_must_cover,
    )
    return [inferred] if inferred else []


def _pick_next_template(evaluation: dict[str, Any]) -> PlanTemplate:
    recommended = evaluation.get("recommended_next_plan")
    if isinstance(recommended, str) and recommended in _ALLOWED_TEMPLATES:
        return recommended  # type: ignore[return-value]
    return "deep_probe"


def refine_followup_node(state: InterviewState) -> dict[str, Any]:
    """Mark the next director pass as a locked refine.

    ``refine_mode=True`` tells ``director_sample_node`` that it must
    stay on the current dimension: no ``switch_dimension`` and no
    ``skip_to_next``. This enforces the semantic the router promises
    ("refine = same dimension, one more attempt") regardless of what
    Thompson sampling would otherwise prefer. The flag is consumed and
    cleared by the director as soon as it honours the lock.

    ``pending_plan_template`` / ``pending_contract_hints`` carry the
    evaluator's concrete suggestion forward into the next ask round.
    """
    node_started_at = time.perf_counter()
    evaluation = state.get("evaluation", {}) or {}
    weaknesses = _dedupe_gap_hints(_list_or_empty(evaluation.get("weaknesses")))
    dim = state.get("current_dimension")

    next_template = _pick_next_template(evaluation)
    missing_must_cover = _dedupe_gap_hints([
        k
        for k, v in _record_or_empty(evaluation.get("rubric_coverage")).items()
        if v == "missing"
    ])
    # ``soft_warnings`` come from the verifier's abstain path (see
    # ``verification_node``): low-confidence concerns that did NOT
    # flip ``passed`` but should still nudge the next contract to
    # re-probe them. We surface them as a separate hint bucket so the
    # generator can distinguish "confirmed weakness" from "uncertain
    # concern worth re-asking".
    soft_warnings = list(evaluation.get("soft_warnings") or [])

    probe_intent = evaluation.get("recommended_probe_intent")
    failure_reason = evaluation.get("failure_reason")
    # PR2: prefer the evaluator's structured ``failure_categories`` when
    # the LLM produced any legal ones; fall back to the keyword-driven
    # ``normalize_failure_category`` inference otherwise. The dual-write
    # to both ``failure_categories`` (list) and ``failure_category``
    # (single) keeps every existing reader working — pre-PR2 callers
    # only look at the single field.
    failure_categories = _resolve_failure_categories(
        evaluation_categories=evaluation.get("failure_categories"),
        failure_reason=failure_reason,
        weaknesses=list(weaknesses),
        missing_must_cover=missing_must_cover,
    )
    failure_category = failure_categories[0] if failure_categories else None
    if not probe_intent:
        probe_intent = resolve_probe_intent(
            direction=(state.get("job_spec") or {}).get("interview_direction"),
            dimension=str(dim or "general"),
            job_level=(state.get("job_spec") or {}).get("level"),
            failure_category=failure_category,
            failure_reason=failure_reason,
        )

    contract_hints: dict[str, Any] = {
        "must_address": list(weaknesses),
        "missing_must_cover": missing_must_cover,
        "refine_mode": True,
    }
    if failure_categories:
        contract_hints["failure_categories"] = failure_categories
    if failure_category:
        contract_hints["failure_category"] = failure_category
    if probe_intent:
        contract_hints["probe_intent"] = probe_intent
    if failure_reason:
        contract_hints["failure_reason"] = failure_reason
    if soft_warnings:
        contract_hints["prior_soft_warnings"] = soft_warnings

    log.info(
        "refine_followup dim=%s weaknesses=%s next_plan=%s",
        dim,
        weaknesses[:2],
        next_template,
    )
    update = {
        "refine_mode": True,
        "pending_plan_template": next_template,
        "pending_contract_hints": contract_hints,
        "messages": [
            {
                "role": "system",
                "kind": "refine_note",
                "dimension": dim,
                "weaknesses": weaknesses,
                "pending_plan_template": next_template,
            }
        ],
    }
    try:
        get_tracer().trace_node_event(
            {**state, **update},
            node="refine_followup",
            payload={
                "dimension": dim,
                "next_template": next_template,
                "weakness_count": len(weaknesses),
                "refine_mode": True,
                "pending_plan_template": next_template,
                "pending_contract_hints": contract_hints,
                "must_address_count": len(contract_hints.get("must_address") or []),
                "missing_must_cover_count": len(
                    contract_hints.get("missing_must_cover") or []
                ),
                "failure_categories": list(
                    contract_hints.get("failure_categories") or []
                ),
                "probe_intent": contract_hints.get("probe_intent"),
                "failure_reason": contract_hints.get("failure_reason"),
                "prior_soft_warnings": list(
                    contract_hints.get("prior_soft_warnings") or []
                ),
                "elapsed_ms": int((time.perf_counter() - node_started_at) * 1000),
            },
        )
    except Exception as e:  # pragma: no cover - side channel
        log.warning("refine_followup tracer side-channel failed: %s", e)
    return update
