from __future__ import annotations

from contextlib import contextmanager
from typing import Any

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
from app.models.strategy_memory import StrategyMemoryUsage


def test_reward_update_writes_strategy_memory_usage(monkeypatch) -> None:
    from app.engine.workflow.nodes import reward_update as reward_update_mod

    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)

    @contextmanager
    def get_session():
        with Session() as sess:
            yield sess
            sess.commit()

    updates: list[tuple[str, str, float]] = []

    class _Bandit:
        def update(self, context_key: str, action_id: str, reward: float) -> None:
            updates.append((context_key, action_id, reward))

    class _Tracer:
        def trace_node_event(self, *_args: Any, **_kwargs: Any) -> None:
            return None

    monkeypatch.setattr(reward_update_mod, "immediate_reward", lambda **_kwargs: 0.42)
    monkeypatch.setattr(reward_update_mod, "get_bandit", lambda: _Bandit())
    monkeypatch.setattr(reward_update_mod, "get_tracer", lambda: _Tracer())
    monkeypatch.setattr(reward_update_mod, "get_session", get_session)

    state = {
        "session_id": "sess-usage",
        "trace_id": "trace-usage",
        "turn_idx": 3,
        "current_dimension": "system_design",
        "current_question": {
            "question": "请结合订单系统讲一次系统设计取舍。",
            "dimension": "system_design",
            "strategy_memory_refs": [
                {
                    "id": "seed:senior_system_design",
                    "slug": "senior_system_design",
                    "memory_key": "seed:system_design:senior",
                    "name": "Senior System Design",
                }
            ],
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

    with Session() as sess:
        usages = list(sess.scalars(select(StrategyMemoryUsage)))

    assert updates == [("senior:system_design", "plan_adaptive", 0.42)]
    assert len(usages) == 1
    usage = usages[0]
    assert usage.strategy_id == "seed:senior_system_design"
    assert usage.session_id == "sess-usage"
    assert usage.trace_id == "trace-usage"
    assert usage.turn_idx == 2
    assert usage.context_key == "senior:system_design"
    assert usage.action_id == "plan_adaptive"
    assert usage.plan_template == "adaptive"
    assert usage.score == 8.0
    assert usage.passed is True
    assert usage.immediate_reward == 0.42
    assert usage.verifier_overruled is False
    assert usage.question_text_hash is not None
    assert usage.question_text_hash.startswith("sha1:")
