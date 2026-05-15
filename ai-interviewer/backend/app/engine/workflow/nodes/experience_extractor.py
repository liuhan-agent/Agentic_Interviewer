"""Post-interview experience extraction node.

Runs after ``final_report_node`` to analyse the completed session and
persist reusable strategy signals. Promotion into active strategy
memory is handled by a separate aggregation job so a single session
does not directly mutate global strategy behaviour.

Two extraction paths run in sequence:

1. **QA-pattern extraction** — scans ``qa_history`` for notable patterns
   (e.g. a dimension where ``give_hint`` rescued a failing candidate,
   or where ``deepen_technical`` consistently produced high scores).

2. **Bandit-posterior extraction** — reads the current Thompson Sampling
   posteriors and records signal rows for ``(context_key, action_id)``
   arms whose mean reward has crossed a confidence threshold.
"""
from __future__ import annotations

import hashlib
from typing import Any

from app.core.logging import get_logger
from app.core.settings import get_settings
from app.core.tracer import get_tracer
from app.engine.workflow.state import InterviewState
from app.ml.rl.action_space import ACTIONS_BY_ID
from app.ml.rl.thompson import get_bandit
from app.models import get_session
from app.models.strategy_memory import StrategySignal
from app.tasks.dream_tasks import increment_session_count

log = get_logger(__name__)


def _safe_key_part(value: Any) -> str:
    return str(value or "unknown").strip().replace(" ", "_") or "unknown"


def _extract_qa_patterns(state: InterviewState) -> list[dict[str, Any]]:
    """Identify notable patterns from this session's QA history."""
    qa_history = state.get("qa_history", [])
    if len(qa_history) < 2:
        return []

    s = get_settings()
    patterns: list[dict[str, Any]] = []
    dim_turns: dict[str, list[dict[str, Any]]] = {}
    for qa in qa_history:
        dim = qa.get("dimension", "unknown")
        dim_turns.setdefault(dim, []).append(qa)

    job_level = (state.get("job_spec") or {}).get("level", "mid")
    spread_threshold = float(s.experience_score_spread_threshold)

    for dim, turns in dim_turns.items():
        if len(turns) < 2:
            continue

        scores = [
            float((t.get("evaluation") or {}).get("score", 0))
            for t in turns
        ]
        actions = [t.get("selected_action", "") for t in turns]

        if len(scores) >= 2 and scores[-1] - scores[0] >= spread_threshold:
            recovery_action = actions[-1] if actions else "unknown"
            patterns.append({
                "type": "score_recovery",
                "dimension": dim,
                "job_level": job_level,
                "recovery_action": recovery_action,
                "score_before": round(scores[0], 2),
                "score_after": round(scores[-1], 2),
                "score_delta": round(scores[-1] - scores[0], 2),
                "detail": (
                    f"Candidate recovered from {scores[0]:.1f} to {scores[-1]:.1f} "
                    f"in {dim} after action '{recovery_action}'."
                ),
            })

        if len(scores) >= 2 and scores[0] - scores[-1] >= spread_threshold:
            failing_action = actions[-1] if actions else "unknown"
            patterns.append({
                "type": "score_decline",
                "dimension": dim,
                "job_level": job_level,
                "failing_action": failing_action,
                "score_before": round(scores[0], 2),
                "score_after": round(scores[-1], 2),
                "score_delta": round(scores[-1] - scores[0], 2),
                "detail": (
                    f"Score declined from {scores[0]:.1f} to {scores[-1]:.1f} "
                    f"in {dim} after action '{failing_action}'."
                ),
            })

        hint_turns = [
            t for t in turns if t.get("selected_action") == "give_hint"
        ]
        if hint_turns:
            hint_scores = [
                float((t.get("evaluation") or {}).get("score", 0))
                for t in hint_turns
            ]
            avg_hint = sum(hint_scores) / len(hint_scores) if hint_scores else 0
            if avg_hint >= 7.0:
                patterns.append({
                    "type": "hint_effective",
                    "dimension": dim,
                    "job_level": job_level,
                    "avg_hint_score": round(avg_hint, 2),
                    "detail": (
                        f"'give_hint' was effective in {dim} "
                        f"(avg score {avg_hint:.1f} across {len(hint_turns)} uses)."
                    ),
                })

    return patterns


def _extract_bandit_insights() -> list[dict[str, Any]]:
    """Query bandit posteriors for arms with strong evidence."""
    s = get_settings()
    min_obs = float(s.experience_min_observations)
    high_mean = float(s.experience_high_reward_mean)
    low_mean = float(s.experience_low_reward_mean)

    bandit = get_bandit()
    insights: list[dict[str, Any]] = []

    for (ctx_key, action_id), params in bandit.priors.items():
        total = params.alpha + params.beta - 2.0
        if total < min_obs:
            continue

        mean = params.mean()
        if mean >= high_mean:
            action = ACTIONS_BY_ID.get(action_id)
            action_label = action.label if action else action_id
            insights.append({
                "type": "high_reward_arm",
                "context_key": ctx_key,
                "action_id": action_id,
                "action_label": action_label,
                "mean_reward": round(mean, 3),
                "observations": int(total),
                "detail": (
                    f"Action '{action_label}' in context '{ctx_key}' has "
                    f"mean reward {mean:.3f} over {int(total)} observations."
                ),
            })

        if mean <= low_mean and total >= min_obs:
            action = ACTIONS_BY_ID.get(action_id)
            action_label = action.label if action else action_id
            insights.append({
                "type": "low_reward_arm",
                "context_key": ctx_key,
                "action_id": action_id,
                "action_label": action_label,
                "mean_reward": round(mean, 3),
                "observations": int(total),
                "detail": (
                    f"Action '{action_label}' in context '{ctx_key}' has "
                    f"low mean reward {mean:.3f} over {int(total)} observations. "
                    f"Consider avoiding this action in similar contexts."
                ),
            })

    return insights


def strategy_memory_key_for_pattern(pattern: dict[str, Any]) -> str:
    ptype = _safe_key_part(pattern.get("type"))
    dim = _safe_key_part(pattern.get("dimension"))
    job_level = _safe_key_part(pattern.get("job_level", "mid"))
    if ptype == "score_recovery":
        action = _safe_key_part(pattern.get("recovery_action"))
        return f"qa:{ptype}:{job_level}:{dim}:{action}"
    if ptype == "score_decline":
        action = _safe_key_part(pattern.get("failing_action"))
        return f"qa:{ptype}:{job_level}:{dim}:{action}"
    if ptype == "hint_effective":
        return f"qa:{ptype}:{job_level}:{dim}"
    return f"qa:{ptype}:{job_level}:{dim}"


def strategy_memory_key_for_insight(insight: dict[str, Any]) -> str:
    itype = _safe_key_part(insight.get("type"))
    ctx = _safe_key_part(insight.get("context_key"))
    action_id = _safe_key_part(insight.get("action_id"))
    return f"bandit:{itype}:{ctx}:{action_id}"


def _signal_id(signal_key: str) -> str:
    digest = hashlib.sha1(signal_key.encode("utf-8"), usedforsecurity=False).hexdigest()
    return f"signal:{digest[:24]}"


def _signal_payload_from_qa_pattern(
    state: InterviewState,
    pattern: dict[str, Any],
) -> dict[str, Any]:
    ptype = str(pattern.get("type") or "unknown")
    action_id = (
        pattern.get("recovery_action")
        or pattern.get("failing_action")
        or ("give_hint" if ptype == "hint_effective" else None)
    )
    group_key = strategy_memory_key_for_pattern(pattern)
    session_id = str(state.get("session_id") or "unknown")
    return {
        "signal_key": f"{session_id}:{group_key}",
        "group_key": group_key,
        "session_id": session_id,
        "turn_idx": int(state.get("turn_idx", len(state.get("qa_history", [])))),
        "dimension": str(pattern.get("dimension") or "unknown"),
        "job_level": str(pattern.get("job_level") or "mid"),
        "action_id": str(action_id or ""),
        "plan_template": str(action_id or "") or None,
        "probe_intent": None,
        "failure_categories": [],
        "score_before": _optional_float(pattern.get("score_before")),
        "score_after": _optional_float(
            pattern.get("score_after") or pattern.get("avg_hint_score")
        ),
        "score_delta": _optional_float(pattern.get("score_delta")),
        "immediate_reward": None,
        "verifier_overruled": False,
        "signal_type": ptype,
    }


def _signal_payload_from_bandit_insight(
    state: InterviewState,
    insight: dict[str, Any],
) -> dict[str, Any]:
    group_key = strategy_memory_key_for_insight(insight)
    session_id = str(state.get("session_id") or "unknown")
    ctx = str(insight.get("context_key") or "")
    parts = ctx.split(":", 1)
    job_level = parts[0] if parts else "mid"
    dimension = parts[1] if len(parts) > 1 else "general"
    action_id = str(insight.get("action_id") or "")
    return {
        "signal_key": f"{session_id}:{group_key}",
        "group_key": group_key,
        "session_id": session_id,
        "turn_idx": int(state.get("turn_idx", len(state.get("qa_history", [])))),
        "dimension": dimension,
        "job_level": job_level,
        "action_id": action_id,
        "plan_template": action_id or None,
        "probe_intent": None,
        "failure_categories": [],
        "score_before": None,
        "score_after": None,
        "score_delta": None,
        "immediate_reward": _optional_float(insight.get("mean_reward")),
        "verifier_overruled": False,
        "signal_type": str(insight.get("type") or "bandit_insight"),
    }


def _persist_strategy_signal(payload: dict[str, Any]) -> tuple[str, str]:
    signal_key = str(payload.get("signal_key") or "")
    if not signal_key:
        return "skipped_invalid", ""
    signal_id = _signal_id(signal_key)
    with get_session() as session:
        existing = session.get(StrategySignal, signal_id)
        if existing is not None:
            return "skipped_existing", signal_key
        session.add(
            StrategySignal(
                id=signal_id,
                signal_key=signal_key,
                group_key=str(payload.get("group_key") or ""),
                session_id=str(payload.get("session_id") or ""),
                turn_idx=int(payload.get("turn_idx") or 0),
                dimension=str(payload.get("dimension") or "unknown"),
                job_level=str(payload.get("job_level") or "mid"),
                action_id=str(payload.get("action_id") or "") or None,
                plan_template=str(payload.get("plan_template") or "") or None,
                probe_intent=str(payload.get("probe_intent") or "") or None,
                failure_categories=list(payload.get("failure_categories") or []),
                score_before=payload.get("score_before"),
                score_after=payload.get("score_after"),
                score_delta=payload.get("score_delta"),
                immediate_reward=payload.get("immediate_reward"),
                verifier_overruled=bool(payload.get("verifier_overruled")),
                signal_type=str(payload.get("signal_type") or "unknown"),
                status="observed",
            )
        )
    return "saved", signal_key


def _optional_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def experience_extractor_node(state: InterviewState) -> dict[str, Any]:
    """Extract and persist reusable strategy knowledge from the session.

    This is a fire-and-forget side-effect node: it reads the completed
    session state, optionally writes strategy files, and passes the
    state through unchanged (returns an empty update dict).
    """
    if state.get("status") == "cancelled":
        log.info("experience_extractor: skipped (session cancelled)")
        _trace_experience_extractor(state, saved=0, reason="cancelled")
        return {}

    qa_patterns = _extract_qa_patterns(state)
    bandit_insights = _extract_bandit_insights()
    candidates = len(qa_patterns) + len(bandit_insights)

    saved = 0
    skipped_existing = 0
    failed = 0
    saved_keys: list[str] = []
    skipped_keys: list[str] = []
    failed_keys: list[str] = []
    for pattern in qa_patterns:
        try:
            status, memory_key = _persist_strategy_signal(
                _signal_payload_from_qa_pattern(state, pattern)
            )
            if status == "saved":
                saved += 1
                saved_keys.append(memory_key)
                log.info(
                    "experience_extractor: saved QA signal %s key=%s",
                    pattern.get("type"),
                    memory_key,
                )
            elif status == "skipped_existing":
                skipped_existing += 1
                skipped_keys.append(memory_key)
                log.info(
                    "experience_extractor: skipped existing QA pattern key=%s",
                    memory_key,
                )
        except Exception as e:
            failed += 1
            memory_key = strategy_memory_key_for_pattern(pattern)
            failed_keys.append(memory_key)
            log.warning("experience_extractor: failed to save QA signal: %s", e)

    for insight in bandit_insights:
        try:
            status, memory_key = _persist_strategy_signal(
                _signal_payload_from_bandit_insight(state, insight)
            )
            if status == "saved":
                saved += 1
                saved_keys.append(memory_key)
                log.info(
                    "experience_extractor: saved bandit signal %s key=%s",
                    insight.get("type"),
                    memory_key,
                )
            elif status == "skipped_existing":
                skipped_existing += 1
                skipped_keys.append(memory_key)
                log.info(
                    "experience_extractor: skipped existing bandit insight key=%s",
                    memory_key,
                )
        except Exception as e:
            failed += 1
            memory_key = strategy_memory_key_for_insight(insight)
            failed_keys.append(memory_key)
            log.warning("experience_extractor: failed to save bandit insight: %s", e)

    if saved:
        log.info("experience_extractor: persisted %d new strategy entries", saved)
    else:
        log.debug("experience_extractor: no new strategies to persist")

    try:
        increment_session_count()
    except Exception as e:
        log.warning("experience_extractor: failed to increment dream session count: %s", e)

    _trace_experience_extractor(
        state,
        saved=saved,
        skipped_existing=skipped_existing,
        failed=failed,
        candidates=candidates,
        saved_keys=saved_keys[:5],
        skipped_keys=skipped_keys[:5],
        failed_keys=failed_keys[:5],
        reason="completed",
    )
    return {}


def _trace_experience_extractor(
    state: InterviewState,
    *,
    saved: int,
    skipped_existing: int = 0,
    failed: int = 0,
    candidates: int = 0,
    saved_keys: list[str] | None = None,
    skipped_keys: list[str] | None = None,
    failed_keys: list[str] | None = None,
    reason: str,
) -> None:
    try:
        get_tracer().trace_node_event(
            dict(state),
            node="experience_extractor",
            payload={
                "reason": reason,
                "saved": saved,
                "skipped_existing": skipped_existing,
                "failed": failed,
                "candidates": candidates,
                "saved_keys": saved_keys or [],
                "skipped_keys": skipped_keys or [],
                "failed_keys": failed_keys or [],
            },
        )
    except Exception as e:  # pragma: no cover - side channel
        log.warning("experience_extractor tracer side-channel failed: %s", e)
