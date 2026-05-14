"""Resume-driven interview planning tests."""
from __future__ import annotations

from typing import Any

from app.engine.rag import retriever as retriever_mod
from app.engine.workflow.nodes import ask_question as ask_mod


def test_retrieve_for_question_query_includes_resume_anchor(monkeypatch):
    captured: dict[str, Any] = {}

    class Store:
        def similarity_search(self, query: str, k: int):
            captured["query"] = query
            captured["k"] = k
            return []

    monkeypatch.setattr(retriever_mod, "get_vectorstore", lambda: Store())

    retrieval = retriever_mod.retrieve_for_question(
        job_spec={
            "title": "Java Backend Engineer",
            "required_skills": ["spring"],
            "interview_direction_label": "Java 后端开发",
        },
        dimension="system_design",
        resume_anchor={
            "project_name": "BluePay payment migration",
            "tech_stack": ["Kafka", "Redis"],
            "question_anchors": ["一致性", "性能优化"],
        },
    )

    assert retrieval.as_prompt_block == "(no relevant knowledge retrieved)"
    query = captured["query"]
    assert "Java Backend Engineer" in query
    assert "Java 后端开发" in query
    assert "BluePay payment migration" in query
    assert "Kafka" in query
    assert "Redis" in query
    assert "一致性" in query


def test_ask_question_selects_resume_anchor_and_passes_to_generator(monkeypatch):
    captured: dict[str, Any] = {}

    def fake_retrieve(**kwargs):
        captured["retrieve_resume_anchor"] = kwargs.get("resume_anchor")

        class _Ctx:
            as_prompt_block = "(stub retrieval)"

        return _Ctx()

    def fake_retrieve_strategies(**_kwargs):
        return []

    def fake_format_strategies(_entries):
        return "(no relevant strategy memories)"

    def fake_generate_question(**kwargs):
        captured["generate_resume_anchor"] = kwargs.get("resume_anchor")
        return {
            "question": "围绕 BluePay 迁移项目，讲讲你如何处理 Kafka 消费幂等？",
            "dimension": kwargs["dimension"],
            "rubric_points": ["idempotency"],
            "proposed_contract": {
                "must_cover": ["idempotency"],
                "acceptance_checks": ["Mentions an idempotent consumer."],
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
        "session_id": "sess-resume",
        "trace_id": "trace-resume",
        "job_spec": {
            "title": "Java Backend Engineer",
            "level": "senior",
            "required_skills": ["java", "kafka"],
        },
        "candidate": {
            "name": "Li Lei",
            "resume_parsed": {
                "highlights": [],
                "projects": [
                    {
                        "id": "proj-1",
                        "name": "BluePay payment migration",
                        "role": "owner",
                        "tech_stack": ["Kafka", "Redis"],
                        "achievements": ["Reduced p99 from 800ms to 120ms."],
                        "question_anchors": ["一致性", "性能优化"],
                    }
                ],
                "focus_areas": [
                    {
                        "id": "focus-1",
                        "label": "支付迁移中的幂等和一致性",
                        "project_id": "proj-1",
                        "dimensions": ["system_design", "technical_depth"],
                        "skills": ["Kafka", "Redis"],
                        "priority": 1,
                    }
                ],
            },
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
        "selected_action": {"id": "deepen_technical"},
    }

    out = ask_mod.ask_question_node(state)  # type: ignore[arg-type]

    assert captured["retrieve_resume_anchor"]["project_id"] == "proj-1"
    assert captured["generate_resume_anchor"]["project_name"] == "BluePay payment migration"
    assert out["current_question"]["resume_anchor"]["project_name"] == (
        "BluePay payment migration"
    )
    assert out["current_question"]["question_basis"]["title"] == "为什么问这一题"
    assert "来自简历" in out["current_question"]["question_basis"]["chips"]
    assert "来自岗位要求" in out["current_question"]["question_basis"]["chips"]
    assert "系统设计" in out["current_question"]["question_basis"]["chips"]
