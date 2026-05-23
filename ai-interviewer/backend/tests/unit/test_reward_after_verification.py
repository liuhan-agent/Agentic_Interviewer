from __future__ import annotations

from contextlib import contextmanager
from typing import Any


def test_evaluator_node_does_not_update_bandit_before_verification(monkeypatch):
    from app.engine.workflow.nodes import evaluator as evaluator_node_mod

    def fake_evaluate(**_kwargs: Any) -> dict[str, Any]:
        return {
            "score": 8.5,
            "passed": True,
            "strengths": [],
            "weaknesses": [],
            "rubric_coverage": {},
            "acceptance_check_results": {},
            "recommended_next": "advance",
            "recommended_next_plan": None,
            "rationale": "",
        }

    updates: list[tuple[str, str, float]] = []

    class _Bandit:
        def update(self, context_key: str, action_id: str, reward: float) -> None:
            updates.append((context_key, action_id, reward))

    class _Tracer:
        def __init__(self) -> None:
            self.kwargs: dict[str, Any] = {}

        def trace_evaluator(self, *_args: Any, **kwargs: Any) -> None:
            self.kwargs.update(kwargs)

    tracer = _Tracer()
    persisted_turn: dict[str, Any] = {}

    @contextmanager
    def fake_get_session():
        yield object()

    def fake_upsert_interview_turn(_session, **kwargs: Any) -> None:
        persisted_turn.update(kwargs)

    monkeypatch.setattr(evaluator_node_mod, "evaluate_answer", fake_evaluate)
    monkeypatch.setattr(evaluator_node_mod, "get_bandit", lambda: _Bandit())
    monkeypatch.setattr(evaluator_node_mod, "get_tracer", lambda: tracer)
    monkeypatch.setattr(evaluator_node_mod, "get_session", fake_get_session)
    monkeypatch.setattr(evaluator_node_mod, "upsert_interview_turn", fake_upsert_interview_turn)

    state = {
        "session_id": "sess-reward",
        "trace_id": "trace-reward",
        "turn_idx": 0,
        "formal_turn_idx": 0,
        "current_question": {
            "question": "Q",
            "dimension": "system_design",
            "resume_anchor": {
                "anchor_key": "focus-payment-consistency",
                "label": "支付迁移中的幂等和一致性",
                "project_id": "proj-payment",
            },
        },
        "current_dimension": "system_design",
        "current_answer": "A concrete answer.",
        "scores_per_dim": {},
        "dimension_status": {},
        "quality_threshold": 7.0,
        "turn_budget_remaining": 3,
        "selected_action": {
            "id": "plan_adaptive",
            "policy_context_keys": ["senior:system_design"],
        },
        "job_spec": {"level": "senior"},
        "qa_history": [],
    }

    evaluator_node_mod.evaluator_node(state)  # type: ignore[arg-type]

    assert updates == []
    assert tracer.kwargs["immediate_reward_applied"] is False
    assert persisted_turn["resume_anchor_key"] == "focus-payment-consistency"
    assert persisted_turn["resume_anchor_label"] == "支付迁移中的幂等和一致性"
    assert persisted_turn["resume_project_id"] == "proj-payment"


def test_reward_update_uses_post_verification_evaluation(monkeypatch):
    from app.engine.workflow.nodes import reward_update as reward_update_mod

    captured: dict[str, Any] = {}
    updates: list[tuple[str, str, float]] = []

    def fake_reward(*, evaluation: dict[str, Any], contract: dict[str, Any] | None):
        captured["evaluation"] = evaluation
        captured["contract"] = contract
        return 0.42

    class _Bandit:
        def update(self, context_key: str, action_id: str, reward: float) -> None:
            updates.append((context_key, action_id, reward))

    class _Tracer:
        def trace_node_event(self, *_args: Any, **_kwargs: Any) -> None:
            return None

    monkeypatch.setattr(reward_update_mod, "immediate_reward", fake_reward)
    monkeypatch.setattr(reward_update_mod, "get_bandit", lambda: _Bandit())
    monkeypatch.setattr(reward_update_mod, "get_tracer", lambda: _Tracer())

    state = {
        "session_id": "sess-reward",
        "trace_id": "trace-reward",
        "turn_idx": 1,
        "current_dimension": "system_design",
        "current_question": {
            "question": "Q",
            "dimension": "system_design",
            "contract": {"must_cover": ["tradeoff"]},
        },
        "current_contract": {"must_cover": ["tradeoff"]},
        "evaluation": {
            "score": 8.5,
            "passed": False,
            "verifier_forced_refine": True,
        },
        "selected_action": {
            "id": "plan_adaptive",
            "policy_context_keys": ["senior:system_design"],
        },
        "job_spec": {"level": "senior"},
    }

    out = reward_update_mod.reward_update_node(state)  # type: ignore[arg-type]

    assert captured["evaluation"]["verifier_forced_refine"] is True
    assert updates == [("senior:system_design", "plan_adaptive", 0.42)]
    assert out["messages"][0]["kind"] == "reward_update"
    assert out["messages"][0]["immediate_reward"] == 0.42
