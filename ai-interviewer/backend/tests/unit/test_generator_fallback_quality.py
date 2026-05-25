"""Generator fallback quality guards for the interview mainline."""
from __future__ import annotations

from app.engine.agents import generator


def test_generate_question_uses_seed_backed_fallback_when_model_omits_question(
    monkeypatch,
) -> None:
    monkeypatch.setattr(generator, "call_chat", lambda *_args, **_kwargs: "{}")

    question = generator.generate_question(
        dimension="technical_depth",
        action={"id": "plan_adaptive"},
        job_spec={"title": "Java 后端工程师", "level": "junior"},
        candidate={},
        recent_qa=[],
        retrieval_block="",
        question_seed_block="\n".join(
            [
                "Seed: Java 事务一致性与补偿边界",
                "Dimension: technical_depth",
                "Intent: deep_probe",
                "Difficulty: deep_probe",
                "Scenario: 主交易成功后需要发送积分、通知和账单事件，多个副作用可能部分失败。",
                "Question stem: 如果主事务已成功但多个异步副作用可能失败，你会如何设计 outbox、重放和补偿流程？",
                "Prompt template: 生成一道 Java 后端事务一致性深挖题，要求候选人说明 outbox 写入、消息投递、幂等消费、监控告警和人工兜底。",
            ]
        ),
        resume_anchor={
            "project_name": "康乐智慧养老系统",
            "tech_stack": ["springboot", "springsecurity", "mybatis-plus"],
        },
        self_intro_profile={},
        target_difficulty="hard",
        target_skills=["springsecurity", "mybatis-plus"],
        probe_intent="performance_probe",
    )

    assert "康乐智慧养老系统" in question["question"]
    assert "outbox" in question["question"].lower()
    assert "异步副作用" in question["question"]
    assert "重放" in question["question"]
    assert "补偿" in question["question"]
    assert "约束、备选方案和最终取舍" not in question["question"]
    assert question["seed_backed_fallback"] is True


def test_generate_question_seed_backed_fallback_keeps_system_design_seed_terms(
    monkeypatch,
) -> None:
    monkeypatch.setattr(generator, "call_chat", lambda *_args, **_kwargs: "{}")

    question = generator.generate_question(
        dimension="system_design",
        action={"id": "plan_hint"},
        job_spec={"title": "Java 后端工程师", "level": "junior"},
        candidate={},
        recent_qa=[],
        retrieval_block="",
        question_seed_block="\n".join(
            [
                "Seed: 容量规划与削峰",
                "Dimension: system_design",
                "Intent: deep_probe",
                "Difficulty: deep_probe",
                "Scenario: 活动峰值超过预估三倍，入口限流后仍有大量请求堆积在队列和库存写入链路。",
                "Question stem: 当活动流量超过预估且队列开始堆积时，你会如何设计背压、削峰、扩容和用户体验降级？",
                "Prompt template: 围绕候选人的高并发或队列经验，生成一道容量规划深挖题，要求量化瓶颈、背压策略和降级边界。",
            ]
        ),
        resume_anchor={
            "project_name": "康乐智慧养老系统",
            "tech_stack": ["springboot", "springsecurity"],
        },
        self_intro_profile={},
        target_difficulty="hard",
        target_skills=["spring-security"],
        probe_intent=None,
    )

    assert "康乐智慧养老系统" in question["question"]
    assert "队列" in question["question"]
    assert "背压" in question["question"]
    assert "削峰" in question["question"]
    assert "扩容" in question["question"]
    assert "降级" in question["question"]
    assert question["question"].count("springsecurity") == 0


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
