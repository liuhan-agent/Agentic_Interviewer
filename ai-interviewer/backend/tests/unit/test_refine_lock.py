"""Regression tests for the "refine = same dimension" semantic.

The router (``routers.route_after_eval``) documents refine as
"same dimension, one more attempt". It is enforced by a two-step
handshake:

1. ``refine_followup_node`` sets ``state.refine_mode = True``.
2. ``director_sample_node`` reads that flag and masks out any arm
   that would rotate the interview away from the current dimension
   (``switch_dimension`` / ``skip_to_next`` in the legacy space,
   ``plan_switch`` in the template space).

These tests pin that contract across *both* policy modes so a
future refactor that drops the flag or widens the mask fails here
instead of silently regressing the interview behaviour.
"""
from __future__ import annotations

import random

import pytest

from app.engine.workflow.nodes.director_sample import director_sample_node
from app.engine.workflow.nodes.refine_followup import refine_followup_node
from app.ml.rl import thompson as thompson_mod
from app.ml.rl.action_space import (
    DEEPEN_TECHNICAL,
    GIVE_HINT,
    PLAN_ADAPTIVE,
    PLAN_DEEP_PROBE,
    PLAN_HINT,
    PLAN_SIMPLE,
    PLAN_SWITCH,
    SKIP_TO_NEXT,
    SWITCH_DIMENSION,
)

# Per-policy test matrix: which arm to bias the bandit toward (the
# dimension-switching one) and which arms the refine mask must leave
# available. ``switch_id`` must NOT appear in ``allowed_under_refine``.
_POLICY_MATRIX = {
    "template": {
        "switch_id": PLAN_SWITCH.id,
        "allowed_under_refine": {
            PLAN_ADAPTIVE.id,
            PLAN_DEEP_PROBE.id,
            PLAN_HINT.id,
        },
    },
    "legacy": {
        "switch_id": SWITCH_DIMENSION.id,
        "allowed_under_refine": {DEEPEN_TECHNICAL.id, GIVE_HINT.id},
    },
}


def _make_state(policy_mode: str) -> dict:
    return {
        "session_id": "sess-refine",
        "trace_id": "trace-refine",
        "job_spec": {"level": "senior"},
        "dimensions": ["technical_depth", "system_design", "communication"],
        "dimension_status": {
            "technical_depth": "active",
            "system_design": "pending",
            "communication": "pending",
        },
        "current_dimension": "technical_depth",
        "turn_idx": 1,
        "evaluation": {
            "passed": False,
            "recommended_next": "refine",
            "weaknesses": ["missed concurrency trade-off"],
        },
        "qa_history": [],
        "refine_mode": False,
        # Pin the policy mode explicitly so tests don't drift when the
        # global Settings default changes.
        "runtime_config": {"policy_mode": policy_mode},
    }


def _install_deterministic_bandit(
    monkeypatch,
    biased_action: str,
    all_arms: set[str],
) -> None:
    """Force the bandit to *prefer* a dimension-switching arm unless masked.

    We pre-inflate the switch arm's posterior and zero-out everything
    else so, under zero-exploration-rate Thompson sampling, the
    director would normally pick the switch arm. The point of the
    test is that the refine mask overrides that preference.
    """
    bandit = thompson_mod.ThompsonBandit(
        exploration_rate=0.0, rng=random.Random(0)
    )
    ctx_key = "senior:technical_depth"
    for _ in range(50):
        bandit.update(ctx_key, biased_action, reward=1.0)
    for arm in all_arms - {biased_action}:
        for _ in range(50):
            bandit.update(ctx_key, arm, reward=0.0)

    monkeypatch.setattr(thompson_mod, "_singleton", bandit, raising=False)


def test_refine_followup_sets_refine_mode_flag():
    state = _make_state(policy_mode="template")
    out = refine_followup_node(state)  # type: ignore[arg-type]
    assert out["refine_mode"] is True


@pytest.mark.parametrize("policy_mode", ["template", "legacy"])
def test_director_with_refine_mode_locks_dimension(monkeypatch, policy_mode):
    """Even with a bandit biased toward the switch arm, refine wins."""
    matrix = _POLICY_MATRIX[policy_mode]
    switch_id = matrix["switch_id"]
    allowed = matrix["allowed_under_refine"]

    # The bandit universe includes the switch arm *and* every arm the
    # mask is supposed to keep available, so the comparison is fair.
    _install_deterministic_bandit(
        monkeypatch,
        biased_action=switch_id,
        all_arms=allowed | {switch_id},
    )

    state = _make_state(policy_mode=policy_mode)
    state.update(refine_followup_node(state))  # type: ignore[arg-type]
    assert state["refine_mode"] is True

    out = director_sample_node(state)  # type: ignore[arg-type]
    chosen = out["selected_action"]["id"]

    assert chosen in allowed, (
        f"refine lock broken in policy_mode={policy_mode}: director "
        f"picked {chosen} despite refine_mode=True"
    )
    # The legacy policy also masks ``skip_to_next``; its template
    # equivalent (``plan_simple``) is *not* masked but must not be the
    # biased switch id. Capture both invariants in one assertion.
    if policy_mode == "legacy":
        assert chosen not in {SWITCH_DIMENSION.id, SKIP_TO_NEXT.id}
    else:
        assert chosen != PLAN_SWITCH.id
        # ``plan_simple`` is allowed but mapped out of the refine
        # mask for template mode — assert that too.
        assert chosen != PLAN_SIMPLE.id
    assert out["current_dimension"] == "technical_depth"
    # Consume-after-use: the lock is a one-shot that must clear so the
    # next cycle is free to sample normally.
    assert out["refine_mode"] is False
    assert out["selected_action"]["refine_locked"] is True


@pytest.mark.parametrize("policy_mode", ["template", "legacy"])
def test_director_without_refine_mode_may_switch(monkeypatch, policy_mode):
    """Sanity check: without refine_mode the bandit is free to switch."""
    matrix = _POLICY_MATRIX[policy_mode]
    switch_id = matrix["switch_id"]
    allowed = matrix["allowed_under_refine"]

    _install_deterministic_bandit(
        monkeypatch,
        biased_action=switch_id,
        all_arms=allowed | {switch_id},
    )

    state = _make_state(policy_mode=policy_mode)
    state["refine_mode"] = False

    out = director_sample_node(state)  # type: ignore[arg-type]
    chosen = out["selected_action"]["id"]
    assert chosen == switch_id


def test_director_uses_global_policy_when_direction_context_is_cold(monkeypatch):
    bandit = thompson_mod.ThompsonBandit(
        exploration_rate=0.0, rng=random.Random(0)
    )
    global_ctx = "senior:system_design"
    direction_ctx = "java_backend:senior:system_design"
    for _ in range(40):
        bandit.update(global_ctx, PLAN_DEEP_PROBE.id, reward=1.0)
    for arm in {PLAN_ADAPTIVE.id, PLAN_HINT.id, PLAN_SIMPLE.id, PLAN_SWITCH.id}:
        for _ in range(40):
            bandit.update(global_ctx, arm, reward=0.0)
    monkeypatch.setattr(thompson_mod, "_singleton", bandit, raising=False)

    state = {
        "session_id": "sess-dir-policy",
        "trace_id": "trace-dir-policy",
        "job_spec": {
            "level": "senior",
            "interview_direction": "java_backend",
            "rubric_dimensions": ["system_design"],
        },
        "dimensions": ["system_design"],
        "dimension_status": {"system_design": "pending"},
        "current_dimension": None,
        "turn_idx": 0,
        "qa_history": [],
        "refine_mode": False,
        "runtime_config": {"policy_mode": "template"},
    }

    out = director_sample_node(state)  # type: ignore[arg-type]

    assert out["selected_action"]["id"] == PLAN_DEEP_PROBE.id
    assert out["selected_action"]["diagnostics"]["context_key"] == global_ctx
    assert out["policy_context_keys"] == [direction_ctx, global_ctx]
