"""Backfill durable strategy-learning facts from generation traces.

Usage:

    python -m app.scripts.backfill_strategy_facts
    python -m app.scripts.backfill_strategy_facts --apply

The default mode is a dry run. ``--apply`` upserts ``interview_turns`` and
rebuilds ``bandit_posteriors`` from already-applied trace rewards.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from typing import Any

from sqlalchemy import delete, or_, select

from app.core.settings import get_settings
from app.ml.rl.action_space import ALIAS_MAP
from app.models import BanditPosterior, GenerationTrace, get_session, init_db
from app.services.strategy_learning_facts import upsert_interview_turn


@dataclass
class PosteriorAccumulator:
    alpha: float
    beta: float
    observation_count: int = 0
    immediate_update_count: int = 0
    delayed_update_count: int = 0
    last_reward: float | None = None
    last_reward_kind: str | None = None
    last_session_id: str | None = None
    last_turn_idx: int | None = None

    def apply(
        self,
        *,
        reward: float,
        reward_kind: str,
        session_id: str,
        turn_idx: int,
    ) -> None:
        clipped = max(0.0, min(1.0, float(reward)))
        self.alpha += clipped
        self.beta += 1.0 - clipped
        self.observation_count += 1
        if reward_kind == "delayed":
            self.delayed_update_count += 1
        else:
            self.immediate_update_count += 1
        self.last_reward = clipped
        self.last_reward_kind = reward_kind
        self.last_session_id = session_id
        self.last_turn_idx = turn_idx


def run(*, apply: bool) -> dict[str, int]:
    init_db()
    settings = get_settings()
    default_alpha = float(settings.bandit_default_alpha)
    default_beta = float(settings.bandit_default_beta)
    counters = {
        "turn_candidates": 0,
        "turns_upserted": 0,
        "posterior_updates": 0,
        "posteriors_rebuilt": 0,
    }
    posterior_map: dict[tuple[str, str], PosteriorAccumulator] = {}

    with get_session() as session:
        turn_rows = list(
            session.scalars(
                select(GenerationTrace)
                .where(GenerationTrace.session_id.is_not(None))
                .where(GenerationTrace.turn_idx.is_not(None))
                .where(GenerationTrace.node == "evaluator")
                .order_by(GenerationTrace.session_id, GenerationTrace.turn_idx)
            )
        )
        counters["turn_candidates"] = len(turn_rows)
        for trace in turn_rows:
            if apply:
                evaluation = dict(trace.evaluation or {})
                failure_categories = _failure_categories(evaluation)
                snapshot = trace.state_snapshot or {}
                job_spec = snapshot.get("job_spec") if isinstance(snapshot, dict) else {}
                upsert_interview_turn(
                    session,
                    session_id=trace.session_id,
                    turn_idx=trace.turn_idx,
                    trace_id=trace.trace_id,
                    dimension=trace.dimension or "unknown",
                    job_level=_optional_str((job_spec or {}).get("level")),
                    question=trace.question or "",
                    answer=trace.answer or "",
                    selected_action=trace.action_id,
                    policy_context_keys=_policy_keys(trace),
                    evaluation=evaluation,
                    failure_categories=failure_categories,
                    score=trace.score,
                    passed=trace.passed,
                )
                counters["turns_upserted"] += 1

        reward_rows = list(
            session.scalars(
                select(GenerationTrace)
                .where(
                    or_(
                        GenerationTrace.immediate_reward_applied.is_(True),
                        GenerationTrace.applied_to_bandit.is_(True),
                    )
                )
                .where(GenerationTrace.context_key.is_not(None))
                .where(GenerationTrace.action_id.is_not(None))
                .order_by(GenerationTrace.id.asc())
            )
        )
        for trace in reward_rows:
            for reward_kind, reward in _trace_rewards(trace):
                for context_key in _policy_keys(trace):
                    for action_id in _action_ids(str(trace.action_id)):
                        acc = posterior_map.setdefault(
                            (context_key, action_id),
                            PosteriorAccumulator(default_alpha, default_beta),
                        )
                        acc.apply(
                            reward=reward,
                            reward_kind=reward_kind,
                            session_id=trace.session_id,
                            turn_idx=trace.turn_idx,
                        )
                        counters["posterior_updates"] += 1

        if apply:
            session.execute(delete(BanditPosterior))
            for (context_key, action_id), acc in posterior_map.items():
                session.add(
                    BanditPosterior(
                        context_key=context_key,
                        action_id=action_id,
                        alpha=acc.alpha,
                        beta=acc.beta,
                        observation_count=acc.observation_count,
                        immediate_update_count=acc.immediate_update_count,
                        delayed_update_count=acc.delayed_update_count,
                        last_reward=acc.last_reward,
                        last_reward_kind=acc.last_reward_kind,
                        last_session_id=acc.last_session_id,
                        last_turn_idx=acc.last_turn_idx,
                    )
                )
            counters["posteriors_rebuilt"] = len(posterior_map)

    return counters


def _trace_rewards(trace: GenerationTrace) -> list[tuple[str, float]]:
    rewards: list[tuple[str, float]] = []
    if trace.immediate_reward_applied and trace.immediate_reward is not None:
        rewards.append(("immediate", float(trace.immediate_reward)))
    if trace.applied_to_bandit and trace.delayed_reward is not None:
        rewards.append(("delayed", float(trace.delayed_reward)))
    return rewards


def _policy_keys(trace: GenerationTrace) -> list[str]:
    keys = trace.policy_context_keys if isinstance(trace.policy_context_keys, list) else []
    if not keys and trace.context_key:
        keys = [trace.context_key]
    out: list[str] = []
    seen: set[str] = set()
    for key in keys:
        item = str(key or "").strip()
        if item and item not in seen:
            out.append(item)
            seen.add(item)
    return out


def _action_ids(action_id: str) -> list[str]:
    ids = [action_id]
    alias = ALIAS_MAP.get(action_id)
    if alias and alias != action_id:
        ids.append(alias)
    return ids


def _failure_categories(evaluation: dict[str, Any]) -> list[str]:
    raw = evaluation.get("failure_categories")
    if not isinstance(raw, list):
        return []
    return [str(value) for value in raw if isinstance(value, str) and value.strip()]


def _optional_str(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write interview_turns and rebuild bandit_posteriors.",
    )
    args = parser.parse_args()
    counters = run(apply=bool(args.apply))
    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"{mode} strategy fact backfill: {counters}")


if __name__ == "__main__":
    main()
