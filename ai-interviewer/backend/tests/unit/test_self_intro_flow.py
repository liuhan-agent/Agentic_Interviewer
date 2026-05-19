"""Self-introduction opening phase tests."""
from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from app.engine.context import build_context_frame_for_generator
from app.engine.resume_plan import select_resume_anchor
from app.engine.workflow.routers import route_after_eval, route_after_wait
from app.services.session_manager import temporary_llm_override


def test_self_intro_question_payload_is_opening_turn() -> None:
    from app.engine.workflow.nodes.self_intro import self_intro_question_node

    out = self_intro_question_node({"session_id": "sess-intro"})  # type: ignore[arg-type]

    question = out["current_question"]
    assert question["question_type"] == "self_intro"
    assert question["dimension"] == "communication"
    assert "自我介绍" in question["question"]
    assert out["intro_completed"] is False


def test_route_after_wait_sends_self_intro_to_parser_not_evaluator() -> None:
    state = {
        "status": "running",
        "current_question": {"question_type": "self_intro"},
    }

    assert route_after_wait(state) == "self_intro_parse"  # type: ignore[arg-type]


def test_self_intro_parse_fallback_profile_does_not_advance_formal_turns(
    monkeypatch,
) -> None:
    from app.engine.workflow.nodes import self_intro as intro_mod

    monkeypatch.setattr(
        intro_mod,
        "parse_self_intro_profile",
        lambda **_kwargs: {
            "summary": "候选人强调 AI 健康评估系统和权限设计。",
            "emphasized_projects": ["AI 健康评估系统"],
            "emphasized_skills": ["权限设计"],
            "parse_status": "fallback",
        },
    )

    out = intro_mod.self_intro_parse_node(
        {
            "turn_idx": 0,
            "formal_turn_idx": 0,
            "current_answer": "我主要做过 AI 健康评估系统和权限设计。",
            "current_answer_raw": "",
            "current_question": {"question": "请先做个自我介绍"},
        }
    )

    assert out["intro_completed"] is True
    assert out["self_intro_answer"] == "我主要做过 AI 健康评估系统和权限设计。"
    assert out["self_intro_profile"]["emphasized_projects"] == ["AI 健康评估系统"]
    assert out["turn_idx"] == 1
    assert out["formal_turn_idx"] == 0
    assert "evaluation" not in out
    assert "scores_per_dim" not in out
    assert "qa_history" not in out


def test_parse_self_intro_profile_tolerates_missing_resume_projects(monkeypatch) -> None:
    from app.engine.agents import self_intro as parser

    monkeypatch.setattr(parser, "get_settings", lambda: SimpleNamespace(use_stub_llm=True))

    profile = parser.parse_self_intro_profile(
        answer="我主要做 Python 后端和 Kafka 消息系统。",
        candidate={"resume_parsed": {"skills": ["Python", "Kafka"], "projects": None}},
        job_spec={},
    )

    assert profile["parse_status"] == "heuristic"
    assert profile["emphasized_skills"] == ["Python", "Kafka"]


def test_self_intro_parser_uses_frontend_byok_even_when_server_stubbed() -> None:
    from app.engine.agents.self_intro import parse_self_intro_profile

    llm_reply = json.dumps(
        {
            "summary": "候选人强调智慧养老项目中的端到端 AI 评估流水线。",
            "emphasized_projects": ["智慧养老项目"],
            "emphasized_skills": ["LangChain4j", "Redis"],
            "preferred_focus": ["AI 健康评估流水线"],
            "clarification_targets": [],
            "communication_signal": {"structure": "clear", "notes": []},
        },
        ensure_ascii=False,
    )

    with (
        temporary_llm_override(
            {
                "provider": "qwen",
                "api_key": "sk-browser-key",
                "model": "qwen3.6-flash",
            }
        ),
        patch("app.engine.agents.self_intro.call_chat", return_value=llm_reply) as call,
    ):
        profile = parse_self_intro_profile(
            answer="我在智慧养老项目里做了端到端 AI 健康评估流水线。",
            candidate={
                "resume_parsed": {
                    "projects": [{"name": "智慧养老项目"}],
                    "focus_areas": [],
                    "skills": ["LangChain4j", "Redis"],
                }
            },
            job_spec={"title": "Java 后端工程师"},
        )

    assert call.called
    assert profile["parse_status"] == "llm"
    assert profile["emphasized_projects"] == ["智慧养老项目"]
    assert profile["emphasized_skills"] == ["LangChain4j", "Redis"]


def test_route_after_eval_uses_formal_turn_idx_for_max_turns() -> None:
    state = {
        "status": "running",
        "evaluation": {"passed": False},
        "turn_idx": 9,
        "formal_turn_idx": 2,
        "max_turns": 8,
        "turn_budget_remaining": 6,
        "dimensions": ["technical_depth"],
        "dimension_status": {"technical_depth": "active"},
    }

    assert route_after_eval(state) == "refine"  # type: ignore[arg-type]


def test_route_after_eval_does_not_refine_on_evaluator_fallback() -> None:
    state = {
        "status": "running",
        "evaluation": {
            "source": "fallback",
            "fallback_reason": "llm_failed",
            "passed": False,
            "recommended_next": "refine",
        },
        "turn_idx": 1,
        "formal_turn_idx": 1,
        "max_turns": 8,
        "turn_budget_remaining": 7,
        "dimensions": ["technical_depth", "system_design"],
        "dimension_status": {
            "technical_depth": "active",
            "system_design": "pending",
        },
    }

    assert route_after_eval(state) == "next_question"  # type: ignore[arg-type]


def test_generator_context_includes_self_intro_profile() -> None:
    profile = {
        "summary": "候选人强调 AI 健康评估系统。",
        "emphasized_projects": ["AI 健康评估系统"],
        "preferred_focus": ["系统架构"],
    }
    with (
        patch(
            "app.engine.context.builder.load_prompt",
            return_value="SYS_SKELETON",
        ),
        patch(
            "app.engine.context.builder.build_strategy_index",
            return_value="",
        ),
    ):
        frame = build_context_frame_for_generator(
            dimension="system_design",
            action={},
            job_spec={"title": "AI 全栈工程师", "level": "senior"},
            candidate={"resume_parsed": {"highlights": []}},
            recent_qa=[],
            retrieval_block="",
            strategy_block="",
            self_intro_profile=profile,
        )

    assert frame.payload["self_intro_profile"] == json.dumps(
        profile,
        ensure_ascii=False,
    )


def test_resume_anchor_prefers_self_intro_emphasized_project() -> None:
    candidate: dict[str, Any] = {
        "resume_parsed": {
            "projects": [
                {"id": "proj-1", "name": "支付系统", "tech_stack": ["Kafka"]},
                {
                    "id": "proj-2",
                    "name": "AI 健康评估系统",
                    "tech_stack": ["LLM", "MySQL"],
                },
            ],
            "focus_areas": [
                {
                    "id": "focus-1",
                    "label": "支付系统一致性",
                    "project_id": "proj-1",
                    "dimensions": ["system_design"],
                    "priority": 1,
                },
                {
                    "id": "focus-2",
                    "label": "AI 健康评估系统架构",
                    "project_id": "proj-2",
                    "dimensions": ["system_design"],
                    "priority": 2,
                },
            ],
        }
    }

    anchor = select_resume_anchor(
        candidate=candidate,
        job_spec={},
        dimension="system_design",
        qa_history=[],
        turn_idx=0,
        self_intro_profile={
            "emphasized_projects": ["AI 健康评估系统"],
            "emphasized_skills": [],
        },
    )

    assert anchor is not None
    assert anchor["project_id"] == "proj-2"
