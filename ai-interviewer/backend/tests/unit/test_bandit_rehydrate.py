"""Unit tests for ``ThompsonBandit.rehydrate_from_db``.

The outcome bridge writes ``delayed_reward`` and flips
``applied_to_bandit=True`` on every trace row once it has been
folded into the bandit. Rehydration replays those rows into a fresh
in-memory bandit so a process restart does not wipe the learning
signal. We exercise the path via the real ORM + the sqlite fallback
that ``app.models.base`` already uses when Postgres is unavailable,
which keeps the test hermetic.
"""
from __future__ import annotations

import random

import pytest
from sqlalchemy import delete

from app.ml.rl.action_space import DEEPEN_TECHNICAL, SWITCH_DIMENSION
from app.ml.rl.thompson import ThompsonBandit
from app.models import GenerationTrace, get_session, init_db


@pytest.fixture(autouse=True)
def _ensure_schema():
    init_db()
    with get_session() as sess:
        sess.execute(delete(GenerationTrace))
    yield
    with get_session() as sess:
        sess.execute(delete(GenerationTrace))


def _insert_applied_trace(
    session_id: str,
    turn_idx: int,
    context_key: str,
    action_id: str,
    reward: float,
    policy_context_keys: list[str] | None = None,
) -> None:
    with get_session() as sess:
        sess.add(
            GenerationTrace(
                trace_id=f"trace-{session_id}",
                session_id=session_id,
                turn_idx=turn_idx,
                node="evaluator",
                dimension="technical_depth",
                action_id=action_id,
                policy_id="thompson_v1::senior:technical_depth",
                context_key=context_key,
                policy_context_keys=policy_context_keys,
                score=8.0,
                passed=True,
                immediate_reward=0.9,
                delayed_reward=reward,
                applied_to_bandit=True,
            )
        )


def _insert_pending_trace(session_id: str) -> None:
    with get_session() as sess:
        sess.add(
            GenerationTrace(
                trace_id=f"trace-{session_id}",
                session_id=session_id,
                turn_idx=0,
                node="evaluator",
                dimension="technical_depth",
                action_id=DEEPEN_TECHNICAL.id,
                policy_id="thompson_v1::senior:technical_depth",
                context_key="senior:technical_depth",
                score=8.0,
                passed=True,
                immediate_reward=0.9,
                delayed_reward=0.9,
                applied_to_bandit=False,  # explicitly pending
            )
        )


def test_rehydrate_rebuilds_posterior_from_applied_traces():
    ctx = "senior:technical_depth"
    for i in range(5):
        _insert_applied_trace(f"sess-win-{i}", i, ctx, DEEPEN_TECHNICAL.id, 1.0)
    for i in range(5):
        _insert_applied_trace(f"sess-lose-{i}", i, ctx, SWITCH_DIMENSION.id, 0.0)

    bandit = ThompsonBandit(exploration_rate=0.0, rng=random.Random(0))
    count = bandit.rehydrate_from_db()
    assert count == 10

    winning = bandit._params(ctx, DEEPEN_TECHNICAL.id)
    losing = bandit._params(ctx, SWITCH_DIMENSION.id)
    # winning arm: reward=1.0 five times -> alpha += 5, beta unchanged
    assert winning.alpha == pytest.approx(1.0 + 5.0)
    assert winning.beta == pytest.approx(1.0)
    # losing arm: reward=0.0 five times -> beta += 5, alpha unchanged
    assert losing.alpha == pytest.approx(1.0)
    assert losing.beta == pytest.approx(1.0 + 5.0)


def test_rehydrate_ignores_pending_traces():
    """Only rows already applied are replayed; pending rows are the
    scheduler's responsibility and would otherwise double-count."""
    _insert_pending_trace("sess-pending")

    bandit = ThompsonBandit(exploration_rate=0.0, rng=random.Random(0))
    count = bandit.rehydrate_from_db()
    assert count == 0
    # Posterior stays at the default Jeffreys-style prior (1, 1).
    p = bandit._params("senior:technical_depth", DEEPEN_TECHNICAL.id)
    assert p.alpha == pytest.approx(1.0)
    assert p.beta == pytest.approx(1.0)


def test_rehydrate_is_noop_on_empty_db():
    bandit = ThompsonBandit(exploration_rate=0.0, rng=random.Random(0))
    assert bandit.rehydrate_from_db() == 0
    assert bandit.priors == {}


def test_rehydrate_replays_all_policy_context_keys():
    global_ctx = "senior:technical_depth"
    direction_ctx = "java_backend:senior:technical_depth"
    _insert_applied_trace(
        "sess-policy-keys",
        0,
        global_ctx,
        DEEPEN_TECHNICAL.id,
        1.0,
        policy_context_keys=[direction_ctx, global_ctx],
    )

    bandit = ThompsonBandit(exploration_rate=0.0, rng=random.Random(0))
    count = bandit.rehydrate_from_db()
    assert count == 2

    assert bandit._params(direction_ctx, DEEPEN_TECHNICAL.id).alpha == pytest.approx(2.0)
    assert bandit._params(global_ctx, DEEPEN_TECHNICAL.id).alpha == pytest.approx(2.0)
