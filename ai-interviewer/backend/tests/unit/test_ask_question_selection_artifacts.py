from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

from app.engine.rag.retriever import RetrievalContext
from app.engine.rag.vectorstore import RetrievedDoc
from app.engine.workflow.nodes import ask_question as ask_mod
from app.memory.skill_store import SkillEntry
from app.memory.strategy_store import StrategyEntry


def test_ask_question_records_selection_artifacts(monkeypatch) -> None:
    retrieval = RetrievalContext(
        docs=[
            RetrievedDoc(
                text="Do not copy retrieved text into selection artifacts.",
                metadata={
                    "source": "strategy/system_design.md",
                    "chunk": 2,
                    "source_type": "strategy",
                },
                score=0.83,
            ),
        ],
        as_prompt_block="[1] retrieved prompt block",
    )
    strategy = StrategyEntry(
        path=Path("senior_system_design.md"),
        id="seed:senior_system_design",
        slug="senior_system_design",
        memory_key="seed:system_design:senior",
        name="Senior System Design",
        source="seed",
        status="active",
        promotion_stage="seed",
        confidence=0.8,
        support_count=20,
        dimensions=["system_design"],
        job_levels=["senior"],
        body="Push for concrete trade-offs.",
        shadow_rank=1,
        ranking_score=3.5,
        ranking_reason={
            "stats_context_key": "java_backend:senior:system_design",
            "stats_scope": "exact",
        },
    )
    skill = SkillEntry(
        path=Path("system_design_scale_reasoning.md"),
        name="System Design Scale Reasoning",
        description="Probe scale assumptions.",
        dimensions=["system_design"],
        job_levels=["senior"],
        body="Ask for load and failure modes.",
    )

    def fake_generate_question(**kwargs):
        return {
            "question": "请结合订单系统讲一次容量设计取舍。",
            "dimension": kwargs["dimension"],
            "proposed_contract": {
                "must_cover": ["容量估算"],
                "acceptance_checks": ["说明一个容量取舍。"],
                "minimum_bar": "能说明容量约束。",
                "bar_level": "standard",
            },
        }

    def fake_negotiate(**kwargs):
        return {**kwargs["proposed_contract"], "signed_by": ["generator", "evaluator"]}

    monkeypatch.setattr(ask_mod, "retrieve_for_question", lambda **_kwargs: retrieval)
    monkeypatch.setattr(ask_mod, "retrieve_strategies", lambda **_kwargs: [strategy])
    monkeypatch.setattr(
        ask_mod,
        "format_strategies_for_prompt",
        lambda entries: "\n".join(entry.body for entry in entries),
    )
    monkeypatch.setattr(ask_mod, "retrieve_skills", lambda **_kwargs: [skill])
    monkeypatch.setattr(
        ask_mod,
        "build_skills_block",
        lambda entries: "\n".join(entry.body for entry in entries),
    )
    monkeypatch.setattr(
        ask_mod,
        "build_generator_avoid_patterns",
        lambda **_kwargs: "avoid shallow evidence",
    )
    monkeypatch.setattr(ask_mod, "generate_question", fake_generate_question)
    monkeypatch.setattr(ask_mod, "negotiate_contract_via_evaluator", fake_negotiate)
    monkeypatch.setattr(
        ask_mod,
        "get_settings",
        lambda: SimpleNamespace(
            enable_llm_memory_selector=False,
            enable_skill_injection=True,
            skill_retrieval_limit=3,
            enable_generator_avoid_patterns=True,
            drift_feedback_top_n=3,
            drift_feedback_min_support=2,
        ),
    )

    captured_trace: dict[str, Any] = {}

    class _Tracer:
        def trace_node_event(self, _state, *, node, payload, **_kwargs):
            if node == "ask_question":
                captured_trace.update(payload)

    monkeypatch.setattr(ask_mod, "get_tracer", lambda: _Tracer())

    state = {
        "session_id": "sess-selection-artifacts",
        "trace_id": "trace-selection-artifacts",
        "job_spec": {
            "title": "Senior Backend Engineer",
            "level": "senior",
            "required_skills": ["redis"],
            "interview_direction": "java_backend",
        },
        "candidate": {"resume_parsed": {"projects": [], "focus_areas": []}},
        "dimensions": ["system_design"],
        "dimension_status": {"system_design": "active"},
        "current_dimension": "system_design",
        "turn_idx": 1,
        "formal_turn_idx": 0,
        "qa_history": [],
        "runtime_config": {"rag_mode": "vector", "rag_top_k": 2},
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

    artifacts = out["current_question"]["selection_artifacts"]
    assert captured_trace["selection_artifacts"] == artifacts
    assert artifacts["rag"]["mode"] == "vector"
    assert artifacts["rag"]["top_k"] == 2
    assert artifacts["rag"]["empty"] is False
    assert artifacts["rag"]["doc_refs"] == [
        {
            "source": "strategy/system_design.md",
            "chunk": 2,
            "source_type": "strategy",
            "score": 0.83,
        }
    ]
    assert "text" not in artifacts["rag"]["doc_refs"][0]
    assert artifacts["strategies"][0]["id"] == "seed:senior_system_design"
    assert artifacts["strategies"][0]["ranking_reason"]["stats_scope"] == "exact"
    assert artifacts["skills"]["enabled"] is True
    assert artifacts["skills"]["refs"] == [
        {
            "filename": "system_design_scale_reasoning.md",
            "name": "System Design Scale Reasoning",
            "description": "Probe scale assumptions.",
            "dimensions": ["system_design"],
            "job_levels": ["senior"],
        }
    ]
    assert artifacts["avoid_patterns"] == {
        "enabled": True,
        "rendered": True,
        "dimension": "system_design",
        "top_n": 3,
        "min_support": 2,
    }
    assert artifacts["question_items"] == []


def _make_retrieval(*, docs: list[RetrievedDoc] | None = None) -> RetrievalContext:
    return RetrievalContext(
        docs=list(docs) if docs is not None else [
            RetrievedDoc(
                text="Hidden retrieval text — must not leak into artifacts.",
                metadata={
                    "source": "strategy/system_design.md",
                    "chunk": 2,
                    "source_type": "strategy",
                },
                score=0.83,
            ),
        ],
        as_prompt_block="[1] retrieved prompt block",
    )


def _make_strategy() -> StrategyEntry:
    return StrategyEntry(
        path=Path("senior_system_design.md"),
        id="seed:senior_system_design",
        slug="senior_system_design",
        memory_key="seed:system_design:senior",
        name="Senior System Design",
        source="seed",
        status="active",
        promotion_stage="seed",
        confidence=0.8,
        support_count=20,
        dimensions=["system_design"],
        job_levels=["senior"],
        body="Push for concrete trade-offs.",
    )


def _make_skill() -> SkillEntry:
    return SkillEntry(
        path=Path("system_design_scale_reasoning.md"),
        name="System Design Scale Reasoning",
        description="Probe scale assumptions.",
        dimensions=["system_design"],
        job_levels=["senior"],
        body="Ask for load and failure modes.",
    )


def _fake_generate_question(**kwargs):
    return {
        "question": "请结合订单系统讲一次容量设计取舍。",
        "dimension": kwargs["dimension"],
        "proposed_contract": {
            "must_cover": ["容量估算"],
            "acceptance_checks": ["说明一个容量取舍。"],
            "minimum_bar": "能说明容量约束。",
            "bar_level": "standard",
        },
    }


def _fake_negotiate(**kwargs):
    return {**kwargs["proposed_contract"], "signed_by": ["generator", "evaluator"]}


def _install_default_patches(
    monkeypatch,
    *,
    retrieval: RetrievalContext,
    strategies: list[StrategyEntry],
    skills: list[SkillEntry] | None = None,
    avoid_patterns_output: str = "avoid shallow evidence",
    enable_skill_injection: bool = True,
    enable_generator_avoid_patterns: bool = True,
) -> dict[str, Any]:
    monkeypatch.setattr(ask_mod, "retrieve_for_question", lambda **_kw: retrieval)
    monkeypatch.setattr(ask_mod, "retrieve_strategies", lambda **_kw: list(strategies))
    monkeypatch.setattr(
        ask_mod,
        "format_strategies_for_prompt",
        lambda entries: "\n".join(entry.body for entry in entries),
    )
    monkeypatch.setattr(ask_mod, "retrieve_skills", lambda **_kw: list(skills or []))
    monkeypatch.setattr(
        ask_mod,
        "build_skills_block",
        lambda entries: "\n".join(entry.body for entry in entries),
    )
    monkeypatch.setattr(
        ask_mod,
        "build_generator_avoid_patterns",
        lambda **_kw: avoid_patterns_output,
    )
    monkeypatch.setattr(ask_mod, "generate_question", _fake_generate_question)
    monkeypatch.setattr(ask_mod, "negotiate_contract_via_evaluator", _fake_negotiate)
    monkeypatch.setattr(
        ask_mod,
        "get_settings",
        lambda: SimpleNamespace(
            enable_llm_memory_selector=False,
            enable_skill_injection=enable_skill_injection,
            skill_retrieval_limit=3,
            enable_generator_avoid_patterns=enable_generator_avoid_patterns,
            drift_feedback_top_n=3,
            drift_feedback_min_support=2,
        ),
    )

    captured: dict[str, Any] = {}

    class _Tracer:
        def trace_node_event(self, _state, *, node, payload, **_kwargs):
            if node == "ask_question":
                captured.update(payload)

    monkeypatch.setattr(ask_mod, "get_tracer", lambda: _Tracer())
    return captured


def _base_state(**overrides: Any) -> dict[str, Any]:
    state: dict[str, Any] = {
        "session_id": "sess-selection-artifacts",
        "trace_id": "trace-selection-artifacts",
        "job_spec": {
            "title": "Senior Backend Engineer",
            "level": "senior",
            "required_skills": ["redis"],
            "interview_direction": "java_backend",
        },
        "candidate": {"resume_parsed": {"projects": [], "focus_areas": []}},
        "dimensions": ["system_design"],
        "dimension_status": {"system_design": "active"},
        "current_dimension": "system_design",
        "turn_idx": 1,
        "formal_turn_idx": 0,
        "qa_history": [],
        "runtime_config": {"rag_mode": "vector", "rag_top_k": 2},
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
    state.update(overrides)
    return state


def _raise_if_called(*_args: Any, **_kwargs: Any) -> Any:
    raise AssertionError("guarded helper must not be invoked in this scenario")


def test_ask_question_records_empty_rag(monkeypatch) -> None:
    """RAG retrieval returns no docs -> empty=True, reason=no_relevant_knowledge."""
    captured = _install_default_patches(
        monkeypatch,
        retrieval=_make_retrieval(docs=[]),
        strategies=[_make_strategy()],
        skills=[_make_skill()],
    )

    out = ask_mod.ask_question_node(_base_state())  # type: ignore[arg-type]

    artifacts = out["current_question"]["selection_artifacts"]
    assert captured["selection_artifacts"] == artifacts
    assert artifacts["rag"]["empty"] is True
    assert artifacts["rag"]["reason"] == "no_relevant_knowledge"
    assert artifacts["rag"]["doc_refs"] == []
    assert artifacts["rag"]["mode"] == "vector"
    assert artifacts["rag"]["top_k"] == 2


def test_ask_question_skill_injection_disabled(monkeypatch) -> None:
    """Skill injection off -> enabled=False, refs=[] and retrieve_skills skipped."""
    captured = _install_default_patches(
        monkeypatch,
        retrieval=_make_retrieval(),
        strategies=[_make_strategy()],
        enable_skill_injection=False,
    )
    monkeypatch.setattr(ask_mod, "retrieve_skills", _raise_if_called)

    out = ask_mod.ask_question_node(_base_state())  # type: ignore[arg-type]

    artifacts = out["current_question"]["selection_artifacts"]
    assert captured["selection_artifacts"] == artifacts
    assert artifacts["skills"] == {"enabled": False, "refs": []}


def test_ask_question_avoid_patterns_disabled(monkeypatch) -> None:
    """Avoid-pattern flag off -> enabled=False, rendered=False, renderer skipped."""
    captured = _install_default_patches(
        monkeypatch,
        retrieval=_make_retrieval(),
        strategies=[_make_strategy()],
        skills=[_make_skill()],
        enable_generator_avoid_patterns=False,
    )
    monkeypatch.setattr(ask_mod, "build_generator_avoid_patterns", _raise_if_called)

    out = ask_mod.ask_question_node(_base_state())  # type: ignore[arg-type]

    artifacts = out["current_question"]["selection_artifacts"]
    assert captured["selection_artifacts"] == artifacts
    assert artifacts["avoid_patterns"] == {
        "enabled": False,
        "rendered": False,
        "dimension": "system_design",
        "top_n": 3,
        "min_support": 2,
    }


def test_ask_question_avoid_patterns_renderer_empty(monkeypatch) -> None:
    """Avoid-pattern flag on but renderer returns empty -> rendered=False."""
    captured = _install_default_patches(
        monkeypatch,
        retrieval=_make_retrieval(),
        strategies=[_make_strategy()],
        skills=[_make_skill()],
        avoid_patterns_output="",
    )

    out = ask_mod.ask_question_node(_base_state())  # type: ignore[arg-type]

    artifacts = out["current_question"]["selection_artifacts"]
    assert captured["selection_artifacts"] == artifacts
    assert artifacts["avoid_patterns"]["enabled"] is True
    assert artifacts["avoid_patterns"]["rendered"] is False


def test_ask_question_artifacts_default_failure_categories_empty(monkeypatch) -> None:
    """No ``pending_contract_hints`` -> artifacts.failure_categories == []."""
    captured = _install_default_patches(
        monkeypatch,
        retrieval=_make_retrieval(),
        strategies=[_make_strategy()],
        skills=[_make_skill()],
    )

    out = ask_mod.ask_question_node(_base_state())  # type: ignore[arg-type]

    artifacts = out["current_question"]["selection_artifacts"]
    assert captured["selection_artifacts"] == artifacts
    assert artifacts["failure_categories"] == []


def test_ask_question_artifacts_forward_multi_failure_categories(monkeypatch) -> None:
    """When ``pending_contract_hints`` carries a structured list, it
    flows verbatim into the selection artifacts so downstream tracing
    and admin can group by failure category."""
    captured = _install_default_patches(
        monkeypatch,
        retrieval=_make_retrieval(),
        strategies=[_make_strategy()],
        skills=[_make_skill()],
    )

    state = _base_state(
        pending_contract_hints={
            "failure_categories": ["missing_metrics", "missing_evidence"],
            "failure_category": "missing_metrics",
            "refine_mode": True,
        }
    )

    out = ask_mod.ask_question_node(state)  # type: ignore[arg-type]

    artifacts = out["current_question"]["selection_artifacts"]
    assert captured["selection_artifacts"] == artifacts
    assert artifacts["failure_categories"] == [
        "missing_metrics",
        "missing_evidence",
    ]


def test_ask_question_artifacts_legacy_single_failure_category(monkeypatch) -> None:
    """Pre-PR2 callers may still ship only the single legacy field;
    artifacts should still surface it as a one-item list so consumers
    have ONE shape to read."""
    captured = _install_default_patches(
        monkeypatch,
        retrieval=_make_retrieval(),
        strategies=[_make_strategy()],
        skills=[_make_skill()],
    )

    state = _base_state(
        pending_contract_hints={
            "failure_category": "weak_debugging",
            "refine_mode": True,
        }
    )

    out = ask_mod.ask_question_node(state)  # type: ignore[arg-type]

    artifacts = out["current_question"]["selection_artifacts"]
    assert captured["selection_artifacts"] == artifacts
    assert artifacts["failure_categories"] == ["weak_debugging"]
