from __future__ import annotations

from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.ml.rl import outcome_reward_bridge as bridge_mod
from app.ml.rl.action_space import PLAN_ADAPTIVE
from app.ml.rl.outcome_reward_bridge import backfill_once
from app.ml.rl.thompson import reset_bandit_for_tests
from app.models import GenerationTrace, OutcomeRecord
from app.models.base import Base
from app.models.strategy_memory import StrategyMemoryUsage


def _session_context():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)

    @contextmanager
    def get_session():
        with Session() as sess:
            yield sess
            sess.commit()

    return Session, get_session


@pytest.fixture(autouse=True)
def _fresh_bandit():
    reset_bandit_for_tests()
    yield
    reset_bandit_for_tests()


def _add_outcome(get_session, session_id: str) -> None:
    with get_session() as sess:
        sess.add(
            OutcomeRecord(
                session_id=session_id,
                outcome="hired",
                source="user_feedback",
                helpful_score=0.8,
            )
        )


def _add_pending_trace(
    get_session,
    session_id: str,
    *,
    turn_idx: int,
    context_keys: list[str],
) -> None:
    with get_session() as sess:
        sess.add(
            GenerationTrace(
                trace_id=f"trace-{session_id}-{turn_idx}",
                session_id=session_id,
                turn_idx=turn_idx,
                node="evaluator",
                dimension="system_design",
                action_id=PLAN_ADAPTIVE.id,
                policy_id="thompson_v1::template::senior:system_design",
                context_key=context_keys[0],
                policy_context_keys=context_keys,
                score=8.0,
                passed=True,
                immediate_reward=0.7,
                applied_to_bandit=False,
            )
        )


def _add_strategy_usage(
    get_session,
    session_id: str,
    *,
    turn_idx: int,
    context_key: str,
    strategy_id: str = "seed:senior_system_design",
) -> None:
    with get_session() as sess:
        sess.add(
            StrategyMemoryUsage(
                id=f"usage-{context_key}",
                strategy_id=strategy_id,
                session_id=session_id,
                turn_idx=turn_idx,
                trace_id=f"trace-{session_id}-{turn_idx}",
                context_key=context_key,
                action_id=PLAN_ADAPTIVE.id,
                plan_template="adaptive",
                immediate_reward=0.7,
            )
        )


def test_backfill_copies_delayed_reward_to_matching_strategy_usages(monkeypatch) -> None:
    Session, get_session = _session_context()
    monkeypatch.setattr(bridge_mod, "get_session", get_session)
    context_keys = ["java_backend:senior:system_design", "senior:system_design"]
    _add_outcome(get_session, "sess-usage")
    _add_pending_trace(get_session, "sess-usage", turn_idx=2, context_keys=context_keys)
    for context_key in context_keys:
        _add_strategy_usage(
            get_session,
            "sess-usage",
            turn_idx=2,
            context_key=context_key,
        )

    counters = backfill_once()

    assert counters["traces"] == 1
    assert counters["strategy_usages"] == 2
    with Session() as sess:
        trace = sess.query(GenerationTrace).one()
        usages = (
            sess.query(StrategyMemoryUsage)
            .order_by(StrategyMemoryUsage.context_key.asc())
            .all()
        )

    assert trace.delayed_reward is not None
    assert all(row.delayed_reward == pytest.approx(trace.delayed_reward) for row in usages)
    assert all(row.helpful_score == pytest.approx(0.8) for row in usages)


def test_backfill_skips_when_strategy_usage_is_absent(monkeypatch) -> None:
    _, get_session = _session_context()
    monkeypatch.setattr(bridge_mod, "get_session", get_session)
    _add_outcome(get_session, "sess-no-usage")
    _add_pending_trace(
        get_session,
        "sess-no-usage",
        turn_idx=0,
        context_keys=["senior:system_design"],
    )

    counters = backfill_once()

    assert counters["traces"] == 1
    assert counters["strategy_usages"] == 0
