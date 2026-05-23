from __future__ import annotations

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
from app.models.strategy_learning import BanditPosterior, InterviewTurn
from app.services.strategy_learning_facts import (
    apply_bandit_posterior_update,
    upsert_interview_turn,
)


def _session_factory():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)


def test_interview_turn_upsert_is_idempotent_per_session_turn() -> None:
    session_factory = _session_factory()
    with session_factory() as sess:
        upsert_interview_turn(
            sess,
            session_id="sess-upsert",
            turn_idx=0,
            trace_id="trace-1",
            dimension="technical_depth",
            job_level="senior",
            question="First version?",
            answer="sanitised",
            selected_action="plan_deep_probe",
            evaluation={"score": 5.0},
            failure_categories=[],
        )
        upsert_interview_turn(
            sess,
            session_id="sess-upsert",
            turn_idx=0,
            trace_id="trace-2",
            dimension="technical_depth",
            job_level="senior",
            question="Updated version?",
            answer="sanitised again",
            selected_action="plan_hint",
            resume_anchor_key="focus-proj-1-abc123",
            resume_anchor_label="支付迁移中的幂等和一致性",
            resume_project_id="proj-1",
            evaluation={"score": 8.0, "failure_categories": ["missing_evidence"]},
            failure_categories=["missing_evidence"],
            immediate_reward=0.82,
        )
        sess.commit()

        rows = list(sess.scalars(select(InterviewTurn)))

    assert len(rows) == 1
    assert rows[0].trace_id == "trace-2"
    assert rows[0].question == "Updated version?"
    assert rows[0].selected_action == "plan_hint"
    assert rows[0].resume_anchor_key == "focus-proj-1-abc123"
    assert rows[0].resume_anchor_label == "支付迁移中的幂等和一致性"
    assert rows[0].resume_project_id == "proj-1"
    assert rows[0].evaluation["score"] == 8.0
    assert rows[0].failure_categories == ["missing_evidence"]
    assert rows[0].immediate_reward == 0.82


def test_bandit_posterior_update_accumulates_fractional_rewards() -> None:
    session_factory = _session_factory()
    with session_factory() as sess:
        apply_bandit_posterior_update(
            sess,
            context_key="senior:technical_depth",
            action_id="plan_deep_probe",
            reward=1.0,
            reward_kind="immediate",
            session_id="sess-bandit",
            turn_idx=0,
        )
        apply_bandit_posterior_update(
            sess,
            context_key="senior:technical_depth",
            action_id="plan_deep_probe",
            reward=0.25,
            reward_kind="immediate",
            session_id="sess-bandit",
            turn_idx=1,
        )
        sess.commit()

        row = sess.scalar(select(BanditPosterior))

    assert row is not None
    assert row.alpha == pytest.approx(2.25)
    assert row.beta == pytest.approx(1.75)
    assert row.observation_count == 2
    assert row.immediate_update_count == 2
    assert row.delayed_update_count == 0
    assert row.last_reward == pytest.approx(0.25)
    assert row.last_session_id == "sess-bandit"
    assert row.last_turn_idx == 1
