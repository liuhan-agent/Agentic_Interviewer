"""Discrete action space used by the Director for follow-up strategy.

Two coexisting namespaces
-------------------------
P0 exposed four "strategy-family" arms (``deepen_technical`` etc.).
P1 adds a parallel "plan_template" namespace whose ids line up 1:1
with the :class:`AskPlan` templates. The director picks a template-
arm by default now; the strategy-family names are kept as aliases so
existing bandit posteriors, CI fixtures, and analytics dashboards
keep working during rollout.

Template arms
~~~~~~~~~~~~~
- ``plan_simple``       lightweight probe; no contract negotiation
- ``plan_quick_review`` compact recap-style probe; opt-in rollout arm
- ``plan_adaptive``     default follow-up with evaluator co-sign
- ``plan_deep_probe``   evaluator-driven refine, adds challenge step
- ``plan_hint``         same template as simple but biased at
                        prompt level toward hinting; kept as a
                        separate arm so ``give_hint`` alias maps
                        cleanly
- ``plan_switch``       same template as adaptive but signals the
                        director it should switch dimensions before
                        the next ask

Keeping the default bandit arm count at 5 (vs. 3 bare templates) means:
  * ``give_hint``/``switch_dimension`` statistics from the old 4-arm
    space can be replayed via ``ALIAS_MAP`` without rebucketing;
  * We still honour the ACO-style "few arms per context" heuristic.
The ``plan_quick_review`` arm is registered but excluded from masks
unless ``enable_quick_review_plan`` is enabled.

Bandit callers should use :func:`template_id_for_action` when they
have a strategy-family id and need the canonical template arm.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal


@dataclass(frozen=True)
class InterviewAction:
    id: str
    label: str
    description: str
    # Which :class:`AskPlan` template this arm maps to. Multiple arms
    # may share a template; the director distinguishes them via other
    # side-effects (e.g. ``plan_switch`` changes ``current_dimension``).
    plan_template: Literal["simple", "adaptive", "deep_probe", "quick_review"]
    # Optional graph-level side-effect tag. ``None`` means "no
    # dimension change"; ``switch`` tells the director to rotate to
    # the next pending dimension *before* ask_question runs.
    dimension_effect: Literal["none", "switch"] = "none"


# ----- Template-arm namespace (P1, primary) --------------------------
PLAN_SIMPLE: Final = InterviewAction(
    id="plan_simple",
    label="Plan: Simple",
    description="Lightweight first-turn probe; skip contract negotiation.",
    plan_template="simple",
)
PLAN_QUICK_REVIEW: Final = InterviewAction(
    id="plan_quick_review",
    label="Plan: Quick Review",
    description="Compact recap probe that quickly checks one dimension before moving on.",
    plan_template="quick_review",
)
PLAN_ADAPTIVE: Final = InterviewAction(
    id="plan_adaptive",
    label="Plan: Adaptive",
    description="Default mid-level ask with evaluator-signed contract.",
    plan_template="adaptive",
)
PLAN_DEEP_PROBE: Final = InterviewAction(
    id="plan_deep_probe",
    label="Plan: Deep Probe",
    description="Follow-up probe with stricter contract and challenge.",
    plan_template="deep_probe",
)
PLAN_HINT: Final = InterviewAction(
    id="plan_hint",
    label="Plan: Hint",
    description="Simple plan biased toward hinting; keeps same dimension.",
    plan_template="simple",
)
PLAN_SWITCH: Final = InterviewAction(
    id="plan_switch",
    label="Plan: Switch",
    description="Adaptive plan but move on to the next pending dimension.",
    plan_template="adaptive",
    dimension_effect="switch",
)


# ----- Legacy strategy-family aliases (P0, kept for compatibility) ---
DEEPEN_TECHNICAL: Final = InterviewAction(
    id="deepen_technical",
    label="Deepen Technical",
    description="Push harder on the current technical dimension; ask for concrete mechanisms.",
    plan_template="adaptive",
)
SWITCH_DIMENSION: Final = InterviewAction(
    id="switch_dimension",
    label="Switch Dimension",
    description="Move on to the next unassessed rubric dimension.",
    plan_template="adaptive",
    dimension_effect="switch",
)
GIVE_HINT: Final = InterviewAction(
    id="give_hint",
    label="Give Hint",
    description="Provide a small hint, keep the same dimension, re-ask.",
    plan_template="simple",
)
SKIP_TO_NEXT: Final = InterviewAction(
    id="skip_to_next",
    label="Skip To Next",
    description="Close out this line of questioning, go to the next question.",
    plan_template="simple",
    dimension_effect="switch",
)


TEMPLATE_ACTIONS: tuple[InterviewAction, ...] = (
    PLAN_SIMPLE,
    PLAN_QUICK_REVIEW,
    PLAN_ADAPTIVE,
    PLAN_DEEP_PROBE,
    PLAN_HINT,
    PLAN_SWITCH,
)

LEGACY_ACTIONS: tuple[InterviewAction, ...] = (
    DEEPEN_TECHNICAL,
    SWITCH_DIMENSION,
    GIVE_HINT,
    SKIP_TO_NEXT,
)

# ``ACTIONS`` keeps its old 4-arm shape so legacy callers that iterate
# over it (reporting, tests) keep working. The bandit itself switches
# between template arms and legacy arms based on ``policy_mode``; see
# :mod:`app.engine.workflow.nodes.director_sample`.
ACTIONS: tuple[InterviewAction, ...] = LEGACY_ACTIONS

ACTIONS_BY_ID: dict[str, InterviewAction] = {
    a.id: a for a in (*TEMPLATE_ACTIONS, *LEGACY_ACTIONS)
}


# Map from legacy strategy-family id -> canonical template-arm id so
# older bandit rehydrate rows can be replayed into the new namespace
# when ``rehydrate_bandit_on_start`` is on.
ALIAS_MAP: dict[str, str] = {
    DEEPEN_TECHNICAL.id: PLAN_ADAPTIVE.id,
    SWITCH_DIMENSION.id: PLAN_SWITCH.id,
    GIVE_HINT.id: PLAN_HINT.id,
    SKIP_TO_NEXT.id: PLAN_SIMPLE.id,
}


def get_action(action_id: str) -> InterviewAction:
    return ACTIONS_BY_ID.get(action_id, PLAN_ADAPTIVE)


def template_id_for_action(action_id: str) -> str:
    """Return the canonical template-arm id for a given action id.

    Passes template-arm ids through unchanged; maps legacy
    strategy-family ids via :data:`ALIAS_MAP`; falls back to
    ``plan_adaptive`` for unknown ids.
    """
    if action_id in {a.id for a in TEMPLATE_ACTIONS}:
        return action_id
    return ALIAS_MAP.get(action_id, PLAN_ADAPTIVE.id)
