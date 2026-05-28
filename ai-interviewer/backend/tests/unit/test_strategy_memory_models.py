from __future__ import annotations

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
from app.models.strategy_memory import (
    StrategyMemory,
    StrategyMemoryUsage,
    StrategySignal,
)
from app.models.strategy_learning import BanditPosterior, InterviewTurn


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
                display_name_zh="系统设计深挖策略",
                display_description_zh="用于高级候选人的系统设计深挖追问。",
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
    assert row.display_name_zh == "系统设计深挖策略"
    assert row.display_description_zh == "用于高级候选人的系统设计深挖追问。"
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


def test_strategy_fact_models_round_trip_turns_and_posteriors() -> None:
    Session = _session_factory()
    with Session() as sess:
        sess.add(
            InterviewTurn(
                session_id="sess-facts",
                turn_idx=1,
                trace_id="trace-facts",
                dimension="system_design",
                job_level="senior",
                question="How would you design a feed?",
                answer="Sanitised candidate answer",
                resume_anchor_key="focus-feed-architecture",
                resume_anchor_label="Feed 架构演进",
                resume_project_id="proj-feed",
                selected_action="plan_deep_probe",
                policy_context_keys=[
                    "java_backend:senior:system_design",
                    "senior:system_design",
                ],
                evaluation={
                    "score": 8.5,
                    "passed": True,
                    "failure_categories": ["missing_tradeoff"],
                },
                failure_categories=["missing_tradeoff"],
                verifier_triggered=True,
                verifier_forced_refine=False,
                verifier_verdict="agree",
                immediate_reward=0.84,
                selection_artifacts={"question_selector_mode": "structured_primary"},
            )
        )
        sess.add(
            BanditPosterior(
                context_key="java_backend:senior:system_design",
                action_id="plan_deep_probe",
                alpha=8.0,
                beta=2.0,
                observation_count=8,
                immediate_update_count=8,
                delayed_update_count=0,
                last_reward=0.75,
                last_session_id="sess-facts",
                last_turn_idx=1,
            )
        )
        sess.commit()

        turn = sess.scalar(select(InterviewTurn))
        posterior = sess.scalar(select(BanditPosterior))

    assert turn is not None
    assert turn.answer == "Sanitised candidate answer"
    assert turn.resume_anchor_key == "focus-feed-architecture"
    assert turn.resume_anchor_label == "Feed 架构演进"
    assert turn.resume_project_id == "proj-feed"
    assert turn.policy_context_keys == [
        "java_backend:senior:system_design",
        "senior:system_design",
    ]
    assert turn.evaluation["score"] == 8.5
    assert turn.failure_categories == ["missing_tradeoff"]
    assert turn.verifier_triggered is True
    assert turn.immediate_reward == 0.84

    assert posterior is not None
    assert posterior.context_key == "java_backend:senior:system_design"
    assert posterior.action_id == "plan_deep_probe"
    assert posterior.alpha == 8.0
    assert posterior.beta == 2.0
    assert posterior.observation_count == 8
