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
    formal_turn_idx = _fact_turn_idx(state, answer_turn_idx)
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
    updated_action_ids = [str(action_id)]
    if alias and alias != action_id:
        updated_action_ids.append(alias)
        for context_key in keys:
            bandit.update(context_key, alias, reward)

    _record_strategy_learning_reward(
        state=state,
        evaluation=evaluation,
        action_id=str(action_id),
        context_keys=keys,
        reward=reward,
        turn_idx=formal_turn_idx,
    )
    strategy_memory_attribution = _record_strategy_memory_usage(
        state=state,
        question=question,
        evaluation=evaluation,
        action=action,
        context_keys=keys,
        reward=reward,
        turn_idx=answer_turn_idx,
    )
    skill_attribution = _record_skill_usage(
        state=state,
        question=question,
        evaluation=evaluation,
        reward=reward,
        turn_idx=formal_turn_idx,
    )
    question_attribution = _backfill_question_usage_result(
        state=state,
        question=question,
        evaluation=evaluation,
        reward=reward,
        turn_idx=formal_turn_idx,
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
        "reward_summary": {
            "immediate_reward": reward,
            "score": _optional_float(evaluation.get("score")),
            "passed": _optional_bool(evaluation.get("passed")),
            "verifier_overruled": _verifier_overruled(evaluation),
            "logical_turn_idx": answer_turn_idx,
            "formal_turn_idx": formal_turn_idx,
        },
        "bandit_update": {
            "action_id": str(action_id),
            "alias": alias if alias and alias != action_id else None,
            "action_ids": updated_action_ids,
            "context_keys": keys,
            "updated_arm_count": len(keys) * len(updated_action_ids),
        },
        "strategy_memory_attribution": strategy_memory_attribution,
        "question_attribution": question_attribution,
        "skill_attribution": skill_attribution,
        "persistence": {
            "failed": [
                *strategy_memory_attribution.get("failed", []),
                *question_attribution.get("failed", []),
                *skill_attribution.get("failed", []),
            ],
        },
        "elapsed_ms": int((time.perf_counter() - node_started_at) * 1000),
    }
    db_write_ms = get_latest_db_write_ms()
    if db_write_ms is not None:
        payload["db_write_ms"] = int(db_write_ms)
        payload["persistence"]["db_write_ms"] = int(db_write_ms)
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
) -> dict[str, Any]:
    refs = [
        ref
        for ref in (question.get("strategy_memory_refs") or [])
        if isinstance(ref, dict) and _strategy_ref_id(ref)
    ]
    summary: dict[str, Any] = {
        "ref_count": len(refs),
        "usage_count": 0,
        "strategy_ids": [],
        "context_keys": list(context_keys or []),
        "failed": [],
    }
    if not refs:
        return summary

    try:
        keys = context_keys or [None]
        with get_session() as session:
            for ref in refs:
                strategy_id = _strategy_ref_id(ref)
                if not strategy_id:
                    continue
                if strategy_id not in summary["strategy_ids"]:
                    summary["strategy_ids"].append(str(strategy_id))
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
                    summary["usage_count"] += 1
    except Exception as e:  # pragma: no cover - attribution is best-effort
        log.warning("strategy memory usage attribution failed: %s", e)
        summary["failed"].append(_failure_summary("strategy_memory_usage", e))
    return summary


def _record_skill_usage(
    *,
    state: InterviewState,
    question: dict[str, Any],
    evaluation: dict[str, Any],
    reward: float,
    turn_idx: int,
) -> dict[str, Any]:
    refs = [
        ref
        for ref in _skill_refs(question)
        if isinstance(ref, dict) and _skill_ref_id(ref)
    ]
    summary: dict[str, Any] = {
        "ref_count": len(refs),
        "usage_count": 0,
        "skill_ids": [],
        "skill_context_key": None,
        "failed": [],
    }
    if not refs:
        return summary

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
    summary["skill_context_key"] = context_key

    try:
        with get_session() as session:
            for idx, ref in enumerate(refs, 1):
                skill_id = _skill_ref_id(ref)
                if not skill_id:
                    continue
                if skill_id not in summary["skill_ids"]:
                    summary["skill_ids"].append(str(skill_id))
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
                summary["usage_count"] += 1
    except Exception as e:  # pragma: no cover - attribution is best-effort
        log.warning("skill usage attribution failed: %s", e)
        summary["failed"].append(_failure_summary("skill_usage", e))
    return summary


def _backfill_question_usage_result(
    *,
    state: InterviewState,
    question: dict[str, Any],
    evaluation: dict[str, Any],
    reward: float,
    turn_idx: int,
) -> dict[str, Any]:
    variant_ids = _injected_primary_variant_ids(question)
    items = _question_items(question)
    summary: dict[str, Any] = {
        "candidate_count": len(items),
        "rewarded_count": 0,
        "selected_variant_ids": sorted(variant_ids),
        "rewarded_variant_ids": [],
        "matched_usage_ids": [],
        "skipped": _question_attribution_skips(items, variant_ids),
        "failed": [],
    }
    if not variant_ids:
        return summary
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
                summary["rewarded_count"] += 1
                summary["matched_usage_ids"].append(row.id)
                if row.variant_id not in summary["rewarded_variant_ids"]:
                    summary["rewarded_variant_ids"].append(row.variant_id)
    except Exception as e:  # pragma: no cover - attribution is best-effort
        log.warning("question usage reward backfill failed: %s", e)
        summary["failed"].append(_failure_summary("question_usage", e))
    return summary


def _injected_primary_variant_ids(question: dict[str, Any]) -> set[str]:
    items = _question_items(question)
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


def _question_items(question: dict[str, Any]) -> list[Any]:
    artifacts = question.get("selection_artifacts") or {}
    items = artifacts.get("question_items") if isinstance(artifacts, dict) else None
    return list(items) if isinstance(items, list) else []


def _question_attribution_skips(
    items: list[Any],
    rewarded_variant_ids: set[str],
) -> list[dict[str, Any]]:
    skipped: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        variant_id = _optional_str(item.get("variant_id"))
        rank = _optional_int(item.get("rank"))
        mode = str(item.get("question_selector_mode") or "structured_primary")
        injected = bool(item.get("injected"))
        reason: str | None = None
        if mode != "structured_primary":
            reason = "not_structured_primary"
        elif not injected:
            reason = "not_injected"
        elif rank != 1:
            reason = "not_rank_one"
        elif not variant_id:
            reason = "missing_variant_id"
        elif variant_id not in rewarded_variant_ids:
            reason = "variant_not_selected"
        if reason:
            skipped.append(
                {
                    "seed_id": _optional_str(item.get("seed_id")),
                    "variant_id": variant_id,
                    "rank": rank,
                    "injected": injected,
                    "question_selector_mode": mode,
                    "reason": reason,
                }
            )
    return skipped


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


def _verifier_overruled(evaluation: dict[str, Any]) -> bool:
    return bool(
        evaluation.get("verifier_forced_refine")
        or evaluation.get("verifier_overruled")
    )


def _failure_summary(target: str, exc: Exception) -> dict[str, str]:
    return {
        "target": target,
        "error_type": type(exc).__name__,
        "message": str(exc)[:240],
    }


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
