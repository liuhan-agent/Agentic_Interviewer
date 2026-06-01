"""Director node: choose the next strategy via Thompson Sampling.

Two policy modes (P1)
---------------------
- ``template`` (default): arms correspond to :class:`AskPlan`
  templates. The selected arm drives two things: the plan
  template used by ``ask_question_node`` *and* an optional
  side-effect such as "switch dimension before asking".
- ``legacy``: arms are the original 4 strategy-family ids
  (``deepen_technical``, ``switch_dimension``, ``give_hint``,
  ``skip_to_next``). Kept for backwards compatibility.

In both modes:
- The first turn also picks which rubric dimension to start with.
- ``refine_locked=True`` masks out any arm that would change
  dimensions, guaranteeing "refine = same dimension".
- If the evaluator pinned a ``pending_plan_template`` via
  ``refine_followup_node``, it is honoured regardless of policy
  mode by being passed down on the ``selected_action`` as a hint.
- ``plan_quick_review`` is registered as a template arm but stays
  masked out unless ``enable_quick_review_plan`` is enabled.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.logging import get_logger
from app.core.settings import get_settings
from app.core.tracer import get_tracer
from app.engine.resume_plan import select_resume_anchor_with_schedule
from app.engine.workflow.depth_followup import select_depth_followup_slot
from app.engine.workflow.difficulty_adapter import compute_target_difficulty
from app.engine.workflow.policy_context import policy_context_keys
from app.engine.workflow.routers import should_advance_for_coverage
from app.engine.workflow.score_aggregation import scored_dimensions_from_state
from app.engine.workflow.state import InterviewState
from app.ml.rl.action_space import (
    ACTIONS_BY_ID,
    DEEPEN_TECHNICAL,
    GIVE_HINT,
    LEGACY_ACTIONS,
    PLAN_ADAPTIVE,
    PLAN_DEEP_PROBE,
    PLAN_HINT,
    PLAN_QUICK_REVIEW,
    PLAN_SIMPLE,
    PLAN_SWITCH,
    SKIP_TO_NEXT,
    SWITCH_DIMENSION,
    TEMPLATE_ACTIONS,
    InterviewAction,
)
from app.ml.rl.thompson import get_bandit

log = get_logger(__name__)


@dataclass(frozen=True)
class ActionGuardrailResult:
    allowed: set[str]
    diagnostics: dict[str, Any]


_TEMPLATE_LIGHTWEIGHT_ACTIONS = {
    PLAN_SIMPLE.id,
    PLAN_HINT.id,
    PLAN_QUICK_REVIEW.id,
}
_LEGACY_LIGHTWEIGHT_ACTIONS = {
    GIVE_HINT.id,
    SKIP_TO_NEXT.id,
}


def _all_dims_done(state: InterviewState) -> bool:
    status = state.get("dimension_status", {}) or {}
    dims = state.get("dimensions", []) or []
    return bool(dims) and all(status.get(dim) == "passed" for dim in dims)


def _pick_next_dimension(state: InterviewState) -> str:
    dims = state.get("dimensions", [])
    status = state.get("dimension_status", {})
    pending = _pending_dimensions(state, status=status, include_active=True)
    if pending:
        return pending[0]
    return dims[-1] if dims else "technical_depth"


def _pending_dimensions(
    state: InterviewState,
    *,
    status: dict[str, Any],
    current_dim: str | None = None,
    include_active: bool = False,
) -> list[str]:
    dims = state.get("dimensions", []) or []
    eligible = {None, "pending", "active"} if include_active else {None, "pending"}
    focus = [
        d
        for d in state.get("focus_dimensions", [])
        if d in dims and d != current_dim and status.get(d) in eligible
    ]
    rest = [
        d
        for d in dims
        if d not in focus and d != current_dim and status.get(d) in eligible
    ]
    return focus + rest


def _allowed_actions_template(
    state: InterviewState,
    current_dim: str,
    *,
    refine_locked: bool,
) -> set[str]:
    """Mask for the 5-arm template namespace.

    When ``refine_locked`` we disallow arms that would change
    dimensions (``plan_switch``) or move away from the focus
    (``plan_simple`` is allowed as a gentle same-dimension restart).
    When there are no remaining dimensions we mask ``plan_switch``
    for the same reason the legacy code masked ``switch_dimension``.
    """
    if refine_locked:
        return {PLAN_ADAPTIVE.id, PLAN_DEEP_PROBE.id, PLAN_HINT.id}

    dims = state.get("dimensions", [])
    status = state.get("dimension_status", {})
    remaining = [
        d
        for d in dims
        if status.get(d) in {None, "pending", "active"} and d != current_dim
    ]
    allowed = {PLAN_SIMPLE.id, PLAN_ADAPTIVE.id, PLAN_DEEP_PROBE.id, PLAN_HINT.id}
    if _quick_review_enabled(state):
        allowed.add(PLAN_QUICK_REVIEW.id)
    if remaining:
        allowed.add(PLAN_SWITCH.id)
    return allowed


def _allowed_actions_legacy(
    state: InterviewState,
    current_dim: str,
    *,
    refine_locked: bool,
) -> set[str]:
    if refine_locked:
        return {DEEPEN_TECHNICAL.id, GIVE_HINT.id}

    dims = state.get("dimensions", [])
    status = state.get("dimension_status", {})
    remaining = [
        d
        for d in dims
        if status.get(d) in {None, "pending", "active"} and d != current_dim
    ]
    allowed = {DEEPEN_TECHNICAL.id, GIVE_HINT.id, SKIP_TO_NEXT.id}
    if remaining:
        allowed.add(SWITCH_DIMENSION.id)
    return allowed


def _policy_mode() -> str:
    try:
        return get_settings().policy_mode
    except Exception:  # pragma: no cover - settings may not be loaded in some tests
        return "template"


def _quick_review_enabled(state: InterviewState) -> bool:
    runtime_config = state.get("runtime_config") or {}
    if "enable_quick_review_plan" in runtime_config:
        return bool(runtime_config.get("enable_quick_review_plan"))
    try:
        return bool(getattr(get_settings(), "enable_quick_review_plan", False))
    except Exception:  # pragma: no cover - settings may be stubbed in tests
        return False


def _sorted_actions(actions: set[str]) -> list[str]:
    return sorted(actions)


def _current_contract(state: InterviewState) -> dict[str, Any] | None:
    contract = state.get("current_contract")
    if isinstance(contract, dict) and contract:
        return contract
    question = state.get("current_question") or {}
    if isinstance(question, dict):
        nested = question.get("contract")
        if isinstance(nested, dict) and nested:
            return nested
    return None


def _recent_low_signal_count(state: InterviewState, current_dim: str) -> int:
    try:
        threshold = float(getattr(get_settings(), "default_quality_threshold", 7.5))
    except Exception:  # pragma: no cover - settings may be stubbed in tests
        threshold = 7.5

    count = 0
    for turn in reversed(list(state.get("qa_history") or [])):
        if not isinstance(turn, dict) or turn.get("dimension") != current_dim:
            continue
        evaluation = turn.get("evaluation") or {}
        if not isinstance(evaluation, dict):
            break
        try:
            score = float(evaluation.get("score", 0.0))
        except (TypeError, ValueError):
            score = 0.0
        passed = evaluation.get("passed")
        if passed is False or score < threshold:
            count += 1
            if count >= 2:
                return count
            continue
        break
    return count


def _action_guardrail_reason_codes(
    *,
    state: InterviewState,
    current_dim: str,
    target_difficulty: str,
) -> list[str]:
    reasons: list[str] = []

    if state.get("refine_mode"):
        reasons.append("refine_mode")
    if state.get("pending_contract_hints"):
        reasons.append("pending_contract_hints")
    if state.get("pending_plan_template"):
        reasons.append("pending_plan_template")
    if target_difficulty == "hard":
        reasons.append("target_difficulty_hard")

    evaluation = state.get("evaluation") or {}
    if isinstance(evaluation, dict):
        if evaluation.get("verifier_forced_refine"):
            reasons.append("verifier_forced_refine")
        if evaluation.get("soft_warnings"):
            reasons.append("verification_soft_warning")

    contract = _current_contract(state)
    if contract is not None:
        signed_by = {str(item) for item in (contract.get("signed_by") or [])}
        if "evaluator" not in signed_by:
            reasons.append("contract_unsigned")
        if not contract.get("must_cover"):
            reasons.append("contract_missing_must_cover")
        if not contract.get("acceptance_checks"):
            reasons.append("contract_missing_acceptance_checks")

    if _recent_low_signal_count(state, current_dim) >= 2:
        reasons.append("consecutive_low_score")

    return reasons


def _apply_action_guardrail(
    *,
    allowed: set[str],
    mode: str,
    state: InterviewState,
    target_difficulty: str,
) -> ActionGuardrailResult:
    original_allowed = set(allowed)
    current_dim = state.get("current_dimension") or ""
    reason_codes = _action_guardrail_reason_codes(
        state=state,
        current_dim=str(current_dim),
        target_difficulty=target_difficulty,
    )
    if mode == "legacy":
        lightweight = _LEGACY_LIGHTWEIGHT_ACTIONS
    else:
        lightweight = _TEMPLATE_LIGHTWEIGHT_ACTIONS
    disabled_ids = original_allowed & lightweight if reason_codes else set()
    filtered_allowed = original_allowed - disabled_ids
    fallback_empty_mask = bool(disabled_ids and not filtered_allowed)
    final_allowed = original_allowed if fallback_empty_mask else filtered_allowed
    final_reason_codes = list(reason_codes)
    if fallback_empty_mask:
        final_reason_codes.append("guardrail_fallback_empty_mask")

    diagnostics = {
        "enabled": bool(disabled_ids and not fallback_empty_mask),
        "mode": "quality_floor",
        "original_allowed_actions": _sorted_actions(original_allowed),
        "final_allowed_actions": _sorted_actions(final_allowed),
        "disabled_actions": [
            {"action_id": action_id, "reason_codes": list(reason_codes)}
            for action_id in _sorted_actions(disabled_ids)
        ],
        "reason_codes": final_reason_codes,
    }
    return ActionGuardrailResult(allowed=final_allowed, diagnostics=diagnostics)


def _resolve_mode_and_actions(
    state: InterviewState,
    current_dim: str,
    *,
    refine_locked: bool,
) -> tuple[str, set[str]]:
    """Compute (policy_mode, allowed_action_ids) for the current pass.

    ``runtime_config.policy_mode`` on state takes precedence over the
    global setting so tests / request translators can pin a mode.
    """
    rc = state.get("runtime_config") or {}
    mode = rc.get("policy_mode") or _policy_mode()
    if mode not in {"template", "legacy"}:
        mode = "template"

    if mode == "template":
        allowed = _allowed_actions_template(
            state, current_dim, refine_locked=refine_locked
        )
    else:
        allowed = _allowed_actions_legacy(
            state, current_dim, refine_locked=refine_locked
        )
    return mode, allowed


def _apply_dimension_effect(
    state: InterviewState,
    action: InterviewAction,
    current_dim: str,
    *,
    forced_target: str | None = None,
) -> tuple[str, dict[str, Any]]:
    """Switch dimensions immediately if the chosen arm demands it.

    This mirrors the inline behaviour that used to live in
    ``apply_action_side_effects``: ``plan_switch`` / ``skip_to_next``
    / ``switch_dimension`` all result in the interview rotating to
    the next pending dimension *before* ``ask_question_node`` runs.
    """
    if action.dimension_effect != "switch" and not forced_target:
        return current_dim, dict(state.get("dimension_status", {}) or {})

    status = dict(state.get("dimension_status", {}) or {})
    if forced_target:
        if current_dim and status.get(current_dim) == "active":
            status[current_dim] = "pending"
        status[forced_target] = "active"
        return forced_target, status

    if current_dim and status.get(current_dim) == "active":
        status[current_dim] = "pending"
    for d in _pending_dimensions(state, status=status, current_dim=current_dim):
        status[d] = "active"
        return d, status

    return current_dim, status


def _remaining_turns(state: InterviewState) -> int | None:
    raw_budget = state.get("turn_budget_remaining")
    if raw_budget is not None:
        try:
            return max(0, int(raw_budget))
        except (TypeError, ValueError):
            return None

    max_turns = state.get("max_turns")
    formal_turn_idx = state.get("formal_turn_idx", state.get("turn_idx", 0))
    try:
        return max(0, int(max_turns) - int(formal_turn_idx))
    except (TypeError, ValueError):
        return None


def _coverage_priority_target(
    state: InterviewState,
    current_dim: str,
) -> tuple[str | None, list[str]]:
    dims = list(state.get("dimensions") or [])
    if not dims:
        return None, []

    scored = scored_dimensions_from_state(state)
    unscored = [d for d in dims if d not in scored]
    if not unscored or current_dim in unscored:
        return None, unscored

    status = state.get("dimension_status", {}) or {}
    target = next((d for d in unscored if d != current_dim), None)
    if target is None:
        return None, unscored

    if status.get(current_dim) == "passed":
        return target, unscored

    remaining = _remaining_turns(state)
    if remaining is not None and remaining <= len(unscored):
        return target, unscored

    return None, unscored


def _anchor_expansion_target(
    state: InterviewState,
) -> tuple[str | None, dict[str, Any] | None]:
    if not _all_dims_done(state):
        return None, None
    rc = state.get("runtime_config") or {}
    depth = str(rc.get("interview_depth") or "standard")
    if depth not in {"standard", "deep"}:
        return None, None
    selection = select_resume_anchor_with_schedule(
        candidate=state.get("candidate", {}) or {},
        job_spec=state.get("job_spec", {}) or {},
        dimension="",
        qa_history=list(state.get("qa_history") or []),
        turn_idx=int(state.get("formal_turn_idx", state.get("turn_idx", 0)) or 0),
        self_intro_profile=state.get("self_intro_profile") or {},
        interview_depth=depth,
        focus_dimensions=list(state.get("focus_dimensions") or []),
    )
    anchor = selection.get("resume_anchor")
    scheduler = selection.get("scheduler")
    if not isinstance(anchor, dict) or not (scheduler or {}).get("available"):
        return None, None
    dims = [dim for dim in anchor.get("dimensions") or [] if isinstance(dim, str)]
    allowed_dims = list(state.get("dimensions") or [])
    target = next((dim for dim in dims if dim in allowed_dims), None)
    if target is None:
        target = dims[0] if dims else state.get("current_dimension")
    if not target:
        return None, None
    return str(target), selection


def director_sample_node(state: InterviewState) -> dict[str, Any]:
    turn_idx = state.get("turn_idx", 0)
    job_spec = state.get("job_spec", {})

    current_dim = state.get("current_dimension") or _pick_next_dimension(state)
    anchor_target, anchor_selection = _anchor_expansion_target(state)
    if anchor_target:
        current_dim = anchor_target
    depth_followup_slot = None
    if not anchor_target:
        depth_followup_slot = select_depth_followup_slot(state)
        if depth_followup_slot:
            current_dim = str(depth_followup_slot.get("dimension") or current_dim)
    refine_locked = bool(state.get("refine_mode"))

    mode, allowed = _resolve_mode_and_actions(
        state, current_dim, refine_locked=refine_locked
    )
    guardrail_target_diff = compute_target_difficulty(state, current_dim)
    guardrail = _apply_action_guardrail(
        allowed=allowed,
        mode=mode,
        state={**state, "current_dimension": current_dim},  # type: ignore[arg-type]
        target_difficulty=guardrail_target_diff,
    )
    allowed = guardrail.allowed

    bandit = get_bandit()
    policy_keys = policy_context_keys(job_spec, current_dim)
    direction_key = policy_keys[0]
    global_key = policy_keys[-1]
    context_key = direction_key
    if len(policy_keys) > 1:
        min_obs = int(getattr(get_settings(), "policy_direction_min_observations", 3))
        if (
            bandit.observation_count(direction_key, mask=allowed) < min_obs
            and bandit.observation_count(global_key, mask=allowed) > 0
        ):
            context_key = global_key
    coverage_target, unscored_dimensions = _coverage_priority_target(
        state,
        current_dim,
    )
    if coverage_target:
        action = PLAN_SWITCH if mode == "template" else SWITCH_DIMENSION
        diagnostics = {
            "mode": "coverage_priority_switch",
            "context_key": context_key,
            "chosen": action.id,
            "target_dimension": coverage_target,
            "unscored_dimensions": unscored_dimensions,
            "action_guardrail": guardrail.diagnostics,
        }
    elif should_advance_for_coverage(state):
        action = PLAN_SWITCH if mode == "template" else SWITCH_DIMENSION
        diagnostics = {
            "mode": "coverage_force_switch",
            "context_key": context_key,
            "chosen": action.id,
            "action_guardrail": guardrail.diagnostics,
        }
    elif depth_followup_slot:
        action = PLAN_DEEP_PROBE if mode == "template" else DEEPEN_TECHNICAL
        diagnostics = {
            "mode": "depth_followup",
            "context_key": context_key,
            "chosen": action.id,
            "target_dimension": depth_followup_slot.get("dimension"),
            "target_anchor_key": (
                (depth_followup_slot.get("resume_anchor") or {}).get("anchor_key")
                if isinstance(depth_followup_slot.get("resume_anchor"), dict)
                else None
            ),
            "depth_followup_slot": depth_followup_slot,
            "action_guardrail": guardrail.diagnostics,
        }
    else:
        action, diagnostics = bandit.select(context_key, mask=allowed)
        diagnostics = {
            **diagnostics,
            "action_guardrail": guardrail.diagnostics,
        }
        if anchor_target and anchor_selection:
            anchor = anchor_selection.get("resume_anchor") or {}
            scheduler = anchor_selection.get("scheduler") or {}
            diagnostics = {
                **diagnostics,
                "mode": "anchor_expansion",
                "target_dimension": anchor_target,
                "target_anchor_key": anchor.get("anchor_key"),
                "anchor_attempt": scheduler.get("anchor_attempt"),
                "max_anchor_attempts": scheduler.get("max_anchor_attempts"),
            }

    # ``pending_plan_template`` is a direct evaluator hint. It wins
    # over the bandit's template mapping for the *upcoming* ask round
    # but does *not* retrain the arm (we still credit the arm the
    # bandit picked, because that is what is responsible for the
    # dimension_effect/mask decisions).
    pending_template = state.get("pending_plan_template")

    # Apply dimension side-effect (e.g. plan_switch / switch_dimension)
    new_current_dim, new_status = _apply_dimension_effect(
        state,
        action,
        current_dim,
        forced_target=coverage_target,
    )
    if anchor_target and not coverage_target:
        new_current_dim = anchor_target
        new_status = dict(state.get("dimension_status", {}) or {})
    if depth_followup_slot and not coverage_target:
        new_current_dim = str(depth_followup_slot.get("dimension") or new_current_dim)
        new_status = dict(state.get("dimension_status", {}) or {})
    # If the dimension rotated, update dimension_status for the new
    # active dimension too.
    if new_current_dim != current_dim:
        if new_status.get(new_current_dim) == "pending":
            new_status[new_current_dim] = "active"
    else:
        if (
            current_dim in new_status
            and new_status[current_dim] == "pending"
        ):
            new_status[current_dim] = "active"

    target_diff = compute_target_difficulty(state, new_current_dim)

    selected_action = {
        "id": action.id,
        "label": action.label,
        "description": action.description,
        "plan_template": action.plan_template,
        "dimension_effect": action.dimension_effect,
        "diagnostics": diagnostics,
        "refine_locked": refine_locked,
        "policy_mode": mode,
        "policy_context_key": context_key,
        "policy_context_keys": policy_keys,
        # Hint consumed by ask_question_node; cleared there (not here)
        # so director -> ask can share the same graph cycle.
        "plan_template_hint": pending_template,
        "target_difficulty": target_diff,
    }
    log.info(
        "director: turn=%d dim=%s -> %s arm=%s template=%s effect=%s "
        "mode=%s hint=%s difficulty=%s",
        turn_idx,
        current_dim,
        new_current_dim,
        action.id,
        action.plan_template,
        action.dimension_effect,
        mode,
        pending_template,
        target_diff,
    )
    updated: dict[str, Any] = {
        "selected_action": selected_action,
        "policy_id": f"thompson_v1::{mode}::{context_key}",
        "policy_context_keys": policy_keys,
        "current_dimension": new_current_dim,
        "dimension_status": new_status,
        "refine_mode": False,
        "target_difficulty": target_diff,
    }
    # Fire-and-forget director trace so trainset builders see
    # (masked_arms, sampled arm, posterior-at-decision).  We build a
    # trace view by folding our updates on top of the input state to
    # match the shape ``Tracer._context_key`` and snapshotters expect.
    trace_view = dict(state)
    trace_view.update(updated)
    try:
        get_tracer().trace_director_sample(trace_view)
    except Exception as e:  # pragma: no cover
        log.warning("director tracer side-channel failed: %s", e)
    return updated


# Kept for backwards compatibility; the main dimension-effect logic
# now lives inline in ``director_sample_node``. Leave the helper
# around because external callers import it for targeted tests.
def apply_action_side_effects(state: InterviewState) -> dict[str, Any]:
    action_id = (state.get("selected_action") or {}).get("id")
    action = ACTIONS_BY_ID.get(action_id or "")
    if action is None:
        return {}
    if action.dimension_effect != "switch":
        return {}
    status = dict(state.get("dimension_status", {}) or {})
    current = state.get("current_dimension")
    if current and status.get(current) == "active":
        status[current] = "pending"
    for d in _pending_dimensions(state, status=status, current_dim=current):
        status[d] = "active"
        return {"current_dimension": d, "dimension_status": status}
    return {}


# Re-export the legacy tuple for analytics dashboards that iterate
# over the original 4-arm space.
_ = LEGACY_ACTIONS
_ = TEMPLATE_ACTIONS
