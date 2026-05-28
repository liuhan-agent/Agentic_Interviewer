from __future__ import annotations

from contextlib import contextmanager
from typing import Any

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
from app.models.skill_playbook import SkillUsage


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
    assert usages[0].verifier_overruled is False
