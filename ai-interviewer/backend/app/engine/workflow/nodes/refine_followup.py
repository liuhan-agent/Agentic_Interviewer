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

import time
from typing import Any

from app.core.logging import get_logger
from app.core.tracer import get_tracer
from app.engine.workflow.probe_intent import (
    normalize_failure_category,
    resolve_probe_intent,
)
from app.engine.workflow.state import InterviewState, PlanTemplate

log = get_logger(__name__)


_ALLOWED_TEMPLATES: set[str] = {
    "simple", "adaptive", "deep_probe",
}


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
    weaknesses = evaluation.get("weaknesses") or []
    dim = state.get("current_dimension")

    next_template = _pick_next_template(evaluation)
    missing_must_cover = [
        k
        for k, v in (evaluation.get("rubric_coverage") or {}).items()
        if v == "missing"
    ]
    # ``soft_warnings`` come from the verifier's abstain path (see
    # ``verification_node``): low-confidence concerns that did NOT
    # flip ``passed`` but should still nudge the next contract to
    # re-probe them. We surface them as a separate hint bucket so the
    # generator can distinguish "confirmed weakness" from "uncertain
    # concern worth re-asking".
    soft_warnings = list(evaluation.get("soft_warnings") or [])

    probe_intent = evaluation.get("recommended_probe_intent")
    failure_reason = evaluation.get("failure_reason")
    failure_category = normalize_failure_category(
        failure_reason=failure_reason,
        weaknesses=list(weaknesses),
        missing_must_cover=missing_must_cover,
    )
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
                "elapsed_ms": int((time.perf_counter() - node_started_at) * 1000),
            },
        )
    except Exception as e:  # pragma: no cover - side channel
        log.warning("refine_followup tracer side-channel failed: %s", e)
    return update
