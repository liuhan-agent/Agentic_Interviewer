"""Reward-update node: apply bandit feedback after verification."""
from __future__ import annotations

import hashlib
import time
import uuid
from typing import Any

from sqlalchemy import select

from app.core.logging import get_logger
from app.core.settings import get_settings
from app.core.timing import get_latest_db_write_ms
from app.core.tracer import get_tracer
from app.engine.workflow.policy_context import policy_context_keys
from app.engine.workflow.state import InterviewState
from app.ml.rl.action_space import ALIAS_MAP
from app.ml.rl.reward_fn import immediate_reward
from app.ml.rl.thompson import get_bandit
from app.models import get_session
from app.models.question_bank import QuestionUsage
from app.models.skill_playbook import SkillUsage
from app.models.strategy_memory import StrategyMemoryUsage
from app.services.question_fit_profile import resolve_question_bank_tags
from app.services.skill_usage_stats import skill_usage_context_key
from app.services.strategy_learning_facts import (
    apply_bandit_posterior_update,
    upsert_interview_turn,
)

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

    _record_strategy_learning_reward(
        state=state,
        evaluation=evaluation,
        action_id=str(action_id),
        context_keys=keys,
        reward=reward,
        turn_idx=_fact_turn_idx(state, answer_turn_idx),
    )
    _record_strategy_memory_usage(
        state=state,
        question=question,
        evaluation=evaluation,
        action=action,
        context_keys=keys,
        reward=reward,
        turn_idx=answer_turn_idx,
    )
    _record_skill_usage(
        state=state,
        question=question,
        evaluation=evaluation,
        reward=reward,
        turn_idx=_fact_turn_idx(state, answer_turn_idx),
    )
    _backfill_question_usage_result(
        state=state,
        question=question,
        evaluation=evaluation,
        reward=reward,
        turn_idx=_fact_turn_idx(state, answer_turn_idx),
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


def _record_strategy_learning_reward(
    *,
    state: InterviewState,
    evaluation: dict[str, Any],
    action_id: str,
    context_keys: list[str],
    reward: float,
    turn_idx: int,
) -> None:
    try:
        s = get_settings()
        alias = ALIAS_MAP.get(action_id)
        action_ids = [action_id]
        if alias and alias != action_id:
            action_ids.append(alias)

        with get_session() as session:
            for context_key in context_keys:
                for aid in action_ids:
                    apply_bandit_posterior_update(
                        session,
                        context_key=context_key,
                        action_id=aid,
                        reward=reward,
                        reward_kind="immediate",
                        session_id=_optional_str(state.get("session_id")),
                        turn_idx=turn_idx,
                        default_alpha=float(s.bandit_default_alpha),
                        default_beta=float(s.bandit_default_beta),
                    )
            upsert_interview_turn(
                session,
                session_id=str(state.get("session_id") or ""),
                turn_idx=turn_idx,
                trace_id=_optional_str(state.get("trace_id")),
                dimension=str(
                    ((state.get("current_question") or {}).get("dimension"))
                    or state.get("current_dimension")
                    or "unknown"
                ),
                job_level=_optional_str((state.get("job_spec") or {}).get("level")),
                evaluation=dict(evaluation),
                failure_categories=_failure_categories(evaluation),
                score=_optional_float(evaluation.get("score")),
                passed=_optional_bool(evaluation.get("passed")),
                immediate_reward=reward,
            )
    except Exception as e:  # pragma: no cover - fact persistence is side-channel
        log.warning("strategy learning reward persistence failed: %s", e)


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


def _record_skill_usage(
    *,
    state: InterviewState,
    question: dict[str, Any],
    evaluation: dict[str, Any],
    reward: float,
    turn_idx: int,
) -> None:
    refs = [
        ref
        for ref in _skill_refs(question)
        if isinstance(ref, dict) and _skill_ref_id(ref)
    ]
    if not refs:
        return

    dimension = str(
        question.get("dimension")
        or state.get("current_dimension")
        or "general"
    )
    job_level = _optional_str((state.get("job_spec") or {}).get("level")) or "mid"
    role = _skill_context_role(state)
    probe_intent = _optional_str(question.get("probe_intent")) or "none"
    context_key = skill_usage_context_key(
        role=role,
        job_level=job_level,
        dimension=dimension,
        probe_intent=probe_intent,
    )

    try:
        with get_session() as session:
            for idx, ref in enumerate(refs, 1):
                skill_id = _skill_ref_id(ref)
                if not skill_id:
                    continue
                session.add(
                    SkillUsage(
                        id=f"skill-usage:{uuid.uuid4().hex}",
                        skill_id=str(skill_id),
                        session_id=str(state.get("session_id") or ""),
                        turn_idx=turn_idx,
                        trace_id=_optional_str(state.get("trace_id")),
                        skill_context_key=context_key,
                        role=role,
                        job_level=job_level,
                        dimension=dimension,
                        probe_intent=probe_intent,
                        rank=_optional_int(ref.get("rank")) or idx,
                        match_score=_optional_float(ref.get("match_score")) or 0.0,
                        match_reasons=_string_list(ref.get("match_reasons")),
                        injected=True,
                        evaluator_visibility=bool(ref.get("evaluator_visibility")),
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
        log.warning("skill usage attribution failed: %s", e)


def _backfill_question_usage_result(
    *,
    state: InterviewState,
    question: dict[str, Any],
    evaluation: dict[str, Any],
    reward: float,
    turn_idx: int,
) -> None:
    variant_ids = _injected_primary_variant_ids(question)
    if not variant_ids:
        return
    try:
        with get_session() as session:
            rows = list(
                session.scalars(
                    select(QuestionUsage)
                    .where(QuestionUsage.session_id == str(state.get("session_id") or ""))
                    .where(QuestionUsage.turn_idx == turn_idx)
                    .where(QuestionUsage.question_selector_mode == "structured_primary")
                    .where(QuestionUsage.injected.is_(True))
                    .where(QuestionUsage.rank == 1)
                )
            )
            for row in rows:
                if row.variant_id not in variant_ids:
                    continue
                row.score = _optional_float(evaluation.get("score"))
                row.passed = _optional_bool(evaluation.get("passed"))
                row.immediate_reward = reward
    except Exception as e:  # pragma: no cover - attribution is best-effort
        log.warning("question usage reward backfill failed: %s", e)


def _injected_primary_variant_ids(question: dict[str, Any]) -> set[str]:
    artifacts = question.get("selection_artifacts") or {}
    items = artifacts.get("question_items") if isinstance(artifacts, dict) else None
    if not isinstance(items, list):
        return set()
    variant_ids: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        if not bool(item.get("injected")):
            continue
        if int(item.get("rank") or 0) != 1:
            continue
        mode = str(item.get("question_selector_mode") or "structured_primary")
        if mode != "structured_primary":
            continue
        variant_id = _optional_str(item.get("variant_id"))
        if variant_id:
            variant_ids.add(variant_id)
    return variant_ids


def _skill_refs(question: dict[str, Any]) -> list[Any]:
    artifacts = question.get("selection_artifacts") or {}
    skills = artifacts.get("skills") if isinstance(artifacts, dict) else None
    refs = skills.get("refs") if isinstance(skills, dict) else None
    return list(refs) if isinstance(refs, list) else []


def _skill_ref_id(ref: dict[str, Any]) -> str | None:
    for key in ("id", "skill_id", "slug", "filename"):
        value = _optional_str(ref.get(key))
        if value:
            return value
    return None


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


def _skill_context_role(state: InterviewState) -> str:
    try:
        _direction_tags, role_tags = resolve_question_bank_tags(
            job_spec=state.get("job_spec") or {},
            runtime_config=state.get("runtime_config") or {},
        )
    except Exception:
        role_tags = []
    for role in _string_list(role_tags):
        if role and role != "general":
            return role
    return "general"


def _fact_turn_idx(state: InterviewState, fallback: int) -> int:
    raw = state.get("formal_turn_idx")
    if raw is None:
        return int(fallback)
    try:
        return max(0, int(raw) - 1)
    except (TypeError, ValueError):
        return int(fallback)


def _failure_categories(evaluation: dict[str, Any]) -> list[str]:
    raw = evaluation.get("failure_categories")
    if not isinstance(raw, list):
        return []
    return [str(value) for value in raw if isinstance(value, str) and value.strip()]


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


def _optional_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_bool(value: Any) -> bool | None:
    if value is None:
        return None
    return bool(value)


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item or "").strip()]
