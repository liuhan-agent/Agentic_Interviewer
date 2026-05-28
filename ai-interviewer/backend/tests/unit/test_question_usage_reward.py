from __future__ import annotations

from contextlib import contextmanager
from typing import Any

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
from app.models.question_bank import QuestionUsage
from app.models.skill_playbook import SkillUsage


def test_reward_update_backfills_only_structured_primary_injected_rank_one(
    monkeypatch,
) -> None:
    from app.engine.workflow.nodes import reward_update as reward_update_mod

    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    session_local = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)

    with session_local() as sess:
        sess.add_all(
            [
                QuestionUsage(
                    id="usage-primary-injected",
                    session_id="sess-question-usage",
                    turn_idx=2,
                    trace_id="trace-question-usage",
                    seed_id="system_design.cache_consistency",
                    variant_id="system_design.cache_consistency.flash_sale_inventory",
                    seed_version=1,
                    variant_version=1,
                    rank=1,
                    match_score=42.0,
                    match_reasons=["priority:30"],
                    injected=True,
                    question_selector_mode="structured_primary",
                ),
                QuestionUsage(
                    id="usage-primary-shadow-rank2",
                    session_id="sess-question-usage",
                    turn_idx=2,
                    trace_id="trace-question-usage",
                    seed_id="system_design.capacity_planning",
                    variant_id="system_design.capacity_planning.live_event_ticketing",
                    seed_version=1,
                    variant_version=1,
                    rank=2,
                    match_score=20.0,
                    match_reasons=["priority:20"],
                    injected=False,
                    question_selector_mode="structured_primary",
                ),
                QuestionUsage(
                    id="usage-shadow-rank1",
                    session_id="sess-question-usage",
                    turn_idx=2,
                    trace_id="trace-question-usage",
                    seed_id="system_design.observability_slo",
                    variant_id="system_design.observability_slo.checkout_latency",
                    seed_version=1,
                    variant_version=1,
                    rank=1,
                    match_score=18.0,
                    match_reasons=["priority:18"],
                    injected=False,
                    question_selector_mode="structured_shadow",
                ),
            ]
        )
        sess.commit()

    @contextmanager
    def get_session():
        with session_local() as sess:
            yield sess
            sess.commit()

    class _Bandit:
        def update(self, *_args: Any, **_kwargs: Any) -> None:
            return None

    class _Tracer:
        def trace_node_event(self, *_args: Any, **_kwargs: Any) -> None:
            return None

    monkeypatch.setattr(reward_update_mod, "immediate_reward", lambda **_kwargs: 0.42)
    monkeypatch.setattr(reward_update_mod, "get_bandit", lambda: _Bandit())
    monkeypatch.setattr(reward_update_mod, "get_tracer", lambda: _Tracer())
    monkeypatch.setattr(reward_update_mod, "get_session", get_session)

    state = {
        "session_id": "sess-question-usage",
        "trace_id": "trace-question-usage",
        "turn_idx": 3,
        "current_dimension": "system_design",
        "current_question": {
            "question": "请设计库存缓存一致性方案。",
            "dimension": "system_design",
            "selection_artifacts": {
                "question_items": [
                    {
                        "seed_id": "system_design.cache_consistency",
                        "variant_id": (
                            "system_design.cache_consistency.flash_sale_inventory"
                        ),
                        "rank": 1,
                        "injected": True,
                        "question_selector_mode": "structured_primary",
                    },
                    {
                        "seed_id": "system_design.capacity_planning",
                        "variant_id": (
                            "system_design.capacity_planning.live_event_ticketing"
                        ),
                        "rank": 2,
                        "injected": False,
                        "question_selector_mode": "structured_primary",
                    },
                ]
            },
        },
        "evaluation": {"score": 8.0, "passed": True},
        "selected_action": {
            "id": "plan_adaptive",
            "plan_template": "adaptive",
            "policy_context_keys": ["senior:system_design"],
        },
        "job_spec": {"level": "senior"},
    }

    reward_update_mod.reward_update_node(state)  # type: ignore[arg-type]

    with session_local() as sess:
        usages = {
            row.id: row
            for row in sess.scalars(select(QuestionUsage).order_by(QuestionUsage.id))
        }

    injected = usages["usage-primary-injected"]
    assert injected.score == 8.0
    assert injected.passed is True
    assert injected.immediate_reward == 0.42

    assert usages["usage-primary-shadow-rank2"].score is None
    assert usages["usage-primary-shadow-rank2"].immediate_reward is None
    assert usages["usage-shadow-rank1"].score is None
    assert usages["usage-shadow-rank1"].immediate_reward is None


def test_reward_update_backfills_question_usage_by_formal_turn_idx(
    monkeypatch,
) -> None:
    from app.engine.workflow.nodes import reward_update as reward_update_mod

    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    session_local = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)

    variant_id = "technical_depth.java_transaction_consistency.order_payment_boundary"
    with session_local() as sess:
        sess.add(
            QuestionUsage(
                id="usage-formal-turn-zero",
                session_id="sess-formal-turn",
                turn_idx=0,
                trace_id="trace-formal-turn",
                seed_id="technical_depth.java_transaction_consistency",
                variant_id=variant_id,
                seed_version=1,
                variant_version=1,
                rank=1,
                match_score=42.0,
                match_reasons=["priority:30"],
                injected=True,
                question_selector_mode="structured_primary",
            )
        )
        sess.commit()

    @contextmanager
    def get_session():
        with session_local() as sess:
            yield sess
            sess.commit()

    class _Bandit:
        def update(self, *_args: Any, **_kwargs: Any) -> None:
            return None

    class _Tracer:
        def trace_node_event(self, *_args: Any, **_kwargs: Any) -> None:
            return None

    monkeypatch.setattr(reward_update_mod, "immediate_reward", lambda **_kwargs: 0.84)
    monkeypatch.setattr(reward_update_mod, "get_bandit", lambda: _Bandit())
    monkeypatch.setattr(reward_update_mod, "get_tracer", lambda: _Tracer())
    monkeypatch.setattr(reward_update_mod, "get_session", get_session)

    state = {
        "session_id": "sess-formal-turn",
        "trace_id": "trace-formal-turn",
        # The evaluator increments workflow turn_idx before reward_update.
        "turn_idx": 2,
        # question_usages and interview turn facts use zero-based formal turns.
        "formal_turn_idx": 1,
        "current_dimension": "technical_depth",
        "current_question": {
            "question": "请说明订单支付边界。",
            "dimension": "technical_depth",
            "selection_artifacts": {
                "question_items": [
                    {
                        "seed_id": "technical_depth.java_transaction_consistency",
                        "variant_id": variant_id,
                        "rank": 1,
                        "injected": True,
                        "question_selector_mode": "structured_primary",
                    }
                ]
            },
        },
        "evaluation": {"score": 8.5, "passed": True},
        "selected_action": {
            "id": "plan_adaptive",
            "policy_context_keys": ["junior:technical_depth"],
        },
        "job_spec": {"level": "junior"},
    }

    reward_update_mod.reward_update_node(state)  # type: ignore[arg-type]

    with session_local() as sess:
        usage = sess.get(QuestionUsage, "usage-formal-turn-zero")

    assert usage is not None
    assert usage.score == 8.5
    assert usage.passed is True
    assert usage.immediate_reward == 0.84


def test_reward_update_records_skill_usage_for_injected_skill_refs(
    monkeypatch,
) -> None:
    from app.engine.workflow.nodes import reward_update as reward_update_mod

    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    session_local = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)

    @contextmanager
    def get_session():
        with session_local() as sess:
            yield sess
            sess.commit()

    class _Bandit:
        def update(self, *_args: Any, **_kwargs: Any) -> None:
            return None

    class _Tracer:
        def trace_node_event(self, *_args: Any, **_kwargs: Any) -> None:
            return None

    monkeypatch.setattr(reward_update_mod, "immediate_reward", lambda **_kwargs: 0.66)
    monkeypatch.setattr(reward_update_mod, "get_bandit", lambda: _Bandit())
    monkeypatch.setattr(reward_update_mod, "get_tracer", lambda: _Tracer())
    monkeypatch.setattr(reward_update_mod, "get_session", get_session)

    state = {
        "session_id": "sess-skill-usage",
        "trace_id": "trace-skill-usage",
        "turn_idx": 4,
        "formal_turn_idx": 3,
        "current_dimension": "system_design",
        "runtime_config": {"question_role_tags": ["java_backend"]},
        "current_question": {
            "question": "How would you debug duplicate delivery?",
            "dimension": "system_design",
            "probe_intent": "evidence_probe",
            "selection_artifacts": {
                "skills": {
                    "enabled": True,
                    "refs": [
                        {
                            "id": "tech_debug_root_cause_probe",
                            "rank": 1,
                            "match_score": 77.0,
                            "match_reasons": [
                                "priority:9",
                                "probe_intent:evidence_probe",
                            ],
                            "evaluator_visibility": True,
                        },
                        {
                            "id": "tech_latency_probe",
                            "rank": 2,
                            "match_score": 61.0,
                            "match_reasons": ["priority:4"],
                            "evaluator_visibility": False,
                        },
                    ],
                }
            },
        },
        "evaluation": {"score": 7.5, "passed": True},
        "selected_action": {
            "id": "plan_adaptive",
            "plan_template": "adaptive",
            "policy_context_keys": ["internet_tech:junior:system_design"],
        },
        "job_spec": {
            "level": "junior",
            "role_tags": ["java_backend"],
        },
    }

    reward_update_mod.reward_update_node(state)  # type: ignore[arg-type]

    with session_local() as sess:
        usages = list(sess.scalars(select(SkillUsage).order_by(SkillUsage.rank)))

    assert [usage.skill_id for usage in usages] == [
        "tech_debug_root_cause_probe",
        "tech_latency_probe",
    ]
    assert usages[0].skill_context_key == (
        "java_backend:junior:system_design:evidence_probe"
    )
    assert usages[0].role == "java_backend"
    assert usages[0].job_level == "junior"
    assert usages[0].dimension == "system_design"
    assert usages[0].probe_intent == "evidence_probe"
    assert usages[0].match_score == 77.0
    assert usages[0].match_reasons == [
        "priority:9",
        "probe_intent:evidence_probe",
    ]
    assert usages[0].evaluator_visibility is True
    assert usages[0].score == 7.5
    assert usages[0].passed is True
    assert usages[0].immediate_reward == 0.66
