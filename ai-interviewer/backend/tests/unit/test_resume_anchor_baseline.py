from __future__ import annotations

import pytest

from app.engine.resume_plan import select_resume_anchor
from app.engine.workflow.plans.ask_plans import PLAN_TEMPLATES


@pytest.fixture
def parsed_resume_fixture() -> dict:
    return {
        "projects": [
            {
                "id": "proj_coupon",
                "name": "Smart Learning Coupon Guard",
                "role": "Backend owner",
                "tech_stack": ["Redis", "Lua", "Spring Boot"],
                "question_anchors": ["inventory consistency", "high concurrency"],
                "achievements": ["Protected coupon deduction at peak traffic"],
            },
            {
                "id": "proj_observability",
                "name": "Realtime Observability Console",
                "role": "Platform engineer",
                "tech_stack": ["Kafka", "Flink", "ClickHouse"],
            },
        ],
        "focus_areas": [
            {
                "id": "focus_coupon_design",
                "project_id": "proj_coupon",
                "label": "Coupon deduction consistency",
                "priority": 1,
                "skills": ["Redis", "Lua"],
                "dimensions": ["system_design", "technical_depth"],
            },
            {
                "id": "focus_observability",
                "project_id": "proj_observability",
                "label": "Metric pipeline troubleshooting",
                "priority": 2,
                "skills": ["Kafka", "Flink"],
                "dimensions": ["debugging", "data_analysis"],
            },
        ],
    }


def test_rule_anchor_selects_dimension_match_when_unused(
    parsed_resume_fixture: dict,
) -> None:
    anchor = select_resume_anchor(
        candidate={"resume_parsed": parsed_resume_fixture},
        job_spec={},
        dimension="system_design",
        qa_history=[],
        turn_idx=0,
    )

    assert anchor is not None
    assert anchor["focus_id"] == "focus_coupon_design"
    assert "system_design" in anchor["dimensions"]
    assert anchor["project_name"] == "Smart Learning Coupon Guard"
    assert anchor["knowledge_source"] == "local"


def test_rule_anchor_skips_used_focus_and_rotates_to_available_focus(
    parsed_resume_fixture: dict,
) -> None:
    anchor = select_resume_anchor(
        candidate={"resume_parsed": parsed_resume_fixture},
        job_spec={},
        dimension="system_design",
        qa_history=[{"resume_anchor": {"focus_id": "focus_coupon_design"}}],
        turn_idx=0,
    )

    assert anchor is not None
    assert anchor["focus_id"] == "focus_observability"
    assert anchor["project_name"] == "Realtime Observability Console"


def test_rule_anchor_prefers_self_intro_matching_focus(
    parsed_resume_fixture: dict,
) -> None:
    anchor = select_resume_anchor(
        candidate={"resume_parsed": parsed_resume_fixture},
        job_spec={},
        dimension="system_design",
        qa_history=[],
        turn_idx=0,
        self_intro_profile={
            "emphasized_projects": ["Realtime Observability Console"],
            "emphasized_skills": ["Flink"],
            "preferred_focus": ["metric pipeline"],
        },
    )

    assert anchor is not None
    assert anchor["focus_id"] == "focus_observability"
    assert anchor["project_name"] == "Realtime Observability Console"


def test_plan_templates_step_kinds_baseline() -> None:
    assert [s["kind"] for s in PLAN_TEMPLATES["simple"]["steps"]] == [
        "retrieve_rag",
        "retrieve_candidate_anchors",
        "draft_question",
        "guardrail_check",
    ]
    assert [s["kind"] for s in PLAN_TEMPLATES["quick_review"]["steps"]] == [
        "retrieve_rag",
        "retrieve_candidate_anchors",
        "draft_question",
        "guardrail_check",
    ]
    assert [s["kind"] for s in PLAN_TEMPLATES["adaptive"]["steps"]] == [
        "retrieve_rag",
        "retrieve_strategy",
        "retrieve_candidate_anchors",
        "draft_question",
        "negotiate_contract",
        "guardrail_check",
    ]
    assert [s["kind"] for s in PLAN_TEMPLATES["deep_probe"]["steps"]] == [
        "retrieve_rag",
        "retrieve_strategy",
        "retrieve_candidate_anchors",
        "draft_question",
        "negotiate_contract",
        "challenge_with_reference",
        "guardrail_check",
    ]
