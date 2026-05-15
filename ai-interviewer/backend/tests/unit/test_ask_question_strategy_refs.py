from __future__ import annotations

from pathlib import Path
from typing import Any

from app.engine.workflow.nodes import ask_question as ask_mod
from app.memory.strategy_store import StrategyEntry


def test_ask_question_persists_strategy_memory_refs(monkeypatch) -> None:
    def fake_retrieve_for_question(**_kwargs):
        class _Ctx:
            as_prompt_block = "(stub retrieval)"

        return _Ctx()

    strategy = StrategyEntry(
        path=Path("senior_system_design.md"),
        id="seed:senior_system_design",
        slug="senior_system_design",
        memory_key="seed:system_design:senior",
        name="Senior System Design",
        description="Deep probes for senior system design.",
        entry_type="strategy",
        source="seed",
        status="active",
        promotion_stage="seed",
        confidence=0.8,
        support_count=20,
        dimensions=["system_design"],
        job_levels=["senior"],
        body="Push for concrete trade-offs and failure modes.",
    )

    def fake_generate_question(**kwargs):
        return {
            "question": "请结合订单系统讲一次系统设计取舍。",
            "dimension": kwargs["dimension"],
            "rubric_points": ["方案取舍"],
            "proposed_contract": {
                "must_cover": ["方案取舍"],
                "acceptance_checks": ["说明至少一个真实取舍。"],
                "minimum_bar": "能结合真实项目说明取舍。",
                "bar_level": "standard",
            },
        }

    def fake_negotiate(**kwargs):
        return {**kwargs["proposed_contract"], "signed_by": ["generator", "evaluator"]}

    captured_retrieve_kwargs: dict[str, Any] = {}

    def fake_retrieve_strategies(**kwargs):
        captured_retrieve_kwargs.update(kwargs)
        return [strategy]

    monkeypatch.setattr(ask_mod, "retrieve_for_question", fake_retrieve_for_question)
    monkeypatch.setattr(ask_mod, "retrieve_strategies", fake_retrieve_strategies)
    monkeypatch.setattr(
        ask_mod,
        "format_strategies_for_prompt",
        lambda entries: "\n".join(entry.body for entry in entries),
    )
    monkeypatch.setattr(ask_mod, "generate_question", fake_generate_question)
    monkeypatch.setattr(ask_mod, "negotiate_contract_via_evaluator", fake_negotiate)

    captured_trace: dict[str, Any] = {}

    class _Tracer:
        def trace_node_event(self, _state, *, node, payload, **_kwargs):
            if node == "ask_question":
                captured_trace.update(payload)

    monkeypatch.setattr(ask_mod, "get_tracer", lambda: _Tracer())

    state = {
        "session_id": "sess-strategy-ref",
        "trace_id": "trace-strategy-ref",
        "job_spec": {
            "title": "Senior Backend Engineer",
            "level": "senior",
            "required_skills": ["redis"],
        },
        "candidate": {"resume_parsed": {"projects": [], "focus_areas": []}},
        "dimensions": ["system_design"],
        "dimension_status": {"system_design": "active"},
        "current_dimension": "system_design",
        "turn_idx": 1,
        "formal_turn_idx": 0,
        "qa_history": [],
        "runtime_config": {},
        "refine_mode": False,
        "current_ask_plan": None,
        "current_contract": None,
        "pending_plan_template": None,
        "pending_contract_hints": None,
        "selected_action": {"id": "plan_adaptive", "plan_template": "adaptive"},
        "policy_context_keys": [
            "java_backend:senior:system_design",
            "senior:system_design",
        ],
    }

    out = ask_mod.ask_question_node(state)  # type: ignore[arg-type]

    expected_ref = {
        "id": "seed:senior_system_design",
        "slug": "senior_system_design",
        "memory_key": "seed:system_design:senior",
        "name": "Senior System Design",
        "source": "seed",
        "status": "active",
        "promotion_stage": "seed",
        "confidence": 0.8,
        "support_count": 20,
    }
    assert out["current_question"]["strategy_memory_refs"] == [expected_ref]
    assert captured_trace["strategy_memory_refs"] == [expected_ref]
    assert captured_retrieve_kwargs["policy_context_keys"] == [
        "java_backend:senior:system_design",
        "senior:system_design",
    ]
