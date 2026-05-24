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

from sqlalchemy import select

from app.core.logging import get_logger
from app.core.settings import get_settings
from app.core.tracer import get_tracer
from app.engine.workflow.policy_context import parse_policy_context_key
from app.engine.workflow.state import FailureCategory, InterviewState
from app.ml.rl.action_space import ACTIONS_BY_ID, canonical_action_id
from app.ml.rl.thompson import get_bandit
from app.models import get_session
from app.models.strategy_learning import BanditPosterior, InterviewTurn
from app.models.strategy_memory import StrategySignal
from app.tasks.dream_tasks import increment_session_count

log = get_logger(__name__)

_VALID_FAILURE_CATEGORIES: set[str] = set(FailureCategory.__args__)  # type: ignore[attr-defined]


def _last_turn_failure_categories(
    qa_history: list[dict[str, Any]],
    dimension: str,
) -> list[str]:
    """Return the most recent same-dimension turn's failure_categories.

    Walks ``qa_history`` from the tail so the signal reflects the
    latest evaluator verdict on the dimension — which is the verdict
    that actually justified persisting the signal in the first place.
    Returns ``[]`` when no matching turn carries any legal enum value,
    so callers can blindly forward the list into ``StrategySignal``.
    """
    for turn in reversed(qa_history or []):
        if turn.get("dimension") != dimension:
            continue
        evaluation = turn.get("evaluation") or {}
        raw = evaluation.get("failure_categories")
        if not isinstance(raw, list):
            return []
        cleaned: list[str] = []
        seen: set[str] = set()
        for item in raw:
            value = str(item or "").strip()
            if not value or value not in _VALID_FAILURE_CATEGORIES or value in seen:
                continue
            cleaned.append(value)
            seen.add(value)
        return cleaned
    return []


def _load_qa_history_for_extraction(
    state: InterviewState,
) -> tuple[list[dict[str, Any]], str]:
    session_id = str(state.get("session_id") or "").strip()
    if session_id:
        try:
            with get_session() as session:
                rows = list(
                    session.scalars(
                        select(InterviewTurn)
                        .where(InterviewTurn.session_id == session_id)
                        .order_by(InterviewTurn.turn_idx.asc())
                    )
                )
            if rows:
                return [_turn_row_to_qa(row) for row in rows], "db"
        except Exception as e:  # pragma: no cover - extraction is best-effort
            log.warning("experience_extractor: interview_turns DB read failed: %s", e)

    return list(state.get("qa_history") or []), "state"


def _turn_row_to_qa(row: InterviewTurn) -> dict[str, Any]:
    evaluation = dict(row.evaluation or {})
    if row.score is not None and "score" not in evaluation:
        evaluation["score"] = row.score
    if row.passed is not None and "passed" not in evaluation:
        evaluation["passed"] = row.passed
    if row.failure_categories and "failure_categories" not in evaluation:
        evaluation["failure_categories"] = list(row.failure_categories)
    qa = {
        "turn_idx": row.turn_idx,
        "dimension": row.dimension,
        "question": row.question,
        "answer": row.answer,
        "selected_action": row.selected_action or "",
        "evaluation": evaluation,
        "selection_artifacts": dict(row.selection_artifacts or {}),
    }
    resume_anchor = _turn_row_resume_anchor(row)
    if resume_anchor:
        qa["resume_anchor"] = resume_anchor
    return qa


def _turn_row_resume_anchor(row: InterviewTurn) -> dict[str, Any]:
    anchor: dict[str, Any] = {}
    if row.resume_anchor_key:
        anchor["anchor_key"] = row.resume_anchor_key
    if row.resume_anchor_label:
        anchor["label"] = row.resume_anchor_label
    if row.resume_project_id:
        anchor["project_id"] = row.resume_project_id
    return anchor


def _safe_key_part(value: Any) -> str:
    return str(value or "unknown").strip().replace(" ", "_") or "unknown"


def _extract_qa_patterns(
    state: InterviewState,
    *,
    qa_history: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Identify notable patterns from this session's QA history."""
    qa_history = qa_history if qa_history is not None else state.get("qa_history", [])
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


def _extract_bandit_insights() -> tuple[list[dict[str, Any]], str]:
    """Query persisted posteriors first, with memory fallback for legacy tests."""
    s = get_settings()
    min_obs = float(s.experience_min_observations)
    high_mean = float(s.experience_high_reward_mean)
    low_mean = float(s.experience_low_reward_mean)

    db_insights, had_db_rows = _extract_bandit_insights_from_db(
        min_obs=min_obs,
        high_mean=high_mean,
        low_mean=low_mean,
    )
    if had_db_rows:
        return db_insights, "db"

    return (
        _extract_bandit_insights_from_memory(
            min_obs=min_obs,
            high_mean=high_mean,
            low_mean=low_mean,
        ),
        "memory",
    )


def _extract_bandit_insights_from_memory(
    *,
    min_obs: float,
    high_mean: float,
    low_mean: float,
) -> list[dict[str, Any]]:
    """Query in-memory bandit posteriors for legacy fallback coverage."""
    bandit = get_bandit()
    insights: list[dict[str, Any]] = []

    for (ctx_key, action_id), params in bandit.priors.items():
        total = params.alpha + params.beta - 2.0
        if total < min_obs:
            continue

        mean = params.mean()
        if mean >= high_mean:
            action = ACTIONS_BY_ID.get(canonical_action_id(action_id) or action_id)
            action_label = action.label if action else action_id
            insights.append({
                "type": "high_reward_arm",
                "context_key": ctx_key,
                "action_id": canonical_action_id(action_id) or action_id,
                "original_action_id": action_id,
                "action_label": action_label,
                "mean_reward": round(mean, 3),
                "observations": int(total),
                "detail": (
                    f"Action '{action_label}' in context '{ctx_key}' has "
                    f"mean reward {mean:.3f} over {int(total)} observations."
                ),
            })

        if mean <= low_mean and total >= min_obs:
            action = ACTIONS_BY_ID.get(canonical_action_id(action_id) or action_id)
            action_label = action.label if action else action_id
            insights.append({
                "type": "low_reward_arm",
                "context_key": ctx_key,
                "action_id": canonical_action_id(action_id) or action_id,
                "original_action_id": action_id,
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


def _extract_bandit_insights_from_db(
    *,
    min_obs: float,
    high_mean: float,
    low_mean: float,
) -> tuple[list[dict[str, Any]], bool]:
    insights: list[dict[str, Any]] = []
    try:
        with get_session() as session:
            rows = list(
                session.scalars(
                    select(BanditPosterior)
                    .order_by(BanditPosterior.observation_count.desc())
                )
            )
    except Exception as e:  # pragma: no cover - extraction is best-effort
        log.warning("experience_extractor: posterior DB read failed: %s", e)
        return [], False

    for row in rows:
        total = int(row.observation_count or 0)
        if total < min_obs:
            continue
        mean = _posterior_mean(row.alpha, row.beta)
        if mean is None:
            continue
        if mean >= high_mean:
            insights.append(
                _posterior_insight(
                    row,
                    signal_type="high_reward_arm",
                    mean=mean,
                    observations=total,
                    low_reward=False,
                )
            )
        if mean <= low_mean:
            insights.append(
                _posterior_insight(
                    row,
                    signal_type="low_reward_arm",
                    mean=mean,
                    observations=total,
                    low_reward=True,
                )
            )
    return insights, bool(rows)


def _posterior_mean(alpha: float | None, beta: float | None) -> float | None:
    a = float(alpha or 0.0)
    b = float(beta or 0.0)
    total = a + b
    if total <= 0:
        return None
    return a / total


def _posterior_insight(
    row: BanditPosterior,
    *,
    signal_type: str,
    mean: float,
    observations: int,
    low_reward: bool,
) -> dict[str, Any]:
    canonical_action = canonical_action_id(row.action_id) or row.action_id
    action = ACTIONS_BY_ID.get(canonical_action)
    action_label = action.label if action else canonical_action
    if low_reward:
        detail = (
            f"Action '{action_label}' in context '{row.context_key}' has "
            f"low mean reward {mean:.3f} over {observations} observations. "
            f"Consider avoiding this action in similar contexts."
        )
    else:
        detail = (
            f"Action '{action_label}' in context '{row.context_key}' has "
            f"mean reward {mean:.3f} over {observations} observations."
        )
    return {
        "type": signal_type,
        "context_key": row.context_key,
        "action_id": canonical_action,
        "original_action_id": row.action_id,
        "action_label": action_label,
        "mean_reward": round(mean, 3),
        "observations": observations,
        "detail": detail,
    }


def strategy_memory_key_for_pattern(pattern: dict[str, Any]) -> str:
    ptype = _safe_key_part(pattern.get("type"))
    dim = _safe_key_part(pattern.get("dimension"))
    job_level = _safe_key_part(pattern.get("job_level", "mid"))
    if ptype == "score_recovery":
        action = _safe_key_part(canonical_action_id(pattern.get("recovery_action")))
        return f"qa:{ptype}:{job_level}:{dim}:{action}"
    if ptype == "score_decline":
        action = _safe_key_part(canonical_action_id(pattern.get("failing_action")))
        return f"qa:{ptype}:{job_level}:{dim}:{action}"
    if ptype == "hint_effective":
        return f"qa:{ptype}:{job_level}:{dim}"
    return f"qa:{ptype}:{job_level}:{dim}"


def strategy_memory_key_for_insight(insight: dict[str, Any]) -> str:
    itype = _safe_key_part(insight.get("type"))
    ctx = _safe_key_part(insight.get("context_key"))
    action_id = _safe_key_part(canonical_action_id(insight.get("action_id")))
    return f"bandit:{itype}:{ctx}:{action_id}"


def _signal_id(signal_key: str) -> str:
    digest = hashlib.sha1(signal_key.encode("utf-8"), usedforsecurity=False).hexdigest()
    return f"signal:{digest[:24]}"


def _signal_payload_from_qa_pattern(
    state: InterviewState,
    pattern: dict[str, Any],
    *,
    qa_history: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    ptype = str(pattern.get("type") or "unknown")
    original_action_id = (
        pattern.get("recovery_action")
        or pattern.get("failing_action")
        or ("give_hint" if ptype == "hint_effective" else None)
    )
    action_id = canonical_action_id(original_action_id)
    group_key = strategy_memory_key_for_pattern(pattern)
    session_id = str(state.get("session_id") or "unknown")
    dimension = str(pattern.get("dimension") or "unknown")
    qa_history = qa_history if qa_history is not None else state.get("qa_history", [])
    return {
        "signal_key": f"{session_id}:{group_key}",
        "group_key": group_key,
        "session_id": session_id,
        "turn_idx": int(state.get("turn_idx", len(qa_history))),
        "dimension": dimension,
        "job_level": str(pattern.get("job_level") or "mid"),
        "action_id": str(action_id or ""),
        "plan_template": str(action_id or "") or None,
        "original_action_id": str(original_action_id or "") or None,
        "probe_intent": None,
        "failure_categories": _last_turn_failure_categories(
            qa_history,
            dimension,
        ),
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
    *,
    qa_history: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    group_key = strategy_memory_key_for_insight(insight)
    session_id = str(state.get("session_id") or "unknown")
    ctx = str(insight.get("context_key") or "")
    parsed_context = parse_policy_context_key(ctx)
    original_action_id = str(
        insight.get("original_action_id") or insight.get("action_id") or ""
    )
    action_id = canonical_action_id(insight.get("action_id")) or ""
    qa_history = qa_history if qa_history is not None else state.get("qa_history", [])
    return {
        "signal_key": f"{session_id}:{group_key}",
        "group_key": group_key,
        "session_id": session_id,
        "turn_idx": int(state.get("turn_idx", len(qa_history))),
        "dimension": parsed_context.dimension,
        "job_level": parsed_context.job_level,
        "action_id": action_id,
        "plan_template": action_id or None,
        "original_action_id": original_action_id or None,
        "probe_intent": None,
        # Bandit context can cross sessions; the categories come from
        # the current session's last matching dimension turn when we
        # happen to have one, else stay empty rather than fabricate.
        "failure_categories": _last_turn_failure_categories(
            qa_history,
            parsed_context.dimension,
        ),
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
        _trace_experience_extractor(
            state,
            saved=0,
            reason="cancelled",
            qa_source="skipped",
            bandit_source="skipped",
        )
        return {}

    qa_history, qa_source = _load_qa_history_for_extraction(state)
    qa_patterns = _call_extract_qa_patterns(state, qa_history)
    bandit_insights, bandit_source = _call_extract_bandit_insights()
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
                _signal_payload_from_qa_pattern(
                    state,
                    pattern,
                    qa_history=qa_history,
                )
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
                _signal_payload_from_bandit_insight(
                    state,
                    insight,
                    qa_history=qa_history,
                )
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
        qa_source=qa_source,
        bandit_source=bandit_source,
    )
    return {}


def _call_extract_qa_patterns(
    state: InterviewState,
    qa_history: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    try:
        return _extract_qa_patterns(state, qa_history=qa_history)
    except TypeError:
        # Some tests and local extensions monkeypatch this internal hook
        # with the legacy one-argument signature.
        return _extract_qa_patterns(state)


def _call_extract_bandit_insights() -> tuple[list[dict[str, Any]], str]:
    raw = _extract_bandit_insights()
    if isinstance(raw, tuple):
        return raw
    return list(raw or []), "memory"


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
    qa_source: str = "state",
    bandit_source: str = "memory",
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
                "qa_source": qa_source,
                "bandit_source": bandit_source,
            },
        )
    except Exception as e:  # pragma: no cover - side channel
        log.warning("experience_extractor tracer side-channel failed: %s", e)
