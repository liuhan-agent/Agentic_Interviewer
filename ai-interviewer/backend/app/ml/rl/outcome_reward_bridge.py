"""Delayed reward back-filling from OutcomeRecord -> ThompsonBandit.

Flow::

    OutcomeRecord (hired / performance_score)
      -> compute delayed reward per session
      -> JOIN GenerationTrace rows that have not been applied yet
      -> for each trace, bandit.update(context_key, action_id, reward)
      -> mark trace.applied_to_bandit = True  (idempotent)

The "applied_to_bandit" flag is the idempotency guard flagged in the
ACO notes as "critical but easy to get wrong": without it, running
the bridge twice would double-count rewards.
"""
from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import select

from app.core.logging import get_logger
from app.core.settings import get_settings
from app.ml.rl.action_space import ALIAS_MAP
from app.ml.rl.thompson import get_bandit
from app.models import GenerationTrace, OutcomeRecord, get_session

log = get_logger(__name__)


# Fallback weights used when ``settings.outcome_weights`` is empty.
# Real overrides live in :mod:`app.core.settings` and can be tuned
# via the ``OUTCOME_WEIGHTS`` env var (JSON string).
OUTCOME_WEIGHTS: dict[str, float] = {
    "hired": 1.0,
    "rejected": 0.0,
    "withdrew": 0.3,
    "ghosted": 0.2,
}


def _delayed_reward(outcome: OutcomeRecord) -> float:
    """Translate a categorical outcome + optional scores into [0,1].

    Two blending channels exist, selected by ``outcome.source``:

    - ``ats_sync`` (B-end default): uses ``performance_score`` in [0,1]
      blended with the category weight via ``outcome_perf_blend``.
    - ``user_feedback`` (C-end): uses ``helpful_score`` (already
      normalised to [0,1] by the API layer) blended the same way.
      Falls through to the ``performance_score`` channel if
      ``helpful_score`` is absent, so legacy rows stay compatible.

    Unknown categories fall back to 0.3 so we never hand the bandit a
    garbage-in-garbage-out update.
    """
    s = get_settings()
    weights = s.outcome_weights or OUTCOME_WEIGHTS
    base = weights.get(outcome.outcome, 0.3)

    source = getattr(outcome, "source", "ats_sync") or "ats_sync"
    subjective: float | None = None
    if source == "user_feedback":
        raw = getattr(outcome, "helpful_score", None)
        if raw is not None:
            subjective = max(0.0, min(1.0, float(raw)))
    if subjective is None and outcome.performance_score is not None:
        subjective = max(0.0, min(1.0, float(outcome.performance_score)))
    if subjective is None:
        return base

    blend = s.outcome_perf_blend
    return (1.0 - blend) * base + blend * subjective


def _pending_traces(sess, session_ids: Iterable[str]) -> list[GenerationTrace]:
    stmt = (
        select(GenerationTrace)
        .where(GenerationTrace.session_id.in_(list(session_ids)))
        .where(GenerationTrace.applied_to_bandit.is_(False))
        .order_by(GenerationTrace.session_id, GenerationTrace.turn_idx)
    )
    return list(sess.scalars(stmt))


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


def backfill_once() -> dict[str, int]:
    """Apply any outcomes not yet propagated to the bandit.

    Two-phase execution to keep DB and in-memory bandit state
    consistent across partial failures:

    1. **DB phase** – collect pending traces, compute rewards, stamp
       ``delayed_reward`` + ``applied_to_bandit=True`` and commit.
       If this phase raises or the commit fails, nothing changes on
       disk and we exit cleanly; the next invocation will see the
       same pending set.
    2. **Bandit phase** – only after the DB commit succeeds we drive
       the in-memory posteriors.  If *this* phase crashes or the
       process dies, the DB is still the source of truth and the
       next ``rehydrate_from_db`` call (run on startup when
       ``settings.rehydrate_bandit_on_start`` is True) will replay
       the exact same updates, so the bandit ends up consistent.

    The ``ALIAS_MAP`` mirror-write to the canonical template arm is
    preserved so ``policy_mode=template`` keeps learning from traces
    that still log legacy arm ids.
    """
    counters = {"sessions": 0, "traces": 0}
    applied: list[tuple[list[str], str, float]] = []

    with get_session() as sess:
        outcomes = list(sess.scalars(select(OutcomeRecord)))
        if not outcomes:
            return counters
        ids = [o.session_id for o in outcomes]
        traces = _pending_traces(sess, ids)
        outcome_by_sid = {o.session_id: o for o in outcomes}
        for t in traces:
            outcome = outcome_by_sid.get(t.session_id)
            if outcome is None:
                continue
            keys = _policy_keys(t)
            if not (keys and t.action_id):
                continue
            reward = _delayed_reward(outcome)
            t.delayed_reward = reward
            t.applied_to_bandit = True
            applied.append((keys, t.action_id, reward))
            counters["traces"] += 1
        counters["sessions"] = len({t.session_id for t in traces})
        # session __exit__ commits here; raising above means no writes.

    bandit = get_bandit()
    for keys, action_id, reward in applied:
        for ctx_key in keys:
            bandit.update(ctx_key, action_id, reward)
        alias = ALIAS_MAP.get(action_id)
        if alias and alias != action_id:
            for ctx_key in keys:
                bandit.update(ctx_key, alias, reward)

    log.info(
        "delayed-reward backfill: committed %d traces across %d sessions "
        "(bandit updates=%d including aliases)",
        counters["traces"],
        counters["sessions"],
        sum(
            2 if (ALIAS_MAP.get(aid) and ALIAS_MAP[aid] != aid) else 1
            for keys, aid, _ in applied
            for _key in keys
        ),
    )
    return counters
