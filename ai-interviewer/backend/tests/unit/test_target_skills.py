"""Tests for per-turn target skill selection and question focusing."""
from __future__ import annotations

from typing import Any

from app.engine.rag import retriever as retriever_mod
from app.engine.workflow.nodes import ask_question as ask_mod
from app.engine.workflow.skill_focus import select_target_skills


def test_select_target_skills_prefers_jd_resume_overlap_and_action_limit() -> None:
    focus = select_target_skills(
        job_spec={"required_skills": ["java", "redis", "kafka", "kubernetes"]},
        resume_anchor={"skills": ["Redis", "RocketMQ"], "tech_stack": ["MySQL", "Kafka"]},
        self_intro_profile={"emphasized_skills": ["kafka", "mysql"]},
        qa_history=[],
        current_dimension="system_design",
        selected_action={"plan_template": "deep_probe", "id": "plan_deep_probe"},
    )

    assert focus["target_skills"] == ["redis", "kafka", "mysql"]
    assert focus["focus_source"] == "jd_resume_overlap"


def test_select_target_skills_avoids_already_covered_jd_skills() -> None:
    focus = select_target_skills(
        job_spec={"required_skills": ["redis", "kafka", "mysql"]},
        resume_anchor={"skills": []},
        self_intro_profile={},
        qa_history=[
            {"target_skills": ["redis"]},
            {"current_question": {"target_skills": ["kafka"]}},
        ],
        current_dimension="technical_depth",
        selected_action={"plan_template": "simple", "id": "plan_simple"},
    )

    assert focus["target_skills"] == ["mysql"]
    assert focus["focus_source"] == "jd_uncovered"


def test_select_target_skills_normalizes_security_aliases() -> None:
    focus = select_target_skills(
        job_spec={"required_skills": ["Spring Security", "springboot"]},
        resume_anchor={
            "skills": ["spring-security"],
            "tech_stack": ["springsecurity", "SpringBoot"],
        },
        self_intro_profile={},
        qa_history=[],
        current_dimension="system_design",
        selected_action={"id": "plan_adaptive", "plan_template": "adaptive"},
    )

    assert focus["target_skills"] == ["spring-security", "springboot"]
    assert focus["focus_source"] == "jd_resume_overlap"


def test_retrieve_for_question_uses_target_skills_instead_of_all_required_skills(monkeypatch):
    captured: dict[str, Any] = {}

    class Store:
        def similarity_search(self, query: str, k: int):
            captured["query"] = query
            captured["k"] = k
            return []

    monkeypatch.setattr(retriever_mod, "get_vectorstore", lambda: Store())

    retriever_mod.retrieve_for_question(
        job_spec={
            "title": "Java Backend Engineer",
            "required_skills": ["redis", "kafka", "kubernetes"],
        },
        dimension="system_design",
        target_skills=["redis"],
        resume_anchor={"project_name": "Order System", "tech_stack": ["Redis"]},
    )

    query = captured["query"]
    assert "redis" in query.lower()
    assert "kubernetes" not in query.lower()
    assert "Order System" in query


def test_ask_question_persists_target_skills_to_current_question(monkeypatch):
    captured: dict[str, Any] = {}

    def fake_retrieve(**kwargs):
        captured["retrieve_target_skills"] = kwargs.get("target_skills")

        class _Ctx:
            as_prompt_block = "(stub retrieval)"

        return _Ctx()

    def fake_retrieve_strategies(**_kwargs):
        return []

    def fake_format_strategies(_entries):
        return "(no relevant strategy memories)"

    def fake_generate_question(**kwargs):
        captured["generate_target_skills"] = kwargs.get("target_skills")
        return {
            "question": "围绕订单系统讲 Redis 和 Kafka 的一致性设计。",
            "dimension": kwargs["dimension"],
            "rubric_points": ["trade-offs"],
            "proposed_contract": {
                "must_cover": ["trade-offs"],
                "acceptance_checks": ["Explains at least one trade-off."],
                "minimum_bar": "One concrete mechanism.",
                "bar_level": "standard",
            },
        }

    def fake_negotiate(**kwargs):
        return {**kwargs["proposed_contract"], "signed_by": ["generator", "evaluator"]}

    monkeypatch.setattr(ask_mod, "retrieve_for_question", fake_retrieve)
    monkeypatch.setattr(ask_mod, "retrieve_strategies", fake_retrieve_strategies)
    monkeypatch.setattr(ask_mod, "format_strategies_for_prompt", fake_format_strategies)
    monkeypatch.setattr(ask_mod, "generate_question", fake_generate_question)
    monkeypatch.setattr(ask_mod, "negotiate_contract_via_evaluator", fake_negotiate)

    state = {
        "session_id": "sess-focus",
        "trace_id": "trace-focus",
        "job_spec": {
            "title": "Java Backend Engineer",
            "level": "senior",
            "required_skills": ["redis", "kafka", "kubernetes"],
        },
        "candidate": {
            "resume_parsed": {
                "projects": [
                    {
                        "id": "proj-1",
                        "name": "Order System",
                        "tech_stack": ["Redis", "Kafka"],
                    }
                ],
                "focus_areas": [
                    {
                        "id": "focus-1",
                        "project_id": "proj-1",
                        "dimensions": ["system_design"],
                        "skills": ["Redis", "Kafka"],
                        "priority": 1,
                    }
                ],
            }
        },
        "dimensions": ["system_design"],
        "dimension_status": {"system_design": "active"},
        "current_dimension": "system_design",
        "turn_idx": 0,
        "qa_history": [],
        "runtime_config": {},
        "refine_mode": False,
        "current_ask_plan": None,
        "current_contract": None,
        "pending_plan_template": None,
        "pending_contract_hints": None,
        "selected_action": {"id": "plan_deep_probe", "plan_template": "deep_probe"},
    }

    out = ask_mod.ask_question_node(state)  # type: ignore[arg-type]

    assert captured["retrieve_target_skills"] == ["redis", "kafka"]
    assert captured["generate_target_skills"] == ["redis", "kafka"]
    assert out["current_question"]["target_skills"] == ["redis", "kafka"]


def test_ask_question_keeps_selected_dimension_when_generator_drifts(monkeypatch):
    def fake_retrieve(**_kwargs):
        class _Ctx:
            as_prompt_block = "(stub retrieval)"

        return _Ctx()

    def fake_generate_question(**kwargs):
        return {
            "question": "Tell me about a system you designed and the trade-offs you made.",
            "dimension": "system_design",
            "rubric_points": ["trade-offs"],
            "proposed_contract": {
                "must_cover": ["trade-offs"],
                "acceptance_checks": ["Explains at least one trade-off."],
                "minimum_bar": "One concrete mechanism.",
                "bar_level": "standard",
            },
        }

    def fake_negotiate(**kwargs):
        return {**kwargs["proposed_contract"], "signed_by": ["generator", "evaluator"]}

    monkeypatch.setattr(ask_mod, "retrieve_for_question", fake_retrieve)
    monkeypatch.setattr(ask_mod, "retrieve_strategies", lambda **_kwargs: [])
    monkeypatch.setattr(
        ask_mod,
        "format_strategies_for_prompt",
        lambda _entries: "(no relevant strategy memories)",
    )
    monkeypatch.setattr(ask_mod, "generate_question", fake_generate_question)
    monkeypatch.setattr(ask_mod, "negotiate_contract_via_evaluator", fake_negotiate)

    state = {
        "session_id": "sess-dim-lock",
        "trace_id": "trace-dim-lock",
        "job_spec": {
            "title": "Backend Engineer",
            "level": "mid",
            "required_skills": ["redis"],
        },
        "candidate": {"resume_parsed": {"projects": [], "focus_areas": []}},
        "dimensions": ["technical_depth", "system_design"],
        "dimension_status": {"technical_depth": "active"},
        "current_dimension": "technical_depth",
        "turn_idx": 2,
        "formal_turn_idx": 1,
        "qa_history": [],
        "runtime_config": {},
        "refine_mode": False,
        "current_ask_plan": None,
        "current_contract": None,
        "pending_plan_template": None,
        "pending_contract_hints": None,
        "selected_action": {"id": "plan_deep_probe", "plan_template": "deep_probe"},
    }

    out = ask_mod.ask_question_node(state)  # type: ignore[arg-type]

    assert out["current_question"]["dimension"] == "technical_depth"
    assert out["current_question"]["model_dimension"] == "system_design"
    assert "Tell me about" not in out["current_question"]["question"]
    assert "请结合" in out["current_question"]["question"]
    assert out["current_question"]["language_fallback"] is True


def test_ask_question_rewrites_recent_duplicate_question(monkeypatch):
    repeated = "Tell me about a system you designed and the trade-offs you made."

    def fake_retrieve(**_kwargs):
        class _Ctx:
            as_prompt_block = "(stub retrieval)"

        return _Ctx()

    def fake_generate_question(**kwargs):
        return {
            "question": repeated,
            "dimension": kwargs["dimension"],
            "rubric_points": ["depth"],
            "proposed_contract": {
                "must_cover": ["depth"],
                "acceptance_checks": ["Names a concrete example."],
                "minimum_bar": "One concrete example.",
                "bar_level": "standard",
            },
        }

    def fake_negotiate(**kwargs):
        return {**kwargs["proposed_contract"], "signed_by": ["generator", "evaluator"]}

    monkeypatch.setattr(ask_mod, "retrieve_for_question", fake_retrieve)
    monkeypatch.setattr(ask_mod, "retrieve_strategies", lambda **_kwargs: [])
    monkeypatch.setattr(
        ask_mod,
        "format_strategies_for_prompt",
        lambda _entries: "(no relevant strategy memories)",
    )
    monkeypatch.setattr(ask_mod, "generate_question", fake_generate_question)
    monkeypatch.setattr(ask_mod, "negotiate_contract_via_evaluator", fake_negotiate)

    state = {
        "session_id": "sess-dedupe",
        "trace_id": "trace-dedupe",
        "job_spec": {
            "title": "Backend Engineer",
            "level": "mid",
            "required_skills": ["redis", "kafka"],
        },
        "candidate": {
            "resume_parsed": {
                "projects": [
                    {
                        "id": "proj-1",
                        "name": "Order System",
                        "tech_stack": ["Redis", "Kafka"],
                    }
                ],
                "focus_areas": [
                    {
                        "id": "focus-1",
                        "project_id": "proj-1",
                        "dimensions": ["technical_depth"],
                        "skills": ["Redis", "Kafka"],
                        "priority": 1,
                    }
                ],
            }
        },
        "dimensions": ["technical_depth"],
        "dimension_status": {"technical_depth": "active"},
        "current_dimension": "technical_depth",
        "turn_idx": 2,
        "formal_turn_idx": 1,
        "qa_history": [{"turn_idx": 0, "question": repeated}],
        "runtime_config": {},
        "refine_mode": False,
        "current_ask_plan": None,
        "current_contract": None,
        "pending_plan_template": None,
        "pending_contract_hints": None,
        "selected_action": {"id": "plan_deep_probe", "plan_template": "deep_probe"},
    }

    out = ask_mod.ask_question_node(state)  # type: ignore[arg-type]
    question = out["current_question"]["question"]

    assert question != repeated
    assert "Order System" in question
    assert "redis" in question.lower()
    assert out["current_question"]["duplicate_rewrite"] is True


def test_ask_question_rewrites_near_duplicate_generic_fallback(monkeypatch):
    previous = (
        "请结合「康乐智慧养老系统」中与「springsecurity、mybatis-plus、springboot」"
        "相关的技术深度场景，说明当时的约束、备选方案和最终取舍。"
        "再补充你如何用指标、故障复盘或上线结果验证这个选择，"
        "以及如果规模或故障压力更高会怎么演进。"
    )
    current = (
        "请结合「康乐智慧养老系统」中与「spring-security、springboot、springsecurity」"
        "相关的系统设计场景，说明当时的约束、备选方案和最终取舍。"
        "再补充你如何用指标、故障复盘或上线结果验证这个选择，"
        "以及如果规模或故障压力更高会怎么演进。"
    )

    def fake_retrieve(**_kwargs):
        class _Ctx:
            as_prompt_block = "(stub retrieval)"

        return _Ctx()

    def fake_generate_question(**kwargs):
        return {
            "question": current,
            "dimension": kwargs["dimension"],
            "rubric_points": ["capacity"],
            "proposed_contract": {
                "must_cover": ["capacity"],
                "acceptance_checks": ["Explains one capacity decision."],
                "minimum_bar": "One concrete decision.",
                "bar_level": "standard",
            },
        }

    def fake_negotiate(**kwargs):
        return {**kwargs["proposed_contract"], "signed_by": ["generator", "evaluator"]}

    monkeypatch.setattr(ask_mod, "retrieve_for_question", fake_retrieve)
    monkeypatch.setattr(ask_mod, "retrieve_strategies", lambda **_kwargs: [])
    monkeypatch.setattr(
        ask_mod,
        "format_strategies_for_prompt",
        lambda _entries: "(no relevant strategy memories)",
    )
    monkeypatch.setattr(ask_mod, "generate_question", fake_generate_question)
    monkeypatch.setattr(ask_mod, "negotiate_contract_via_evaluator", fake_negotiate)

    state = {
        "session_id": "sess-near-duplicate",
        "trace_id": "trace-near-duplicate",
        "job_spec": {
            "title": "Java 后端工程师",
            "level": "junior",
            "required_skills": ["spring-security", "springboot"],
        },
        "candidate": {
            "resume_parsed": {
                "projects": [
                    {
                        "id": "proj-eldercare",
                        "name": "康乐智慧养老系统",
                        "tech_stack": ["springboot", "springsecurity"],
                    }
                ],
                "focus_areas": [
                    {
                        "id": "focus-eldercare",
                        "project_id": "proj-eldercare",
                        "dimensions": ["system_design"],
                        "skills": ["spring-security", "springboot"],
                        "priority": 1,
                    }
                ],
            }
        },
        "dimensions": ["system_design"],
        "dimension_status": {"system_design": "active"},
        "current_dimension": "system_design",
        "turn_idx": 8,
        "formal_turn_idx": 7,
        "qa_history": [{"turn_idx": 6, "question": previous}],
        "runtime_config": {},
        "refine_mode": False,
        "current_ask_plan": None,
        "current_contract": None,
        "pending_plan_template": None,
        "pending_contract_hints": None,
        "selected_action": {"id": "plan_hint", "plan_template": "simple"},
    }

    out = ask_mod.ask_question_node(state)  # type: ignore[arg-type]
    question = out["current_question"]["question"]

    assert question != current
    assert out["current_question"]["duplicate_rewrite"] is True
    assert "康乐智慧养老系统" in question
    assert "约束、备选方案和最终取舍" not in question


def test_ask_question_rewrites_english_generated_question_to_chinese(monkeypatch):
    english_question = (
        "In your AI health assessment project, you improved accuracy from 60% "
        "to over 90% using prompt engineering and post-processing validation. "
        "Could you walk us through the specific technical measures?"
    )

    def fake_retrieve(**_kwargs):
        class _Ctx:
            as_prompt_block = "(stub retrieval)"

        return _Ctx()

    def fake_generate_question(**kwargs):
        return {
            "question": english_question,
            "dimension": kwargs["dimension"],
            "rubric_points": ["technical measures"],
            "proposed_contract": {
                "must_cover": ["technical measures"],
                "acceptance_checks": ["Names concrete measures."],
                "minimum_bar": "One concrete measure.",
                "bar_level": "standard",
            },
        }

    def fake_negotiate(**kwargs):
        return {**kwargs["proposed_contract"], "signed_by": ["generator", "evaluator"]}

    monkeypatch.setattr(ask_mod, "retrieve_for_question", fake_retrieve)
    monkeypatch.setattr(ask_mod, "retrieve_strategies", lambda **_kwargs: [])
    monkeypatch.setattr(
        ask_mod,
        "format_strategies_for_prompt",
        lambda _entries: "(no relevant strategy memories)",
    )
    monkeypatch.setattr(ask_mod, "generate_question", fake_generate_question)
    monkeypatch.setattr(ask_mod, "negotiate_contract_via_evaluator", fake_negotiate)

    state = {
        "session_id": "sess-language",
        "trace_id": "trace-language",
        "job_spec": {
            "title": "Java 后端工程师",
            "level": "mid",
            "required_skills": ["prompt engineering", "validation"],
        },
        "candidate": {
            "resume_parsed": {
                "projects": [
                    {
                        "id": "proj-ai-health",
                        "name": "AI 健康评估项目",
                        "tech_stack": ["Prompt Engineering", "Validation"],
                    }
                ],
                "focus_areas": [
                    {
                        "id": "focus-ai-health",
                        "project_id": "proj-ai-health",
                        "dimensions": ["technical_depth"],
                        "skills": ["Prompt Engineering", "Validation"],
                        "priority": 1,
                    }
                ],
            }
        },
        "dimensions": ["technical_depth"],
        "dimension_status": {"technical_depth": "active"},
        "current_dimension": "technical_depth",
        "turn_idx": 1,
        "formal_turn_idx": 0,
        "qa_history": [],
        "runtime_config": {},
        "refine_mode": False,
        "current_ask_plan": None,
        "current_contract": None,
        "pending_plan_template": None,
        "pending_contract_hints": None,
        "selected_action": {"id": "plan_deep_probe", "plan_template": "deep_probe"},
    }

    out = ask_mod.ask_question_node(state)  # type: ignore[arg-type]
    question = out["current_question"]["question"]

    assert question != english_question
    assert "请结合" in question
    assert "AI 健康评估项目" in question
    assert "prompt-engineering" in question
    assert out["current_question"]["language_fallback"] is True
    assert out["current_question"]["original_question"] == english_question
