"""Helpers for durable strategy-learning facts and posterior aggregates."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import get_session
from app.models.strategy_learning import BanditPosterior, InterviewTurn


def upsert_interview_turn(
    sess: Session,
    *,
    session_id: str,
    turn_idx: int,
    **values: Any,
) -> InterviewTurn:
    """Create or update the durable fact row for a completed interview turn."""
    sid = str(session_id)
    idx = int(turn_idx)
    row = _pending_interview_turn(sess, sid, idx)
    if row is None:
        row = sess.scalar(
            select(InterviewTurn)
            .where(InterviewTurn.session_id == sid)
            .where(InterviewTurn.turn_idx == idx)
        )
    if row is None:
        row = InterviewTurn(session_id=sid, turn_idx=idx)
        sess.add(row)

    for key, value in values.items():
        if not hasattr(row, key):
            continue
        setattr(row, key, _normalise_json_value(value))
    row.updated_at = datetime.now(UTC)
    return row


def apply_bandit_posterior_update(
    sess: Session,
    *,
    context_key: str,
    action_id: str,
    reward: float,
    reward_kind: str,
    session_id: str | None = None,
    turn_idx: int | None = None,
    default_alpha: float = 1.0,
    default_beta: float = 1.0,
) -> BanditPosterior:
    """Apply one Thompson-style fractional reward update to the aggregate row."""
    ctx = str(context_key or "").strip()
    action = str(action_id or "").strip()
    if not ctx or not action:
        raise ValueError("context_key and action_id are required")

    row = _pending_bandit_posterior(sess, ctx, action)
    if row is None:
        row = sess.scalar(
            select(BanditPosterior)
            .where(BanditPosterior.context_key == ctx)
            .where(BanditPosterior.action_id == action)
        )
    if row is None:
        row = BanditPosterior(
            context_key=ctx,
            action_id=action,
            alpha=float(default_alpha),
            beta=float(default_beta),
            observation_count=0,
            immediate_update_count=0,
            delayed_update_count=0,
        )
        sess.add(row)

    clipped = max(0.0, min(1.0, float(reward)))
    row.alpha = float(row.alpha or default_alpha) + clipped
    row.beta = float(row.beta or default_beta) + (1.0 - clipped)
    row.observation_count = int(row.observation_count or 0) + 1
    if reward_kind == "delayed":
        row.delayed_update_count = int(row.delayed_update_count or 0) + 1
    else:
        reward_kind = "immediate"
        row.immediate_update_count = int(row.immediate_update_count or 0) + 1
    row.last_reward = clipped
    row.last_reward_kind = reward_kind
    row.last_session_id = str(session_id) if session_id else None
    row.last_turn_idx = int(turn_idx) if turn_idx is not None else None
    row.updated_at = datetime.now(UTC)
    return row


def load_session_turns(session_id: str) -> list[InterviewTurn]:
    """Return durable turns for a session, ordered by interview turn."""
    with get_session() as sess:
        return list(
            sess.scalars(
                select(InterviewTurn)
                .where(InterviewTurn.session_id == str(session_id))
                .order_by(InterviewTurn.turn_idx.asc())
            )
        )


def load_bandit_posteriors(*, min_observations: float = 0.0) -> list[BanditPosterior]:
    """Return persisted posterior rows that have enough observations."""
    with get_session() as sess:
        return list(
            sess.scalars(
                select(BanditPosterior)
                .where(BanditPosterior.observation_count >= int(min_observations))
                .order_by(BanditPosterior.observation_count.desc())
            )
        )


def bandit_posterior_snapshot(*, limit: int = 10) -> dict[str, Any]:
    """Small admin-friendly summary of persisted posterior state."""
    with get_session() as sess:
        rows = list(
            sess.scalars(
                select(BanditPosterior)
                .order_by(BanditPosterior.observation_count.desc())
                .limit(limit)
            )
        )
        count = sess.query(BanditPosterior).count()

    return {
        "persisted_prior_count": count,
        "top_posteriors": [
            {
                "context_key": row.context_key,
                "action_id": row.action_id,
                "alpha": row.alpha,
                "beta": row.beta,
                "mean_reward": _mean(row.alpha, row.beta),
                "observation_count": row.observation_count,
                "last_reward": row.last_reward,
                "last_reward_kind": row.last_reward_kind,
                "last_session_id": row.last_session_id,
                "last_turn_idx": row.last_turn_idx,
                "updated_at": row.updated_at.isoformat() if row.updated_at else None,
            }
            for row in rows
        ],
    }


def _mean(alpha: float | None, beta: float | None) -> float | None:
    a = float(alpha or 0.0)
    b = float(beta or 0.0)
    total = a + b
    if total <= 0:
        return None
    return a / total


def _normalise_json_value(value: Any) -> Any:
    if isinstance(value, tuple):
        return list(value)
    return value


def _pending_interview_turn(
    sess: Session,
    session_id: str,
    turn_idx: int,
) -> InterviewTurn | None:
    for obj in list(sess.new) + list(sess.identity_map.values()):
        if (
            isinstance(obj, InterviewTurn)
            and obj.session_id == session_id
            and int(obj.turn_idx) == turn_idx
        ):
            return obj
    return None


def _pending_bandit_posterior(
    sess: Session,
    context_key: str,
    action_id: str,
) -> BanditPosterior | None:
    for obj in list(sess.new) + list(sess.identity_map.values()):
        if (
            isinstance(obj, BanditPosterior)
            and obj.context_key == context_key
            and obj.action_id == action_id
        ):
            return obj
    return None
