from __future__ import annotations

from typing import Any


def test_classify_answer_intent_handles_non_scoring_inputs() -> None:
    from app.engine.workflow.answer_lifecycle import classify_answer_intent

    previous = ["我负责 Redis 缓存设计。"]

    assert classify_answer_intent("", previous) == "empty"
    assert classify_answer_intent("什么意思？", previous) == "clarification"
    assert classify_answer_intent("我负责 Redis 缓存设计。", previous) == "repeat"
    assert classify_answer_intent("__skip_question__", previous) == "skipped"
    assert classify_answer_intent("不会", previous) == "too_short"
    assert (
        classify_answer_intent(
            "我负责 Redis 缓存设计，并根据命中率调整过期策略。",
            previous,
        )
        == "normal"
    )


def test_wait_answer_writes_current_answer_intent(monkeypatch) -> None:
    from app.engine.workflow.nodes import wait_answer as wait_answer_mod

    class _Provider:
        def get(self, *_args: Any, **_kwargs: Any) -> str:
            return "能再解释一下这个问题吗？"

    monkeypatch.setattr(wait_answer_mod, "_use_sync_provider", lambda _state: True)
    monkeypatch.setattr(wait_answer_mod, "_resolve_provider", lambda _state: _Provider())

    out = wait_answer_mod.wait_answer_node(
        {
            "session_id": "sess-answer-intent",
            "turn_idx": 0,
            "runtime_config": {},
            "current_question": {
                "question": "请说明一次系统设计取舍。",
                "dimension": "system_design",
            },
            "qa_history": [],
        }
    )  # type: ignore[arg-type]

    assert out["current_answer"] == "能再解释一下这个问题吗？"
    assert out["current_answer_intent"] == "clarification"


def test_reward_update_skips_non_scoring_answer_intent(monkeypatch) -> None:
    from app.engine.workflow.nodes import reward_update as reward_update_mod

    updates: list[tuple[str, str, float]] = []

    class _Bandit:
        def update(self, context_key: str, action_id: str, reward: float) -> None:
            updates.append((context_key, action_id, reward))

    class _Tracer:
        def trace_node_event(self, *_args: Any, **_kwargs: Any) -> None:
            return None

    monkeypatch.setattr(reward_update_mod, "get_bandit", lambda: _Bandit())
    monkeypatch.setattr(reward_update_mod, "get_tracer", lambda: _Tracer())

    out = reward_update_mod.reward_update_node(
        {
            "session_id": "sess-answer-intent",
            "trace_id": "trace-answer-intent",
            "turn_idx": 1,
            "current_dimension": "system_design",
            "current_answer_intent": "clarification",
            "current_question": {
                "question": "Q",
                "dimension": "system_design",
                "contract": {"must_cover": ["tradeoff"]},
            },
            "evaluation": {"score": 8.0, "passed": True},
            "selected_action": {
                "id": "plan_adaptive",
                "policy_context_keys": ["senior:system_design"],
            },
            "job_spec": {"level": "senior"},
        }
    )  # type: ignore[arg-type]

    assert out == {}
    assert updates == []


def test_skip_question_node_records_unscored_turn() -> None:
    from app.engine.workflow.nodes.skip_question import skip_question_node

    out = skip_question_node(
        {
            "turn_idx": 2,
            "formal_turn_idx": 1,
            "turn_budget_remaining": 5,
            "current_dimension": "system_design",
            "current_question": {
                "question": "How would you design a feed?",
                "dimension": "system_design",
            },
            "qa_history": [],
            "messages": [],
        }
    )

    assert out["turn_idx"] == 3
    assert out["formal_turn_idx"] == 2
    assert out["turn_budget_remaining"] == 4
    assert out["current_answer_intent"] == "skipped"
    assert out["current_question"] == {}
    assert out["qa_history"][0]["answer_intent"] == "skipped"
    assert out["qa_history"][0]["evaluation"]["score"] is None


def test_skip_question_node_preserves_depth_followup_metadata() -> None:
    from app.engine.workflow.nodes.skip_question import skip_question_node

    depth_followup = {
        "source_turn_idx": 3,
        "depth_reason": "depth_followup_recovery",
        "depth_slot_rank": 2,
        "depth_target_turns": 12,
    }

    out = skip_question_node(
        {
            "turn_idx": 11,
            "formal_turn_idx": 11,
            "turn_budget_remaining": 1,
            "current_dimension": "technical_depth",
            "current_question": {
                "question": "Continue on Redis failure recovery.",
                "dimension": "technical_depth",
                "phase": "depth_followup",
                "depth_followup": depth_followup,
                "selection_artifacts": {
                    "depth_followup": depth_followup,
                },
            },
            "dimension_status": {"technical_depth": "passed"},
            "qa_history": [],
            "messages": [],
        }
    )

    qa_turn = out["qa_history"][0]
    assert qa_turn["phase"] == "depth_followup"
    assert qa_turn["depth_followup"] == depth_followup
    assert qa_turn["selection_artifacts"]["depth_followup"] == depth_followup


def test_hint_from_contract_must_cover_is_directional() -> None:
    from app.services.session_manager import build_interview_hint

    result = build_interview_hint(
        {
            "question": "请设计一个订单系统。",
            "contract": {"must_cover": ["边界条件", "方案取舍", "验证方式"]},
        }
    )

    assert result["source"] == "contract"
    assert "边界条件" in result["hint"]
    assert "方案取舍" in result["hint"]
    assert "可以先" in result["hint"]


def test_hint_from_target_skills_or_resume_anchor_when_contract_missing() -> None:
    from app.services.session_manager import build_interview_hint

    skill_result = build_interview_hint(
        {
            "question": "请说明一次缓存优化。",
            "target_skills": ["Redis", "MySQL"],
        }
    )
    anchor_result = build_interview_hint(
        {
            "question": "请说明一个项目难点。",
            "resume_anchor": {"project_name": "支付迁移", "tech_stack": ["Kafka"]},
        }
    )

    assert skill_result["source"] == "target_skills"
    assert "Redis" in skill_result["hint"]
    assert anchor_result["source"] == "resume_anchor"
    assert "支付迁移" in anchor_result["hint"]


def test_hint_fallback_works_without_llm() -> None:
    from app.services.session_manager import build_interview_hint

    result = build_interview_hint({"question": "Q"})

    assert result["source"] == "fallback"
    assert result["hint"]


def test_hint_does_not_include_direct_answer_phrases() -> None:
    from app.services.session_manager import build_interview_hint

    forbidden = ["标准答案", "你可以直接说", "完整答案", "照抄"]
    result = build_interview_hint(
        {
            "question": "请设计一个 Feed 流。",
            "contract": {"must_cover": ["存储模型", "推拉模式", "降级策略"]},
            "target_skills": ["Redis"],
        }
    )

    assert not any(phrase in result["hint"] for phrase in forbidden)
