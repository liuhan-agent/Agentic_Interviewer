from __future__ import annotations

from app.engine.workflow.replay_basis import (
    build_replay_context_basis,
    build_replay_question_basis,
    sanitize_replay_question_basis,
)


def test_question_basis_uses_resume_anchor_skills_and_dimension() -> None:
    basis = build_replay_question_basis(
        dimension="technical_depth",
        resume_anchor={
            "project_name": "支付迁移项目",
            "label": "支付迁移中的缓存治理",
            "tech_stack": ["Redis", "Kafka"],
            "skills": ["Redis"],
            "knowledge_source": "local",
        },
        target_skills=["Redis", "Kafka"],
        skill_focus={"focus_source": "resume_anchor"},
        job_spec={"required_skills": ["Redis", "Kafka"]},
        refine_mode=False,
        contract_hints={},
    )

    assert basis is not None
    assert basis["title"] == "为什么问这一题"
    assert "支付迁移项目" in basis["summary"]
    assert "来自简历" in basis["chips"]
    assert "评分维度" in basis["chips"]
    assert "技术深度" in basis["chips"]
    assert "Redis" in basis["chips"]
    assert "Kafka" in basis["chips"]


def test_question_basis_uses_self_intro_source() -> None:
    basis = build_replay_question_basis(
        dimension="project_experience",
        resume_anchor={
            "label": "AI 健康评估系统",
            "project_name": "AI 健康评估系统",
            "skills": ["LangChain4j"],
            "knowledge_source": "self_intro",
        },
        target_skills=["LangChain4j"],
        skill_focus={"focus_source": "self_intro"},
        job_spec={},
        refine_mode=False,
        contract_hints={},
    )

    assert basis is not None
    assert "来自自我介绍" in basis["chips"]
    assert "AI 健康评估系统" in basis["summary"]
    assert "LangChain4j" in basis["chips"]


def test_question_basis_marks_job_spec_and_followup_sources() -> None:
    basis = build_replay_question_basis(
        dimension="system_design",
        resume_anchor={},
        target_skills=["Redis"],
        skill_focus={"focus_source": "jd_uncovered"},
        job_spec={"required_skills": ["Redis"]},
        refine_mode=True,
        contract_hints={"failure_reason": "缺少容量估算"},
    )

    assert basis is not None
    assert "来自岗位要求" in basis["chips"]
    assert "上一轮追问" in basis["chips"]
    assert "系统设计" in basis["chips"]


def test_context_basis_aggregates_self_intro_resume_and_job_spec() -> None:
    basis = build_replay_context_basis(
        report={
            "self_intro": {
                "profile": {
                    "summary": "候选人强调支付迁移项目和缓存治理，可全职实习6个月以上，面试通过后3天内到岗。",
                    "emphasized_projects": ["支付迁移项目"],
                    "emphasized_skills": ["Redis"],
                    "preferred_focus": ["容量估算"],
                }
            }
        },
        setup_snapshot={
            "candidate": {
                "resume_parsed": {
                    "projects": [{"name": "支付迁移项目"}],
                    "focus_areas": [{"label": "缓存治理"}],
                    "skills": ["Redis", "Kafka"],
                }
            },
            "job_spec": {
                "title": "Java 后端",
                "level": "senior",
                "required_skills": ["Redis", "Kafka"],
                "rubric_dimensions": ["technical_depth", "system_design"],
            },
        },
    )

    assert basis is not None
    assert basis["title"] == "开场与简历线索"
    assert basis["summary"] == (
        "本场面试会结合开场自我介绍、简历项目和岗位要求选择问题；"
        "评分维度主要来自岗位要求。"
    )
    assert "全职实习" not in basis["summary"]
    assert "3天内到岗" not in basis["summary"]
    assert "来自自我介绍" not in basis["chips"]
    assert "来自简历" not in basis["chips"]
    assert "来自岗位要求" not in basis["chips"]
    assert "1 个项目线索" in basis["chips"]
    assert "2 个技能线索" in basis["chips"]
    assert "2 个评分维度" in basis["chips"]
    assert "支付迁移项目" not in basis["chips"]
    assert "Redis" not in basis["chips"]
    assert basis["self_intro"]["emphasized_projects"] == ["支付迁移项目"]
    assert basis["self_intro"]["summary"] is None
    assert basis["resume"]["skills"] == ["Redis", "Kafka"]
    assert basis["job_spec"]["dimensions"] == ["technical_depth", "system_design"]
    assert basis["job_spec"]["dimension_source_label"] == "岗位要求"


def test_context_basis_falls_back_to_default_score_dimensions() -> None:
    basis = build_replay_context_basis(
        report={
            "dimension_summaries": {
                "technical_depth": {},
                "project_experience": {},
            }
        },
        setup_snapshot={
            "candidate": {"resume_parsed": {"skills": ["Java"]}},
            "job_spec": {
                "title": "Java 后端",
                "level": "junior",
                "required_skills": ["Java"],
                "rubric_dimensions": [],
            },
        },
    )

    assert basis is not None
    assert basis["summary"] == (
        "本场面试会结合简历项目和岗位要求选择问题；"
        "评分维度主要来自默认评分标准。"
    )
    assert "默认评分标准" not in basis["chips"]
    assert "2 个评分维度" in basis["chips"]
    assert basis["job_spec"]["dimensions"] == [
        "technical_depth",
        "project_experience",
    ]
    assert basis["job_spec"]["dimension_source_label"] == "默认评分标准"


def test_sanitize_question_basis_rejects_internal_or_malformed_payloads() -> None:
    assert sanitize_replay_question_basis({"title": "为什么问这一题"}) is None
    assert (
        sanitize_replay_question_basis(
            {
                "title": "为什么问这一题",
                "summary": "说明",
                "chips": ["来自简历"],
                "resume_anchor": {"project_name": "raw"},
            }
        )
        is None
    )
    assert (
        sanitize_replay_question_basis(
            {
                "title": "为什么问这一题",
                "summary": "说明",
                "chips": "来自简历",
            }
        )
        is None
    )
