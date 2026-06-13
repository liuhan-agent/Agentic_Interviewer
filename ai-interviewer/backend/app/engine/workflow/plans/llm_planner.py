"""Optional LLM-driven ``AskPlan`` builder.

When ``runtime_config.ask_planning`` is True and the LLM provider is
not in stub mode, the ``ask_question_node`` calls
:func:`build_llm_ask_plan` instead of the default-template resolver.
The LLM is instructed to produce a plan by *editing* one of the
three canonical templates - deleting, reordering, or adding at most
one optional step. This keeps the output grounded in the existing
step-kind dispatcher and forbids free-form step kinds that the
executor would not understand.

Degrade path
------------
On any parse failure or provider error we return ``None`` so the
caller falls back to :func:`resolve_ask_plan`. That matches the
"grounded, not free-form" philosophy in ACO §10.4.
"""
from __future__ import annotations

import json
import uuid
from typing import Any

from app.core.logging import get_logger
from app.engine.agents.llm_client import (
    ChatMessage,
    call_chat,
    parse_json_response,
)
from app.engine.workflow.state import AskPlan

from .ask_plans import PLAN_TEMPLATES, build_default_plan

log = get_logger(__name__)


_ALLOWED_KINDS = {
    "select_structured_question",
    "retrieve_rag",
    "retrieve_strategy",
    "retrieve_skills",
    "retrieve_candidate_anchors",
    "draft_question",
    "negotiate_contract",
    "challenge_with_reference",
    "guardrail_check",
}


_LLM_PLANNER_TASK = """You are the Ask Planner. Produce an AskPlan for
the current interview round by starting from the BASE_TEMPLATE and
making at most 2 small edits (drop a step, add a step, or reorder a
subsequence).

Reply with a single JSON object:

{{
  "template": "simple|adaptive|deep_probe",
  "steps": [
    {{"step_id": 1, "kind": "...", "goal": "...", "success_criteria": "...", "optional": false}},
    ...
  ],
  "rationale": "one sentence: why this plan for this context"
}}

Allowed ``kind`` values: {allowed_kinds}
Rules:
- ``step_id`` must be strictly increasing.
- The last step MUST be ``guardrail_check``.
- Keep the plan to 2-9 steps.
- Keep ``select_structured_question`` before ``retrieve_candidate_anchors``
  and ``draft_question``.
- Keep ``retrieve_skills`` before ``draft_question`` whenever it is present.
- Do not invent unknown step kinds; if unsure, return BASE_TEMPLATE
  unchanged.

DIMENSION        = {dimension}
JOB_LEVEL        = {job_level}
REFINE_MODE      = {refine_mode}
SELECTED_ACTION  = {selected_action}
CONTRACT_HINTS   = {contract_hints}
BASE_TEMPLATE    = {base_template}
"""


def _base_template_for_context(
    *,
    selected_action: dict[str, Any] | None,
    refine_mode: bool,
    pending_plan_template: str | None,
) -> str:
    """Pick the template the LLM should start editing from.

    Uses the exact same priority order the default resolver uses so
    the LLM-on path is a superset, never a regression.
    """
    if pending_plan_template in PLAN_TEMPLATES:
        return pending_plan_template  # type: ignore[return-value]
    sa = selected_action or {}
    tmpl = sa.get("plan_template")
    if tmpl in PLAN_TEMPLATES:
        return tmpl  # type: ignore[no-any-return]
    if refine_mode:
        return "deep_probe"
    return "adaptive"


def _validate_llm_plan(
    raw_plan: dict[str, Any],
    base_template: str,
) -> AskPlan | None:
    if not isinstance(raw_plan, dict):
        return None
    template = raw_plan.get("template")
    if template not in PLAN_TEMPLATES:
        template = base_template
    raw_steps = raw_plan.get("steps")
    if not isinstance(raw_steps, list) or not raw_steps:
        return None

    cleaned_steps: list[dict[str, Any]] = []
    last_idx = 0
    for idx, step in enumerate(raw_steps, start=1):
        if not isinstance(step, dict):
            return None
        kind = step.get("kind")
        if kind not in _ALLOWED_KINDS:
            return None
        try:
            step_id = int(step.get("step_id", idx))
        except (TypeError, ValueError):
            step_id = idx
        if step_id <= last_idx:
            step_id = last_idx + 1
        last_idx = step_id
        cleaned_steps.append(
            {
                "step_id": step_id,
                "kind": kind,
                "goal": str(step.get("goal") or ""),
                "success_criteria": str(step.get("success_criteria") or ""),
                "produced_keys": list(step.get("produced_keys") or []),
                "dependencies": list(step.get("dependencies") or []),
                "optional": bool(step.get("optional") or False),
            }
        )

    if not cleaned_steps or cleaned_steps[-1]["kind"] != "guardrail_check":
        # Strict: guardrail must be last. If the LLM dropped it, we
        # refuse the plan rather than silently plugging it back in.
        return None

    return {
        "plan_id": f"ask-{template}-llm-{uuid.uuid4().hex[:8]}",
        "template": template,  # type: ignore[typeddict-item]
        "complexity": PLAN_TEMPLATES[template]["complexity"],
        "steps": cleaned_steps,  # type: ignore[typeddict-item]
        "source": "llm",
    }


def build_llm_ask_plan(
    *,
    dimension: str,
    job_level: str,
    selected_action: dict[str, Any] | None,
    refine_mode: bool,
    pending_plan_template: str | None,
    contract_hints: dict[str, Any] | None,
) -> AskPlan | None:
    """Try to produce an LLM-authored AskPlan.

    Returns ``None`` on any failure so the caller can fall back to
    the default resolver. All LLM exceptions are caught; we never
    propagate them into ``ask_question_node``.
    """
    base_template = _base_template_for_context(
        selected_action=selected_action,
        refine_mode=refine_mode,
        pending_plan_template=pending_plan_template,
    )
    base_plan = build_default_plan(base_template)

    messages = [
        ChatMessage(
            "system",
            "You are the Ask Planner. Respond only with JSON.",
        ),
        ChatMessage(
            "user",
            _LLM_PLANNER_TASK.format(
                allowed_kinds=sorted(_ALLOWED_KINDS),
                dimension=dimension,
                job_level=job_level,
                refine_mode=bool(refine_mode),
                selected_action=json.dumps(
                    selected_action or {}, ensure_ascii=False
                ),
                contract_hints=json.dumps(
                    contract_hints or {}, ensure_ascii=False
                ),
                base_template=json.dumps(
                    {"template": base_template, "steps": base_plan["steps"]},
                    ensure_ascii=False,
                ),
            ),
        ),
    ]
    try:
        raw = call_chat(messages, json_mode=True, agent_role="llm_planner")
        data = parse_json_response(raw)
    except Exception as e:  # pragma: no cover
        log.warning("llm_planner failed, falling back: %s", e)
        return None

    plan = _validate_llm_plan(data, base_template)
    if plan is None:
        log.info("llm_planner produced an invalid plan; falling back to default")
    return plan
