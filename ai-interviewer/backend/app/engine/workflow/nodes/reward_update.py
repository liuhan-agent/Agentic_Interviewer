"""Reward-update node: apply bandit feedback after verification."""
from __future__ import annotations

import hashlib
import time
import uuid
from typing import Any

from app.core.logging import get_logger
from app.core.timing import get_latest_db_write_ms
from app.core.tracer import get_tracer
from app.engine.workflow.policy_context import policy_context_keys
from app.engine.workflow.state import InterviewState
from app.ml.rl.action_space import ALIAS_MAP
from app.ml.rl.reward_fn import immediate_reward
from app.ml.rl.thompson import get_bandit
from app.models import get_session
from app.models.strategy_memory import StrategyMemoryUsage

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

    _record_strategy_memory_usage(
        state=state,
        question=question,
        evaluation=evaluation,
        action=action,
        context_keys=keys,
        reward=reward,
        turn_idx=answer_turn_idx,
    )

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
    payload: dict[str, Any] = {
        "dimension": dimension,
        "action_id": action_id,
        "context_keys": keys,
        "immediate_reward": reward,
        "immediate_reward_applied": True,
        "elapsed_ms": int((time.perf_counter() - node_started_at) * 1000),
    }
    db_write_ms = get_latest_db_write_ms()
    if db_write_ms is not None:
        payload["db_write_ms"] = int(db_write_ms)
    try:
        get_tracer().trace_node_event(
            {**state, **update},
            node="reward_update",
            payload=payload,
            logical_turn_idx=answer_turn_idx,
        )
    except Exception as e:  # pragma: no cover - side channel
        log.warning("reward_update tracer side-channel failed: %s", e)
    return update


def _record_strategy_memory_usage(
    *,
    state: InterviewState,
    question: dict[str, Any],
    evaluation: dict[str, Any],
    action: dict[str, Any],
    context_keys: list[str],
    reward: float,
    turn_idx: int,
) -> None:
    refs = [
        ref
        for ref in (question.get("strategy_memory_refs") or [])
        if isinstance(ref, dict) and _strategy_ref_id(ref)
    ]
    if not refs:
        return

    try:
        keys = context_keys or [None]
        with get_session() as session:
            for ref in refs:
                strategy_id = _strategy_ref_id(ref)
                if not strategy_id:
                    continue
                for context_key in keys:
                    session.add(
                        StrategyMemoryUsage(
                            id=f"usage:{uuid.uuid4().hex}",
                            strategy_id=str(strategy_id),
                            session_id=str(state.get("session_id") or ""),
                            turn_idx=turn_idx,
                            trace_id=_optional_str(state.get("trace_id")),
                            context_key=_optional_str(context_key),
                            action_id=_optional_str(action.get("id")),
                            plan_template=_optional_str(action.get("plan_template")),
                            question_id=_optional_str(question.get("id")),
                            question_text_hash=_question_text_hash(
                                question.get("question")
                            ),
                            score=_optional_float(evaluation.get("score")),
                            passed=_optional_bool(evaluation.get("passed")),
                            immediate_reward=reward,
                            verifier_overruled=bool(
                                evaluation.get("verifier_forced_refine")
                                or evaluation.get("verifier_overruled")
                            ),
                        )
                    )
    except Exception as e:  # pragma: no cover - attribution is best-effort
        log.warning("strategy memory usage attribution failed: %s", e)


def _strategy_ref_id(ref: dict[str, Any]) -> str | None:
    for key in ("id", "memory_key", "slug"):
        value = _optional_str(ref.get(key))
        if value:
            return value
    return None


def _question_text_hash(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    digest = hashlib.sha1(text.encode("utf-8"), usedforsecurity=False).hexdigest()
    return f"sha1:{digest}"


def _optional_str(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _optional_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _optional_bool(value: Any) -> bool | None:
    if value is None:
        return None
    return bool(value)
