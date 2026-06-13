from __future__ import annotations

import pytest

from app.engine.resume_plan import (
    has_available_resume_anchor_slot,
    select_resume_anchor,
    select_resume_anchor_with_schedule,
)
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
    assert anchor["anchor_key"] == "focus-coupon-design"
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


def test_rule_anchor_skips_used_anchor_key_before_legacy_ids(
    parsed_resume_fixture: dict,
) -> None:
    parsed_resume_fixture["focus_areas"][0]["anchor_key"] = "focus-coupon-design"
    parsed_resume_fixture["focus_areas"][1]["anchor_key"] = "focus-observability"
    parsed_resume_fixture["focus_areas"][1]["dimensions"] = ["system_design"]

    anchor = select_resume_anchor(
        candidate={"resume_parsed": parsed_resume_fixture},
        job_spec={},
        dimension="system_design",
        qa_history=[{"resume_anchor": {"anchor_key": "focus-coupon-design"}}],
        turn_idx=0,
    )

    assert anchor is not None
    assert anchor["anchor_key"] == "focus-observability"
    assert anchor["focus_id"] == "focus_observability"


def test_anchor_scheduler_short_mode_does_not_reuse_anchor(
    parsed_resume_fixture: dict,
) -> None:
    parsed_resume_fixture["focus_areas"] = [parsed_resume_fixture["focus_areas"][0]]

    selection = select_resume_anchor_with_schedule(
        candidate={"resume_parsed": parsed_resume_fixture},
        job_spec={"required_skills": ["Go"]},
        dimension="system_design",
        qa_history=[{"resume_anchor": {"anchor_key": "focus-coupon-design"}}],
        turn_idx=1,
        interview_depth="short",
    )

    assert selection["resume_anchor"] is None
    assert not has_available_resume_anchor_slot(
        candidate={"resume_parsed": parsed_resume_fixture},
        job_spec={"required_skills": ["Redis"]},
        qa_history=[{"resume_anchor": {"anchor_key": "focus-coupon-design"}}],
        interview_depth="short",
    )


def test_anchor_scheduler_standard_reuses_high_value_anchor_once(
    parsed_resume_fixture: dict,
) -> None:
    parsed_resume_fixture["focus_areas"] = [parsed_resume_fixture["focus_areas"][0]]

    selection = select_resume_anchor_with_schedule(
        candidate={"resume_parsed": parsed_resume_fixture},
        job_spec={"required_skills": ["Go"]},
        dimension="system_design",
        qa_history=[{"resume_anchor": {"anchor_key": "focus-coupon-design"}}],
        turn_idx=1,
        interview_depth="standard",
    )

    assert selection["resume_anchor"]["anchor_key"] == "focus-coupon-design"
    assert selection["scheduler"]["anchor_attempt"] == 2
    assert selection["scheduler"]["max_anchor_attempts"] == 2
    assert selection["scheduler"]["expansion_reason"] == "high_value_second_pass"


def test_anchor_scheduler_does_not_reuse_low_value_anchor(
    parsed_resume_fixture: dict,
) -> None:
    parsed_resume_fixture["focus_areas"] = [
        {
            **parsed_resume_fixture["focus_areas"][0],
            "priority": 9,
            "skills": ["LegacyTool"],
        }
    ]

    selection = select_resume_anchor_with_schedule(
        candidate={"resume_parsed": parsed_resume_fixture},
        job_spec={"required_skills": ["Go"]},
        dimension="system_design",
        qa_history=[{"resume_anchor": {"anchor_key": "focus-coupon-design"}}],
        turn_idx=1,
        interview_depth="standard",
    )

    assert selection["resume_anchor"] is None


def test_anchor_scheduler_prefers_unasked_anchor_before_second_pass(
    parsed_resume_fixture: dict,
) -> None:
    parsed_resume_fixture["focus_areas"][1]["anchor_key"] = "focus-observability"
    parsed_resume_fixture["focus_areas"][1]["dimensions"] = ["system_design"]

    selection = select_resume_anchor_with_schedule(
        candidate={"resume_parsed": parsed_resume_fixture},
        job_spec={"required_skills": ["Redis"]},
        dimension="system_design",
        qa_history=[{"resume_anchor": {"anchor_key": "focus-coupon-design"}}],
        turn_idx=1,
        interview_depth="deep",
    )

    assert selection["resume_anchor"]["anchor_key"] == "focus-observability"
    assert selection["scheduler"]["anchor_attempt"] == 1
    assert selection["scheduler"]["expansion_reason"] == "first_pass_dimension_match"


def test_anchor_scheduler_namespaces_numeric_focus_and_project_ids() -> None:
    parsed_resume = {
        "projects": [
            {
                "id": "2",
                "name": "Smart Learning Platform",
                "tech_stack": ["Redis", "RabbitMQ"],
            }
        ],
        "focus_areas": [
            {
                "id": "1",
                "anchor_key": "focus-ai-routing",
                "project_id": "2",
                "label": "AI agent routing",
                "priority": 1,
                "skills": ["LangChain4j"],
                "dimensions": ["technical_depth"],
            },
            {
                "id": "2",
                "anchor_key": "focus-coupon-consistency",
                "project_id": "2",
                "label": "Coupon consistency",
                "priority": 2,
                "skills": ["Redis", "RabbitMQ"],
                "dimensions": ["technical_depth"],
            },
        ],
    }

    selection = select_resume_anchor_with_schedule(
        candidate={"resume_parsed": parsed_resume},
        job_spec={"required_skills": ["Redis"]},
        dimension="technical_depth",
        qa_history=[
            {
                "resume_anchor": {
                    "anchor_key": "focus-ai-routing",
                    "focus_id": "1",
                    "project_id": "2",
                }
            },
            {
                "resume_anchor": {
                    "anchor_key": "focus-ai-routing",
                    "focus_id": "1",
                    "project_id": "2",
                }
            },
        ],
        turn_idx=2,
        interview_depth="standard",
    )

    assert selection["resume_anchor"]["anchor_key"] == "focus-coupon-consistency"
    assert selection["resume_anchor"]["focus_id"] == "2"
    assert selection["scheduler"]["anchor_attempt"] == 1
    assert selection["scheduler"]["expansion_reason"] == "first_pass_dimension_match"


def test_plan_templates_step_kinds_baseline() -> None:
    assert [s["kind"] for s in PLAN_TEMPLATES["simple"]["steps"]] == [
        "select_structured_question",
        "retrieve_rag",
        "retrieve_skills",
        "retrieve_candidate_anchors",
        "draft_question",
        "guardrail_check",
    ]
    assert [s["kind"] for s in PLAN_TEMPLATES["quick_review"]["steps"]] == [
        "select_structured_question",
        "retrieve_rag",
        "retrieve_skills",
        "retrieve_candidate_anchors",
        "draft_question",
        "guardrail_check",
    ]
    assert [s["kind"] for s in PLAN_TEMPLATES["adaptive"]["steps"]] == [
        "select_structured_question",
        "retrieve_rag",
        "retrieve_strategy",
        "retrieve_skills",
        "retrieve_candidate_anchors",
        "draft_question",
        "negotiate_contract",
        "guardrail_check",
    ]
    assert [s["kind"] for s in PLAN_TEMPLATES["deep_probe"]["steps"]] == [
        "select_structured_question",
        "retrieve_rag",
        "retrieve_strategy",
        "retrieve_skills",
        "retrieve_candidate_anchors",
        "draft_question",
        "negotiate_contract",
        "challenge_with_reference",
        "guardrail_check",
    ]
