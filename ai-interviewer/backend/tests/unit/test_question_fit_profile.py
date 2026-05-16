from __future__ import annotations

from app.services.question_fit_profile import (
    build_question_fit_profile,
    format_candidate_anchor_block,
)
from app.services.question_selector import QuestionCandidate


def _candidate() -> QuestionCandidate:
    return QuestionCandidate(
        seed_id="system_design.cache_consistency",
        variant_id="system_design.cache_consistency.flash_sale_inventory",
        seed_version=1,
        variant_version=1,
        rank=1,
        match_score=42.0,
        match_reasons=["priority:30"],
        injected=True,
        title="Cache consistency",
        dimension="system_design",
        seed_priority=20,
        variant_priority=10,
        skill_tags=["redis", "cache"],
        rubric={"must_cover": ["consistency"]},
        intent="opening",
        difficulty="standard",
        scenario_brief="Flash-sale inventory cache consistency.",
        question_stem="Design inventory cache consistency.",
        prompt_template="Generate a cache consistency question.",
        scenario_skill_tags=["redis", "inventory_service"],
        resume_anchor_hints=["redis", "inventory_service"],
        failure_categories=["missing_metrics"],
        rubric_additions=["Mention consistency window"],
        expected_signals=["Distinguishes strong and eventual consistency"],
        anti_patterns=["Only says add locks"],
        good_answer_hints=["Define consistency target first"],
        direction_tags=["internet_tech"],
        role_tags=["java_backend"],
    )


def test_fit_profile_extracts_resume_jd_intro_and_contract_signals() -> None:
    profile = build_question_fit_profile(
        candidate={
            "resume_parsed": {
                "projects": [
                    {
                        "name": "Flash Sale Inventory",
                        "summary": "Inventory service with Redis cache.",
                        "tech_stack": ["Redis", "Kafka"],
                        "highlights": ["cut oversell by 80%"],
                    }
                ],
                "skills": ["Java", "Redis"],
            }
        },
        self_intro_profile={
            "emphasized_skills": ["Kafka", "DDD"],
            "summary": "Focused on inventory reliability.",
        },
        job_spec={"required_skills": ["Redis", "Microservices", "Observability"]},
        target_skills=["Cache", "Redis"],
        resume_anchor={
            "project_name": "Flash Sale Inventory",
            "tech_stack": ["Redis"],
        },
        pending_contract_hints={
            "failure_categories": ["missing_metrics", "missing_tradeoff"],
        },
        dimension="system_design",
        probe_intent="architecture_challenge",
    )

    assert profile.anchor_confidence == "high"
    assert profile.generic_risk == "low"
    assert profile.candidate_projects[0]["name"] == "Flash Sale Inventory"
    assert "redis" in profile.candidate_skills
    assert "microservices" in profile.job_core_skills
    assert profile.failure_categories == ["missing_metrics", "missing_tradeoff"]
    assert profile.turn_intent == "architecture_challenge"
    assert profile.direction_tags == ["internet_tech"]
    assert profile.role_tags == ["java_backend"]


def test_fit_profile_resolves_frontend_and_sre_role_tags() -> None:
    frontend = build_question_fit_profile(
        candidate={"resume_parsed": {}},
        self_intro_profile={},
        job_spec={
            "interview_direction": "frontend",
            "title": "高级前端开发工程师",
            "required_skills": ["React"],
        },
        target_skills=[],
        resume_anchor=None,
        pending_contract_hints=None,
        dimension="technical_depth",
        probe_intent="opening",
    )
    sre = build_question_fit_profile(
        candidate={"resume_parsed": {}},
        self_intro_profile={},
        job_spec={
            "interview_direction": "sre",
            "title": "运维 / SRE 工程师",
            "required_skills": ["Kubernetes"],
        },
        target_skills=[],
        resume_anchor=None,
        pending_contract_hints=None,
        dimension="problem_solving",
        probe_intent="opening",
    )

    assert frontend.direction_tags == ["internet_tech"]
    assert frontend.role_tags == ["frontend_web"]
    assert sre.direction_tags == ["internet_tech"]
    assert sre.role_tags == ["sre"]


def test_fit_profile_resolves_batch2_role_tags_from_direction_and_title() -> None:
    cases = [
        (
            {
                "interview_direction": "ai_agent",
                "title": "AI Agent 开发工程师",
                "required_skills": ["RAG", "tool calling", "LangGraph"],
            },
            "ai_agent",
        ),
        (
            {
                "interview_direction": "ai_fullstack",
                "title": "AI 全栈开发工程师",
                "required_skills": ["LLM", "React", "Python"],
            },
            "ai_fullstack",
        ),
        (
            {
                "title": "移动端开发工程师",
                "required_skills": ["Android", "Flutter", "React Native"],
            },
            "mobile",
        ),
        (
            {
                "title": "AI 算法工程师",
                "required_skills": ["PyTorch", "TensorFlow", "模型评估"],
            },
            "ai_algorithm",
        ),
        (
            {
                "title": "架构师 / 技术专家",
                "required_skills": ["复杂系统", "技术治理", "Staff"],
            },
            "architect",
        ),
    ]

    for job_spec, expected_role in cases:
        profile = build_question_fit_profile(
            candidate={"resume_parsed": {}},
            self_intro_profile={},
            job_spec=job_spec,
            target_skills=[],
            resume_anchor=None,
            pending_contract_hints=None,
            dimension="technical_depth",
            probe_intent="opening",
        )

        assert profile.direction_tags == ["internet_tech"]
        assert profile.role_tags == [expected_role]


def test_fit_profile_runtime_role_tags_take_precedence_for_batch2() -> None:
    profile = build_question_fit_profile(
        candidate={"resume_parsed": {}},
        self_intro_profile={},
        job_spec={
            "interview_direction": "java_backend",
            "required_skills": ["Java", "Redis"],
        },
        target_skills=[],
        resume_anchor=None,
        pending_contract_hints=None,
        dimension="system_design",
        probe_intent="opening",
        runtime_config={
            "question_direction_tags": ["internet_tech"],
            "question_role_tags": ["ai_agent"],
        },
    )

    assert profile.direction_tags == ["internet_tech"]
    assert profile.role_tags == ["ai_agent"]


def test_fit_profile_resolves_business1_role_tags_from_direction_and_title() -> None:
    cases = [
        (
            {
                "interview_direction": "product_manager",
                "title": "产品经理",
                "required_skills": ["用户洞察", "PRD", "指标"],
            },
            "product_manager",
        ),
        (
            {
                "title": "用户增长运营",
                "required_skills": ["活动策划", "留存", "转化复盘"],
            },
            "operations",
        ),
        (
            {
                "title": "销售 / 商务经理",
                "required_skills": ["客户开发", "合同谈判", "CRM"],
            },
            "sales_business",
        ),
        (
            {
                "title": "市场品牌经理",
                "required_skills": ["品牌定位", "渠道投放", "Campaign"],
            },
            "marketing_brand",
        ),
    ]

    for job_spec, expected_role in cases:
        profile = build_question_fit_profile(
            candidate={"resume_parsed": {}},
            self_intro_profile={},
            job_spec=job_spec,
            target_skills=[],
            resume_anchor=None,
            pending_contract_hints=None,
            dimension="user_insight",
            probe_intent="opening",
        )

        assert profile.direction_tags == ["business"]
        assert profile.role_tags == [expected_role]


def test_fit_profile_runtime_business_tags_take_precedence() -> None:
    profile = build_question_fit_profile(
        candidate={"resume_parsed": {}},
        self_intro_profile={},
        job_spec={
            "interview_direction": "java_backend",
            "required_skills": ["Java", "Redis"],
        },
        target_skills=[],
        resume_anchor=None,
        pending_contract_hints=None,
        dimension="customer_discovery",
        probe_intent="opening",
        runtime_config={
            "question_direction_tags": ["business"],
            "question_role_tags": ["sales_business"],
        },
    )

    assert profile.direction_tags == ["business"]
    assert profile.role_tags == ["sales_business"]


def test_fit_profile_marks_empty_resume_as_generic_risk() -> None:
    profile = build_question_fit_profile(
        candidate={"resume_parsed": {}},
        self_intro_profile={},
        job_spec={},
        target_skills=[],
        resume_anchor=None,
        pending_contract_hints=None,
        dimension="backend_systems",
        probe_intent=None,
    )

    assert profile.anchor_confidence == "low"
    assert profile.generic_risk == "high"
    assert profile.candidate_projects == []
    assert profile.candidate_skills == []
    assert profile.job_core_skills == []


def test_candidate_anchor_block_uses_rule_profile_and_rule_top1() -> None:
    profile = build_question_fit_profile(
        candidate={
            "resume_parsed": {
                "projects": [
                    {
                        "name": "Flash Sale Inventory",
                        "tech_stack": ["Redis", "Kafka"],
                        "summary": "Handled oversell prevention.",
                    }
                ]
            }
        },
        self_intro_profile={},
        job_spec={"required_skills": ["Redis"]},
        target_skills=["Redis"],
        resume_anchor={"project_name": "Flash Sale Inventory", "tech_stack": ["Redis"]},
        pending_contract_hints=None,
        dimension="system_design",
        probe_intent="opening",
    )

    block = format_candidate_anchor_block(profile, _candidate())

    assert "Flash Sale Inventory" in block
    assert "redis" in block
    assert "system_design.cache_consistency" not in block
    assert "expected_signals" not in block
