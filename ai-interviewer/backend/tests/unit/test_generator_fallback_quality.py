"""Generator fallback quality guards for the interview mainline."""
from __future__ import annotations

from app.engine.agents import generator


def test_generate_question_fallback_stays_resume_grounded_and_chinese(
    monkeypatch,
) -> None:
    monkeypatch.setattr(generator, "call_chat", lambda *_args, **_kwargs: "{}")

    question = generator.generate_question(
        dimension="system_design",
        action={"id": "plan_deep_probe"},
        job_spec={"title": "后端工程师", "level": "senior"},
        candidate={},
        recent_qa=[],
        retrieval_block="(no relevant knowledge retrieved)",
        resume_anchor={
            "project_name": "支付迁移",
            "tech_stack": ["Kafka", "Redis"],
            "question_anchors": ["一致性", "性能优化"],
        },
        self_intro_profile={"emphasized_skills": ["Kafka"]},
        refine_mode=True,
        contract_hints={"must_address": ["缺少容量估算"]},
        target_difficulty="hard",
        target_skills=["Kafka", "Redis"],
        probe_intent="architecture_challenge",
    )

    assert "支付迁移" in question["question"]
    assert "系统设计" in question["question"]
    assert "Kafka" in question["question"]
    assert "system design" not in question["question"]
    assert question["difficulty"] == "hard"
    assert question["proposed_contract"]["bar_level"] == "deep_probe"
    checks = question["proposed_contract"]["acceptance_checks"]
    assert len(checks) >= 3
    assert any("取舍" in check for check in checks)
    assert any("证据" in check or "指标" in check for check in checks)
    assert all("Answer " not in check for check in checks)
