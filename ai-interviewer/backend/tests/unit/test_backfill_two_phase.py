"""Tests for the two-phase ``backfill_once`` flow introduced in Step 2.

Contract we lock in:

1. Normal path: DB rows get ``applied_to_bandit=True`` and the
   in-memory bandit sees the exact same updates (plus the
   ``ALIAS_MAP`` mirror write for legacy arm ids).
2. Phase-2 failure path: even if the in-memory bandit update raises
   *after* the DB commit, the DB is already the source of truth; a
   subsequent ``rehydrate_from_db`` call rebuilds the bandit to the
   same end-state as the normal path.
3. Idempotency: running ``backfill_once`` twice credits each trace
   exactly once because the DB flag gates the SELECT.
"""
from __future__ import annotations

import pytest
from sqlalchemy import delete

from app.ml.rl import outcome_reward_bridge as bridge_mod
from app.ml.rl.action_space import (
    DEEPEN_TECHNICAL,
    PLAN_ADAPTIVE,
    PLAN_SIMPLE,
)
from app.ml.rl.outcome_reward_bridge import backfill_once
from app.ml.rl.thompson import (
    ThompsonBandit,
    get_bandit,
    reset_bandit_for_tests,
)
from app.models import (
    GenerationTrace,
    OutcomeRecord,
    get_session,
    init_db,
)


@pytest.fixture(autouse=True)
def _fresh_db_and_bandit():
    init_db()
    with get_session() as sess:
        sess.execute(delete(GenerationTrace))
        sess.execute(delete(OutcomeRecord))
    reset_bandit_for_tests()
    yield
    with get_session() as sess:
        sess.execute(delete(GenerationTrace))
        sess.execute(delete(OutcomeRecord))
    reset_bandit_for_tests()


def _add_outcome(session_id: str, outcome: str = "hired") -> None:
    with get_session() as sess:
        sess.add(OutcomeRecord(session_id=session_id, outcome=outcome))


def _add_pending_trace(
    session_id: str,
    turn_idx: int,
    *,
    context_key: str,
    action_id: str,
    policy_context_keys: list[str] | None = None,
) -> None:
    with get_session() as sess:
        sess.add(
            GenerationTrace(
                trace_id=f"trace-{session_id}-{turn_idx}",
                session_id=session_id,
                turn_idx=turn_idx,
                node="evaluator",
                dimension="technical_depth",
                action_id=action_id,
                policy_id="thompson_v1::template::senior:technical_depth",
                context_key=context_key,
                policy_context_keys=policy_context_keys,
                score=8.0,
                passed=True,
                immediate_reward=0.9,
                applied_to_bandit=False,
            )
        )


def test_backfill_normal_path_updates_db_and_bandit():
    ctx = "senior:technical_depth"
    _add_outcome("sess-1", outcome="hired")
    _add_pending_trace("sess-1", 0, context_key=ctx, action_id=PLAN_ADAPTIVE.id)
    _add_pending_trace("sess-1", 1, context_key=ctx, action_id=PLAN_ADAPTIVE.id)

    counters = backfill_once()
    assert counters["sessions"] == 1
    assert counters["traces"] == 2

    with get_session() as sess:
        rows = list(sess.query(GenerationTrace))
    assert all(r.applied_to_bandit for r in rows)
    assert all(r.delayed_reward == pytest.approx(1.0) for r in rows)

    # Two updates on plan_adaptive => alpha grows by 2, beta unchanged.
    p = get_bandit()._params(ctx, PLAN_ADAPTIVE.id)
    assert p.alpha == pytest.approx(1.0 + 2.0)
    assert p.beta == pytest.approx(1.0)


def test_backfill_mirrors_legacy_action_to_template_alias():
    """Legacy ``deepen_technical`` traces must also credit
    ``plan_adaptive`` via the ``ALIAS_MAP`` mirror write."""
    ctx = "senior:technical_depth"
    _add_outcome("sess-legacy", outcome="hired")
    _add_pending_trace(
        "sess-legacy", 0, context_key=ctx, action_id=DEEPEN_TECHNICAL.id
    )

    backfill_once()

    bandit = get_bandit()
    legacy = bandit._params(ctx, DEEPEN_TECHNICAL.id)
    template = bandit._params(ctx, PLAN_ADAPTIVE.id)
    assert legacy.alpha == pytest.approx(2.0)
    assert template.alpha == pytest.approx(2.0), (
        "alias mirror-write was dropped during the Step-2 refactor"
    )


def test_backfill_is_idempotent_when_run_twice():
    ctx = "senior:technical_depth"
    _add_outcome("sess-2", outcome="hired")
    _add_pending_trace("sess-2", 0, context_key=ctx, action_id=PLAN_SIMPLE.id)

    first = backfill_once()
    second = backfill_once()

    assert first["traces"] == 1
    assert second["traces"] == 0, "second run must be a no-op"

    p = get_bandit()._params(ctx, PLAN_SIMPLE.id)
    # Exactly one credit, not two.
    assert p.alpha == pytest.approx(1.0 + 1.0)


def test_backfill_phase2_failure_still_recoverable_via_rehydrate(monkeypatch):
    """Simulate an in-memory crash *after* DB commit: the DB has
    already stamped ``applied_to_bandit=True``; ``rehydrate_from_db``
    must restore the exact same posterior the normal path would have
    produced."""
    ctx = "senior:technical_depth"
    _add_outcome("sess-crash", outcome="hired")
    _add_pending_trace("sess-crash", 0, context_key=ctx, action_id=PLAN_ADAPTIVE.id)

    # Patch the thompson module's get_bandit lookup so Phase 2 crashes
    # AFTER the DB commit.  The bridge imports ``get_bandit`` locally
    # so we patch the attribute on the bridge module itself.
    class _Boom(ThompsonBandit):
        def update(self, *_a, **_kw):  # type: ignore[override]
            raise RuntimeError("simulated bandit crash")

    monkeypatch.setattr(bridge_mod, "get_bandit", lambda: _Boom())

    with pytest.raises(RuntimeError):
        backfill_once()

    # DB side should be committed despite the Phase-2 crash.
    with get_session() as sess:
        row = sess.query(GenerationTrace).one()
    assert row.applied_to_bandit is True
    assert row.delayed_reward == pytest.approx(1.0)

    # Now restore the real get_bandit and rehydrate from the DB.
    monkeypatch.undo()
    reset_bandit_for_tests()
    fresh = get_bandit()
    restored = fresh.rehydrate_from_db()
    assert restored >= 1

    p = fresh._params(ctx, PLAN_ADAPTIVE.id)
    assert p.alpha == pytest.approx(2.0), (
        "Phase 2 crash + rehydrate must converge to the same end state "
        "as the happy path"
    )


def test_backfill_updates_direction_and_global_policy_keys():
    global_ctx = "senior:technical_depth"
    direction_ctx = "java_backend:senior:technical_depth"
    _add_outcome("sess-policy", outcome="hired")
    _add_pending_trace(
        "sess-policy",
        0,
        context_key=direction_ctx,
        policy_context_keys=[direction_ctx, global_ctx],
        action_id=PLAN_ADAPTIVE.id,
    )

    counters = backfill_once()
    assert counters["traces"] == 1

    bandit = get_bandit()
    assert bandit._params(direction_ctx, PLAN_ADAPTIVE.id).alpha == pytest.approx(2.0)
    assert bandit._params(global_ctx, PLAN_ADAPTIVE.id).alpha == pytest.approx(2.0)
