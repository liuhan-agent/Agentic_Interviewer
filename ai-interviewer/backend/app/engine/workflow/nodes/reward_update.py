"""Reward-update node: apply bandit feedback after verification."""
from __future__ import annotations

import time
from typing import Any

from app.core.logging import get_logger
from app.core.tracer import get_tracer
from app.engine.workflow.policy_context import policy_context_keys
from app.engine.workflow.state import InterviewState
from app.ml.rl.action_space import ALIAS_MAP
from app.ml.rl.reward_fn import immediate_reward
from app.ml.rl.thompson import get_bandit

log = get_logger(__name__)

_NON_SCORING_INTENTS = {"empty", "clarification", "repeat", "too_short", "skipped"}


def _reward_context_keys(
    state: InterviewState,
    action: dict[str, Any],
    dimension: str,
) -> list[str]:
    keys = (
        state.get("policy_context_keys")
        or action.get("policy_context_keys")
        or policy_context_keys(state.get("job_spec") or {}, dimension)
    )
    return [str(key) for key in keys if str(key or "").strip()]


def reward_update_node(state: InterviewState) -> dict[str, Any]:
    """Apply immediate reward using the post-verification evaluation."""
    node_started_at = time.perf_counter()
    answer_turn_idx = max(0, int(state.get("turn_idx", 0)) - 1)
    evaluation = state.get("evaluation") or {}
    action = state.get("selected_action") or {}
    action_id = action.get("id")
    if not action_id:
        return {}
    if state.get("current_answer_intent") in _NON_SCORING_INTENTS:
        log.info(
            "reward_update skipped for answer_intent=%s",
            state.get("current_answer_intent"),
        )
        return {}
    if evaluation.get("source") == "fallback" or evaluation.get("fallback_reason"):
        return {}

    question = state.get("current_question") or {}
    dimension = (
        question.get("dimension")
        or state.get("current_dimension")
        or "unknown"
    )
    contract = state.get("current_contract") or question.get("contract")
    reward = immediate_reward(evaluation=evaluation, contract=contract)
    keys = _reward_context_keys(state, action, str(dimension))

    bandit = get_bandit()
    for context_key in keys:
        bandit.update(context_key, str(action_id), reward)
    alias = ALIAS_MAP.get(str(action_id))
    if alias and alias != action_id:
        for context_key in keys:
            bandit.update(context_key, alias, reward)

    update = {
        "messages": [
            {
                "role": "system",
                "kind": "reward_update",
                "action_id": action_id,
                "context_keys": keys,
                "immediate_reward": reward,
            }
        ]
    }
    log.info(
        "reward_update dim=%s action=%s reward=%.2f contexts=%d",
        dimension,
        action_id,
        reward,
        len(keys),
    )
    try:
        get_tracer().trace_node_event(
            {**state, **update},
            node="reward_update",
            payload={
                "dimension": dimension,
                "action_id": action_id,
                "context_keys": keys,
                "immediate_reward": reward,
                "immediate_reward_applied": True,
                "elapsed_ms": int((time.perf_counter() - node_started_at) * 1000),
            },
            logical_turn_idx=answer_turn_idx,
        )
    except Exception as e:  # pragma: no cover - side channel
        log.warning("reward_update tracer side-channel failed: %s", e)
    return update
