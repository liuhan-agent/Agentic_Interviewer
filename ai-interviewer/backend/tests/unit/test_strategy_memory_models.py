from __future__ import annotations

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
from app.models.strategy_memory import (
    StrategyMemory,
    StrategyMemoryUsage,
    StrategySignal,
)


def _session_factory():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)


def test_strategy_memory_round_trips_structured_metadata() -> None:
    Session = _session_factory()
    with Session() as sess:
        sess.add(
            StrategyMemory(
                id="strat-system-design-deep-probe",
                slug="system-design-deep-probe",
                name="System design deep probe",
                description="Probe scale and failure modes for senior candidates.",
                source="seed",
                memory_key="seed:system_design:deep_probe",
                dimensions=["system_design"],
                job_levels=["senior", "staff"],
                failure_categories=["missing_metrics", "missing_tradeoff"],
                recommended_action="plan_deep_probe",
                recommended_plan_template="deep_probe",
                recommended_probe_intent="architecture_challenge",
                body_markdown="Ask for one quantified scale argument and one failure mode.",
                status="active",
                priority=20,
                confidence=0.75,
                support_count=42,
                promotion_stage="seed",
                version=3,
                content_hash="sha1:abc123",
            )
        )
        sess.commit()

        row = sess.scalar(
            select(StrategyMemory).where(
                StrategyMemory.id == "strat-system-design-deep-probe"
            )
        )

    assert row is not None
    assert row.dimensions == ["system_design"]
    assert row.job_levels == ["senior", "staff"]
    assert row.failure_categories == ["missing_metrics", "missing_tradeoff"]
    assert row.recommended_plan_template == "deep_probe"
    assert row.status == "active"
    assert row.priority == 20
    assert row.confidence == 0.75
    assert row.support_count == 42
    assert row.version == 3


def test_strategy_signal_and_usage_round_trip_rewards() -> None:
    Session = _session_factory()
    with Session() as sess:
        sess.add(
            StrategyMemory(
                id="strat-hint-system-design",
                slug="hint-system-design",
                name="Hint for system design",
                description="Use hints when system-design answers are incomplete.",
                source="promoted_signal",
                memory_key="signal:system_design:plan_hint",
                dimensions=["system_design"],
                job_levels=["senior"],
                body_markdown="Prefer a targeted hint before switching dimensions.",
                status="active",
            )
        )
        sess.add(
            StrategySignal(
                id="signal-1",
                signal_key="sess-1:2:system_design:plan_hint",
                group_key="system_design:senior:plan_hint:missing_metrics",
                session_id="sess-1",
                turn_idx=2,
                dimension="system_design",
                job_level="senior",
                action_id="plan_hint",
                plan_template="simple",
                probe_intent="metric_probe",
                failure_categories=["missing_metrics"],
                score_before=5.0,
                score_after=8.0,
                score_delta=3.0,
                immediate_reward=0.82,
                verifier_overruled=False,
                signal_type="score_recovery",
                status="observed",
            )
        )
        sess.add(
            StrategyMemoryUsage(
                id="usage-1",
                strategy_id="strat-hint-system-design",
                session_id="sess-1",
                turn_idx=3,
                trace_id="trace-1",
                context_key="senior:system_design",
                action_id="plan_hint",
                plan_template="simple",
                question_text_hash="sha1:q1",
                score=8.0,
                passed=True,
                immediate_reward=0.82,
                delayed_reward=0.7,
                verifier_overruled=False,
                helpful_score=0.75,
            )
        )
        sess.commit()

        signal = sess.scalar(select(StrategySignal))
        usage = sess.scalar(select(StrategyMemoryUsage))

    assert signal is not None
    assert signal.failure_categories == ["missing_metrics"]
    assert signal.score_delta == 3.0
    assert signal.immediate_reward == 0.82
    assert signal.status == "observed"

    assert usage is not None
    assert usage.strategy_id == "strat-hint-system-design"
    assert usage.context_key == "senior:system_design"
    assert usage.score == 8.0
    assert usage.passed is True
    assert usage.immediate_reward == 0.82
    assert usage.delayed_reward == 0.7
