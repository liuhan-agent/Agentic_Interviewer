from __future__ import annotations

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.models.base import Base
from app.models.strategy_memory import StrategyMemory, StrategySignal
from app.services.strategy_promotion import (
    StrategyPromotionResult,
    promote_strategy_signals,
)


def _session_factory():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)


def _add_signal(
    sess: Session,
    *,
    idx: int,
    group_key: str = "qa:score_recovery:senior:system_design:plan_hint",
    reward: float = 0.74,
    score_after: float = 7.6,
    overruled: bool = False,
) -> None:
    sess.add(
        StrategySignal(
            id=f"signal-{idx}",
            signal_key=f"sess-{idx}:{group_key}",
            group_key=group_key,
            session_id=f"sess-{idx}",
            turn_idx=idx,
            dimension="system_design",
            job_level="senior",
            action_id="plan_hint",
            plan_template="simple",
            probe_intent="metric_probe",
            failure_categories=["missing_metrics"],
            score_before=5.0,
            score_after=score_after,
            score_delta=score_after - 5.0,
            immediate_reward=reward,
            verifier_overruled=overruled,
            signal_type="score_recovery",
            status="observed",
        )
    )


def test_promote_strategy_signals_ignores_under_supported_groups() -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as sess:
        for idx in range(1, 10):
            _add_signal(sess, idx=idx)
        result = promote_strategy_signals(session=sess)
        sess.commit()
        memories = list(sess.scalars(select(StrategyMemory)))

    assert result.promoted == 0
    assert result.skipped == 1
    assert memories == []


def test_promote_strategy_signals_creates_low_confidence_active_strategy() -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as sess:
        for idx in range(1, 31):
            _add_signal(sess, idx=idx)
        result = promote_strategy_signals(session=sess)
        second = promote_strategy_signals(session=sess)
        sess.commit()

        memories = list(sess.scalars(select(StrategyMemory)))
        signals = list(sess.scalars(select(StrategySignal)))

    assert result.promoted == 1
    assert second.unchanged == 1
    assert len(memories) == 1

    memory = memories[0]
    assert memory.id.startswith("promoted:")
    assert memory.source == "promoted_signal"
    assert memory.status == "active"
    assert memory.promotion_stage == "low_confidence"
    assert memory.dimensions == ["system_design"]
    assert memory.job_levels == ["senior"]
    assert memory.failure_categories == ["missing_metrics"]
    assert memory.recommended_action == "plan_hint"
    assert memory.recommended_plan_template == "simple"
    assert memory.recommended_probe_intent == "metric_probe"
    assert memory.support_count == 30
    assert memory.confidence >= 0.35
    assert "30 sessions" in memory.body_markdown

    assert {signal.status for signal in signals} == {"promoted"}


def test_run_strategy_promotion_now_wraps_service(monkeypatch) -> None:
    from app.tasks import strategy_promotion_tasks as tasks

    calls: list[str] = []

    class _Session:
        pass

    class _Context:
        def __enter__(self):
            calls.append("enter")
            return _Session()

        def __exit__(self, exc_type, exc, tb):
            calls.append("exit")
            return False

    monkeypatch.setattr(tasks, "get_session", lambda: _Context())
    monkeypatch.setattr(
        tasks,
        "promote_strategy_signals",
        lambda *, session: StrategyPromotionResult(promoted=1, unchanged=2, skipped=3),
    )

    result = tasks.run_strategy_promotion_now()

    assert calls == ["enter", "exit"]
    assert result == {"promoted": 1, "unchanged": 2, "skipped": 3}
