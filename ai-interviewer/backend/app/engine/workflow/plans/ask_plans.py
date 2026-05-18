"""Default ``AskPlan`` templates and the resolver function.

Three templates in P0, mirroring the three question-quality bands
documented in :mod:`app.engine.workflow.nodes.ask_question`:

- ``simple``:    first turn / low-risk dimension, no contract negotiation
- ``quick_review``: compact recap / quick signal check, no contract negotiation
- ``adaptive``:  default mid-level, with contract negotiation
- ``deep_probe`` evaluator-driven refine, adds a ``challenge`` step

Policy order for picking a template (highest priority first):

1. ``state.pending_plan_template`` — set by the evaluator via
   ``refine_followup_node`` — this is how a prior evaluator round can
   pin the next ask plan.
2. A fixed mapping from ``(selected_action.id, refine_mode)``. This
   preserves the existing 4-arm bandit: we do *not* learn templates
   as arms in P0, we just project arms onto templates deterministically.
3. Fall back to ``adaptive`` if neither applies.

The resolver is pure and stateless; the ``ask_question_node`` owns
the actual step execution.
"""
from __future__ import annotations

import uuid
from copy import deepcopy
from typing import Any

from app.engine.workflow.state import (
    AskPlan,
    AskPlanStep,
    PlanTemplate,
)


def _step(
    step_id: int,
    kind: str,
    goal: str,
    success_criteria: str,
    produced_keys: list[str] | None = None,
    dependencies: list[int] | None = None,
    optional: bool = False,
) -> AskPlanStep:
    return {
        "step_id": step_id,
        "kind": kind,  # type: ignore[typeddict-item]
        "goal": goal,
        "success_criteria": success_criteria,
        "produced_keys": produced_keys or [],
        "dependencies": dependencies or [],
        "optional": optional,
    }


_SIMPLE_STEPS: list[AskPlanStep] = [
    _step(
        1,
        "retrieve_rag",
        goal="Pull top-k knowledge snippets for the current dimension.",
        success_criteria="At least one retrieved doc OR an explicit empty marker.",
        produced_keys=["retrieval_block"],
    ),
    _step(
        2,
        "retrieve_candidate_anchors",
        goal="Pull semantically related resume and self-intro anchors to ground follow-up questions.",
        success_criteria="candidate_anchor_rag_artifact is set (status may be off/shadow/empty).",
        produced_keys=[
            "resume_rag_block",
            "self_intro_rag_block",
            "candidate_anchor_rag_artifact",
        ],
        dependencies=[1],
        optional=True,
    ),
    _step(
        3,
        "draft_question",
        goal="Author a clear, open-ended question plus a draft contract proposal.",
        success_criteria="question non-empty AND proposed_contract has >=1 must_cover item.",
        produced_keys=["question_payload", "proposed_contract"],
        dependencies=[1, 2],
    ),
    _step(
        4,
        "guardrail_check",
        goal="Scan the question against the compliance rule set.",
        success_criteria="verdict.allowed OR fallback applied.",
        produced_keys=["question_payload"],
        dependencies=[3],
    ),
]

_QUICK_REVIEW_STEPS: list[AskPlanStep] = [
    _step(
        1,
        "retrieve_rag",
        goal="Pull only the most relevant snippets needed for a compact review probe.",
        success_criteria="At least one retrieved doc OR an explicit empty marker.",
        produced_keys=["retrieval_block"],
    ),
    _step(
        2,
        "retrieve_candidate_anchors",
        goal="Pull semantically related resume and self-intro anchors to ground follow-up questions.",
        success_criteria="candidate_anchor_rag_artifact is set (status may be off/shadow/empty).",
        produced_keys=[
            "resume_rag_block",
            "self_intro_rag_block",
            "candidate_anchor_rag_artifact",
        ],
        dependencies=[1],
        optional=True,
    ),
    _step(
        3,
        "draft_question",
        goal=(
            "Author one concise recap-style question that checks the current "
            "dimension without opening a long detour."
        ),
        success_criteria="question non-empty AND proposed_contract has >=1 must_cover item.",
        produced_keys=["question_payload", "proposed_contract"],
        dependencies=[1, 2],
    ),
    _step(
        4,
        "guardrail_check",
        goal="Scan the compact question against the compliance rule set.",
        success_criteria="verdict.allowed OR fallback applied.",
        produced_keys=["question_payload"],
        dependencies=[3],
    ),
]

_ADAPTIVE_STEPS: list[AskPlanStep] = [
    _step(
        1,
        "retrieve_rag",
        goal="Pull top-k knowledge snippets for the current dimension.",
        success_criteria="At least one retrieved doc OR an explicit empty marker.",
        produced_keys=["retrieval_block"],
    ),
    _step(
        2,
        "retrieve_strategy",
        goal="Surface memoised strategies matching dimension + job_level.",
        success_criteria="strategy_block non-empty string (possibly the no-match placeholder).",
        produced_keys=["strategy_block"],
    ),
    _step(
        3,
        "retrieve_candidate_anchors",
        goal="Pull semantically related resume and self-intro anchors to ground follow-up questions.",
        success_criteria="candidate_anchor_rag_artifact is set (status may be off/shadow/empty).",
        produced_keys=[
            "resume_rag_block",
            "self_intro_rag_block",
            "candidate_anchor_rag_artifact",
        ],
        dependencies=[1, 2],
        optional=True,
    ),
    _step(
        4,
        "draft_question",
        goal="Author a clear question plus a draft contract proposal.",
        success_criteria="question non-empty AND proposed_contract has >=2 must_cover items.",
        produced_keys=["question_payload", "proposed_contract"],
        dependencies=[1, 2, 3],
    ),
    _step(
        5,
        "negotiate_contract",
        goal="Have the evaluator confirm/amend the contract BEFORE the question is emitted.",
        success_criteria="contract.signed_by contains 'evaluator'.",
        produced_keys=["contract"],
        dependencies=[4],
    ),
    _step(
        6,
        "guardrail_check",
        goal="Scan the final question against the compliance rule set.",
        success_criteria="verdict.allowed OR fallback applied.",
        produced_keys=["question_payload"],
        dependencies=[5],
    ),
]

_DEEP_PROBE_STEPS: list[AskPlanStep] = [
    _step(
        1,
        "retrieve_rag",
        goal="Pull focused knowledge snippets; bias toward advanced/edge material.",
        success_criteria="At least one retrieved doc OR an explicit empty marker.",
        produced_keys=["retrieval_block"],
    ),
    _step(
        2,
        "retrieve_strategy",
        goal="Surface strategies tagged for the same dimension + previous-turn weaknesses.",
        success_criteria="strategy_block non-empty.",
        produced_keys=["strategy_block"],
    ),
    _step(
        3,
        "retrieve_candidate_anchors",
        goal="Pull semantically related resume and self-intro anchors to ground follow-up questions.",
        success_criteria="candidate_anchor_rag_artifact is set (status may be off/shadow/empty).",
        produced_keys=[
            "resume_rag_block",
            "self_intro_rag_block",
            "candidate_anchor_rag_artifact",
        ],
        dependencies=[1, 2],
        optional=True,
    ),
    _step(
        4,
        "draft_question",
        goal="Author a follow-up question that directly probes the prior weaknesses.",
        success_criteria=(
            "question non-empty AND proposed_contract.bar_level is 'deep_probe' "
            "AND >=3 acceptance_checks."
        ),
        produced_keys=["question_payload", "proposed_contract"],
        dependencies=[1, 2, 3],
    ),
    _step(
        5,
        "negotiate_contract",
        goal=(
            "Evaluator signs a stricter contract: more acceptance_checks, "
            "bar_level='deep_probe', explicit review_focus."
        ),
        success_criteria="contract.signed_by contains 'evaluator' AND bar_level=='deep_probe'.",
        produced_keys=["contract"],
        dependencies=[4],
    ),
    _step(
        6,
        "challenge_with_reference",
        goal=(
            "Optionally annotate the question with a concrete reference scenario "
            "(counter-example or production pitfall)."
        ),
        success_criteria="question_payload.challenge_context populated OR step marked optional-skip.",
        produced_keys=["question_payload"],
        dependencies=[5],
        optional=True,
    ),
    _step(
        7,
        "guardrail_check",
        goal="Scan the final question against the compliance rule set.",
        success_criteria="verdict.allowed OR fallback applied.",
        produced_keys=["question_payload"],
        dependencies=[6],
    ),
]


PLAN_TEMPLATES: dict[PlanTemplate, dict[str, Any]] = {
    "simple": {
        "complexity": "simple",
        "steps": _SIMPLE_STEPS,
    },
    "quick_review": {
        "complexity": "simple",
        "steps": _QUICK_REVIEW_STEPS,
    },
    "adaptive": {
        "complexity": "medium",
        "steps": _ADAPTIVE_STEPS,
    },
    "deep_probe": {
        "complexity": "hard",
        "steps": _DEEP_PROBE_STEPS,
    },
}


# Fallback projection from the legacy 4-arm action space onto plan
# templates. Still used when the director ran in ``policy_mode=legacy``
# and therefore populated ``selected_action`` with a legacy id only.
# P1 template arms carry their own ``plan_template`` so this table is
# no longer the primary path.
_ACTION_TO_TEMPLATE: dict[tuple[str, bool], PlanTemplate] = {
    ("give_hint", False): "simple",
    ("give_hint", True): "simple",
    ("deepen_technical", False): "adaptive",
    ("deepen_technical", True): "deep_probe",
    ("switch_dimension", False): "adaptive",
    ("switch_dimension", True): "adaptive",
    ("skip_to_next", False): "simple",
    ("skip_to_next", True): "simple",
}


def build_default_plan(template: PlanTemplate) -> AskPlan:
    """Instantiate a fresh plan object from the named template.

    Steps are deep-copied so callers can mutate them inside the
    executor without leaking state into subsequent rounds.
    """
    if template not in PLAN_TEMPLATES:
        template = "adaptive"
    spec = PLAN_TEMPLATES[template]
    return {
        "plan_id": f"ask-{template}-{uuid.uuid4().hex[:8]}",
        "template": template,
        "complexity": spec["complexity"],
        "steps": deepcopy(spec["steps"]),
        "source": "default",
    }


def resolve_ask_plan(
    *,
    selected_action: dict[str, Any] | None,
    refine_mode: bool,
    pending_plan_template: PlanTemplate | None,
    runtime_config: dict[str, Any] | None,
    turn_budget_remaining: int | None = None,
    uncovered_dimensions: int | None = None,
    job_level: str | None = None,
) -> AskPlan:
    """Pick a concrete plan for the upcoming ``ask_question`` round.

    Priority (highest -> lowest):

    1. ``pending_plan_template`` (evaluator-driven override,
       honoured regardless of bandit policy mode).
    2. ``selected_action.plan_template`` (P1: bandit template arms
       carry their target template directly).
    3. Legacy ``(action_id, refine_mode)`` mapping (P0 fallback,
       used when policy_mode=="legacy" or for unknown ids).
    3b. Level-aware upgrade: staff/principal + deepen_technical
       defaults to ``deep_probe`` even outside refine mode.
    4. ``runtime_config.iterative_contract`` -> ``adaptive``.
    5. Fallback: ``adaptive``.

    ``runtime_config.ask_planning`` is accepted here but the
    LLM-planner path is resolved one layer up in
    :func:`app.engine.workflow.nodes.ask_question.ask_question_node`
    (so the plan object it produces can use this resolver's templates
    as a starting point).
    """
    if pending_plan_template and pending_plan_template in PLAN_TEMPLATES:
        return build_default_plan(pending_plan_template)

    sa = selected_action or {}
    template_hint: PlanTemplate | None = sa.get("plan_template")
    if template_hint and template_hint in PLAN_TEMPLATES:
        return build_default_plan(template_hint)

    action_id = sa.get("id", "")
    level = (job_level or "").lower()
    if (
        level in {"staff", "principal"}
        and action_id == "deepen_technical"
        and not refine_mode
    ):
        return build_default_plan("deep_probe")

    mapped = _ACTION_TO_TEMPLATE.get((action_id, bool(refine_mode)))
    if mapped is not None:
        return build_default_plan(mapped)

    rc = runtime_config or {}
    if rc.get("iterative_contract"):
        return build_default_plan("adaptive")

    return build_default_plan("adaptive")
