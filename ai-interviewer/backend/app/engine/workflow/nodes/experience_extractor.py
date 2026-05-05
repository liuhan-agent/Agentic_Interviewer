"""Post-interview experience extraction node.

Runs after ``final_report_node`` to analyse the completed session and
decide whether any reusable strategy knowledge should be persisted to
the file-backed strategy memory layer.

Two extraction paths run in sequence:

1. **QA-pattern extraction** — scans ``qa_history`` for notable patterns
   (e.g. a dimension where ``give_hint`` rescued a failing candidate,
   or where ``deepen_technical`` consistently produced high scores).

2. **Bandit-posterior extraction** — reads the current Thompson Sampling
   posteriors and auto-generates strategy files for ``(context_key,
   action_id)`` arms whose mean reward has crossed a confidence
   threshold, bridging numerical RL signals with human-readable
   strategy knowledge.

Both paths write through ``strategy_store.save_strategy`` which keeps
``MEMORY.md`` in sync.
"""
from __future__ import annotations

from typing import Any

from app.core.logging import get_logger
from app.core.settings import get_settings
from app.core.tracer import get_tracer
from app.engine.workflow.state import InterviewState
from app.memory.strategy_store import list_strategies, save_strategy
from app.ml.rl.action_space import ACTIONS_BY_ID
from app.ml.rl.thompson import get_bandit
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


def _strategy_exists(name_slug_prefix: str) -> bool:
    """Check if a strategy with a similar name already exists."""
    for entry in list_strategies():
        if entry.path.stem.startswith(name_slug_prefix):
            return True
    return False


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


def strategy_exists_by_memory_key(memory_key: str) -> bool:
    needle = f"memory_key: {memory_key}"
    for entry in list_strategies():
        try:
            if needle in entry.path.read_text(encoding="utf-8"):
                return True
        except OSError:
            continue
    return False


def _persist_qa_pattern(pattern: dict[str, Any]) -> tuple[str, str]:
    dim = pattern.get("dimension", "unknown")
    job_level = pattern.get("job_level", "mid")
    ptype = pattern.get("type", "")
    slug_prefix = f"auto_{ptype}_{dim}"
    memory_key = strategy_memory_key_for_pattern(pattern)

    if strategy_exists_by_memory_key(memory_key) or _strategy_exists(slug_prefix):
        return "skipped_existing", memory_key

    if ptype == "score_recovery":
        action = pattern.get("recovery_action", "unknown")
        save_strategy(
            name=f"Auto: {dim} recovery via {action}",
            description=pattern.get("detail", ""),
            dimensions=[dim],
            job_levels=[job_level],
            memory_key=memory_key,
            body=(
                f"{pattern.get('detail', '')}\n\n"
                f"How to apply:\n"
                f"- When a candidate scores low in {dim}, try '{action}' "
                f"before switching dimensions.\n"
                f"- This pattern was observed with a score delta of "
                f"{pattern.get('score_delta', 0):.1f} points.\n"
            ),
        )
        return "saved", memory_key

    if ptype == "hint_effective":
        save_strategy(
            name=f"Auto: hints effective in {dim}",
            description=pattern.get("detail", ""),
            dimensions=[dim],
            job_levels=[job_level],
            memory_key=memory_key,
            body=(
                f"{pattern.get('detail', '')}\n\n"
                f"How to apply:\n"
                f"- In {dim}, prefer 'give_hint' when candidates give "
                f"incomplete initial answers.\n"
                f"- Average hint-assisted score: {pattern.get('avg_hint_score', 0):.1f}\n"
            ),
        )
        return "saved", memory_key

    return "skipped_unsupported", memory_key


def _persist_bandit_insight(insight: dict[str, Any]) -> tuple[str, str]:
    ctx = insight.get("context_key", "unknown")
    action_id = insight.get("action_id", "unknown")
    slug_prefix = f"auto_bandit_{ctx}_{action_id}".replace(":", "_")
    memory_key = strategy_memory_key_for_insight(insight)

    if strategy_exists_by_memory_key(memory_key) or _strategy_exists(slug_prefix):
        return "skipped_existing", memory_key

    parts = ctx.split(":", 1)
    job_level = parts[0] if parts else "mid"
    dim = parts[1] if len(parts) > 1 else "general"

    itype = insight.get("type", "")
    action_label = insight.get("action_label", action_id)
    mean = insight.get("mean_reward", 0)
    obs = insight.get("observations", 0)

    if itype == "high_reward_arm":
        save_strategy(
            name=f"Auto: {action_label} excels in {dim} ({job_level})",
            description=f"Bandit evidence: {action_label} has {mean:.0%} mean reward in {ctx}",
            dimensions=[dim],
            job_levels=[job_level],
            memory_key=memory_key,
            body=(
                f"Thompson Sampling evidence ({obs} observations):\n"
                f"Action '{action_label}' consistently produces high rewards "
                f"(mean {mean:.3f}) for {job_level}-level candidates in {dim}.\n\n"
                f"How to apply:\n"
                f"- When interviewing {job_level} candidates on {dim}, "
                f"'{action_label}' is the statistically preferred action.\n"
                f"- The bandit has accumulated {obs} observations supporting this.\n\n"
                f"Pitfalls:\n"
                f"- Statistical preference does not mean always correct; "
                f"context matters.\n"
                f"- Exploration rate ensures alternatives are still tried.\n"
            ),
        )
        return "saved", memory_key

    if itype == "low_reward_arm":
        save_strategy(
            name=f"Auto: avoid {action_label} in {dim} ({job_level})",
            description=f"Bandit evidence: {action_label} underperforms in {ctx}",
            dimensions=[dim],
            job_levels=[job_level],
            memory_key=memory_key,
            body=(
                f"Thompson Sampling evidence ({obs} observations):\n"
                f"Action '{action_label}' consistently produces low rewards "
                f"(mean {mean:.3f}) for {job_level}-level candidates in {dim}.\n\n"
                f"How to apply:\n"
                f"- Avoid defaulting to '{action_label}' for {job_level} "
                f"candidates in {dim} unless other actions are masked.\n"
                f"- Consider 'deepen_technical' or 'give_hint' instead.\n"
            ),
        )
        return "saved", memory_key

    return "skipped_unsupported", memory_key


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
            status, memory_key = _persist_qa_pattern(pattern)
            if status == "saved":
                saved += 1
                saved_keys.append(memory_key)
                log.info(
                    "experience_extractor: saved QA pattern %s key=%s",
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
            log.warning("experience_extractor: failed to save QA pattern: %s", e)

    for insight in bandit_insights:
        try:
            status, memory_key = _persist_bandit_insight(insight)
            if status == "saved":
                saved += 1
                saved_keys.append(memory_key)
                log.info(
                    "experience_extractor: saved bandit insight %s key=%s",
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
