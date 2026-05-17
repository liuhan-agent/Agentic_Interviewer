from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

from app.engine.rag.retriever import RetrievalContext
from app.engine.rag.vectorstore import RetrievedDoc
from app.engine.workflow.nodes import ask_question as ask_mod
from app.memory.skill_store import SkillEntry
from app.memory.strategy_store import StrategyEntry
from app.services.question_selector import QuestionCandidate, QuestionSelectionResult

_COVERED_PRIMARY_ROLE_TAGS = [
    "java_backend",
    "frontend_web",
    "sre",
    "ai_fullstack",
    "ai_agent",
    "mobile",
    "ai_algorithm",
    "architect",
    "product_manager",
    "operations",
    "sales_business",
    "marketing_brand",
    "hr_function",
    "customer_success",
    "general_management",
]


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
        id="system_design_scale_reasoning",
        name="System Design Scale Reasoning",
        description="Probe scale assumptions.",
        priority=4,
        direction_tags=["internet_tech"],
        role_tags=["java_backend"],
        dimensions=["system_design"],
        job_levels=["senior"],
        probe_intents=["architecture_challenge"],
        failure_categories=["missing_scale_reasoning"],
        body="Ask for load and failure modes.",
        match_score=42.0,
        match_reasons=["dimension:system_design", "role_tag:java_backend"],
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
            "id": "system_design_scale_reasoning",
            "name": "System Design Scale Reasoning",
            "description": "Probe scale assumptions.",
            "status": "active",
            "priority": 4,
            "direction_tags": ["internet_tech"],
            "role_tags": ["java_backend"],
            "dimensions": ["system_design"],
            "job_levels": ["senior"],
            "probe_intents": ["architecture_challenge"],
            "failure_categories": ["missing_scale_reasoning"],
            "match_score": 42.0,
            "match_reasons": ["dimension:system_design", "role_tag:java_backend"],
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
        id="system_design_scale_reasoning",
        name="System Design Scale Reasoning",
        description="Probe scale assumptions.",
        status="active",
        priority=4,
        direction_tags=["internet_tech"],
        role_tags=["java_backend"],
        dimensions=["system_design"],
        job_levels=["senior"],
        probe_intents=["architecture_challenge"],
        failure_categories=["missing_scale_reasoning"],
        body="Ask for load and failure modes.",
        match_score=42.0,
        match_reasons=[
            "dimension:system_design",
            "role_tag:java_backend",
        ],
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
    enable_question_fit_profile: bool = True,
    enable_question_reranker_shadow: bool = False,
    question_primary_role_tags: list[str] | None = None,
) -> dict[str, Any]:
    monkeypatch.setattr(ask_mod, "retrieve_for_question", lambda **_kw: retrieval)
    monkeypatch.setattr(ask_mod, "retrieve_strategies", lambda **_kw: list(strategies))
    monkeypatch.setattr(
        ask_mod,
        "format_strategies_for_prompt",
        lambda entries: "\n".join(entry.body for entry in entries),
    )
    captured: dict[str, Any] = {}

    def fake_retrieve_skills(**kwargs):
        captured["skill_retrieve_kwargs"] = kwargs
        return list(skills or [])

    monkeypatch.setattr(ask_mod, "retrieve_skills", fake_retrieve_skills)
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
            enable_question_fit_profile=enable_question_fit_profile,
            enable_question_reranker_shadow=enable_question_reranker_shadow,
            question_reranker_timeout_ms=4000,
            question_primary_role_tags=question_primary_role_tags
            or list(_COVERED_PRIMARY_ROLE_TAGS),
        ),
    )

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
    assert captured["skill_retrieve_kwargs"]["direction_tags"] == ["internet_tech"]
    assert captured["skill_retrieve_kwargs"]["role_tags"] == ["java_backend"]
    assert captured["skill_retrieve_kwargs"]["probe_intent"] == "architecture_challenge"
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


def _install_avoid_kwargs_capture(monkeypatch) -> dict[str, Any]:
    """Wrap ``build_generator_avoid_patterns`` with a kwargs-capture stub.

    The default ``_install_default_patches`` stub discards the kwargs
    because every existing test cares only about the rendered output.
    The drift-feedback persistence track (PR5 source switch) needs to
    pin the *call shape* — specifically that ``ask_question`` forwards
    ``failure_categories`` so the DB-backed path can drill into the
    ``(dimension, check, failure_category)`` buckets instead of always
    falling back to ``__global__``.
    """
    captured_kwargs: dict[str, Any] = {}

    def _capture(**kwargs: Any) -> str:
        captured_kwargs.clear()
        captured_kwargs.update(kwargs)
        return "rendered avoid patterns"

    monkeypatch.setattr(ask_mod, "build_generator_avoid_patterns", _capture)
    return captured_kwargs


def test_ask_question_forwards_failure_categories_to_avoid_patterns(
    monkeypatch,
) -> None:
    """When ``pending_contract_hints`` declares a structured
    ``failure_categories`` list, ``_step_retrieve_strategy`` must
    forward it to ``build_generator_avoid_patterns`` so the
    ``db`` / ``db_shadow`` feedback source can read the
    per-category ``verifier_drift_patterns`` row instead of degrading
    to the ``__global__`` rollup.
    """
    _install_default_patches(
        monkeypatch,
        retrieval=_make_retrieval(),
        strategies=[_make_strategy()],
        skills=[_make_skill()],
    )
    captured_kwargs = _install_avoid_kwargs_capture(monkeypatch)

    state = _base_state(
        pending_contract_hints={
            "failure_categories": ["missing_metrics", "missing_evidence"],
            "failure_category": "missing_metrics",
            "refine_mode": True,
        }
    )

    ask_mod.ask_question_node(state)  # type: ignore[arg-type]

    assert captured_kwargs.get("failure_categories") == [
        "missing_metrics",
        "missing_evidence",
    ]
    assert captured_kwargs.get("dimension") == "system_design"
    assert captured_kwargs.get("top_n") == 3
    assert captured_kwargs.get("min_support") == 2


def test_ask_question_forwards_legacy_single_failure_category_to_avoid_patterns(
    monkeypatch,
) -> None:
    """A legacy ``contract_hints`` shape that only sets the singular
    ``failure_category`` field must still arrive at the renderer as a
    one-item list so the DB-source query never has to branch on the
    legacy shape.
    """
    _install_default_patches(
        monkeypatch,
        retrieval=_make_retrieval(),
        strategies=[_make_strategy()],
        skills=[_make_skill()],
    )
    captured_kwargs = _install_avoid_kwargs_capture(monkeypatch)

    state = _base_state(
        pending_contract_hints={
            "failure_category": "weak_debugging",
            "refine_mode": True,
        }
    )

    ask_mod.ask_question_node(state)  # type: ignore[arg-type]

    assert captured_kwargs.get("failure_categories") == ["weak_debugging"]


def test_ask_question_forwards_empty_failure_categories_when_no_hints(
    monkeypatch,
) -> None:
    """Without any ``pending_contract_hints``, the caller still passes
    an empty list so the DB / monitor renderer falls back to the
    ``__global__`` bucket instead of being called with the legacy
    keyword-omitted shape (which would mask future regressions).
    """
    _install_default_patches(
        monkeypatch,
        retrieval=_make_retrieval(),
        strategies=[_make_strategy()],
        skills=[_make_skill()],
    )
    captured_kwargs = _install_avoid_kwargs_capture(monkeypatch)

    ask_mod.ask_question_node(_base_state())  # type: ignore[arg-type]

    assert captured_kwargs.get("failure_categories") == []


def _question_candidate(*, rank: int = 1) -> QuestionCandidate:
    return QuestionCandidate(
        seed_id="system_design.cache_consistency",
        variant_id="system_design.cache_consistency.flash_sale_inventory",
        seed_version=1,
        variant_version=1,
        rank=rank,
        match_score=42.0,
        match_reasons=["priority:30", "target_skill:redis"],
        injected=False,
        title="缓存一致性与失效策略",
        dimension="system_design",
        seed_priority=30,
        variant_priority=20,
        skill_tags=["redis", "cache"],
        rubric={"must_cover": ["一致性目标"]},
        intent="opening",
        difficulty="standard",
        scenario_brief="秒杀库存读多写少。",
        question_stem="请设计库存缓存一致性方案。",
        prompt_template="围绕缓存经验生成一道系统设计题。",
        scenario_skill_tags=["redis", "inventory"],
        resume_anchor_hints=["redis"],
        failure_categories=["missing_metrics"],
        rubric_additions=["说明缓存失效窗口"],
        expected_signals=["能区分强一致和最终一致"],
        anti_patterns=["只说加锁不讨论吞吐"],
        good_answer_hints=["先定义一致性目标"],
        direction_tags=["internet_tech"],
        role_tags=["java_backend"],
    )


def test_question_selector_vector_mode_preserves_empty_question_items(
    monkeypatch,
) -> None:
    captured = _install_default_patches(
        monkeypatch,
        retrieval=_make_retrieval(),
        strategies=[_make_strategy()],
        skills=[_make_skill()],
    )
    monkeypatch.setattr(ask_mod, "select_question_candidates", _raise_if_called)
    monkeypatch.setattr(ask_mod, "record_question_usages", _raise_if_called)
    monkeypatch.setattr(ask_mod, "build_question_fit_profile", _raise_if_called)
    monkeypatch.setattr(ask_mod, "rerank_question_candidates", _raise_if_called)

    out = ask_mod.ask_question_node(
        _base_state(runtime_config={"rag_mode": "vector", "question_selector_mode": "vector"})
    )  # type: ignore[arg-type]

    artifacts = out["current_question"]["selection_artifacts"]
    assert captured["selection_artifacts"] == artifacts
    assert artifacts["question_items"] == []
    assert "question_fit_profile" not in artifacts
    assert "question_reranker" not in artifacts
    assert "candidate_anchor" not in artifacts


def test_question_selector_structured_shadow_records_items_without_prompt_change(
    monkeypatch,
) -> None:
    generated_kwargs: dict[str, Any] = {}
    recorded: dict[str, Any] = {}
    select_kwargs: dict[str, Any] = {}

    def fake_generate_question(**kwargs):
        generated_kwargs.update(kwargs)
        return _fake_generate_question(**kwargs)

    def fake_record(**kwargs):
        recorded.update(kwargs)

    _install_default_patches(
        monkeypatch,
        retrieval=_make_retrieval(),
        strategies=[_make_strategy()],
        skills=[_make_skill()],
    )
    monkeypatch.setattr(ask_mod, "generate_question", fake_generate_question)
    monkeypatch.setattr(
        ask_mod,
        "select_question_candidates",
        lambda **kwargs: select_kwargs.update(kwargs)
        or QuestionSelectionResult(candidates=[_question_candidate()]),
    )
    monkeypatch.setattr(ask_mod, "record_question_usages", fake_record)

    out = ask_mod.ask_question_node(
        _base_state(
            runtime_config={
                "rag_mode": "vector",
                "rag_top_k": 2,
                "question_selector_mode": "structured_shadow",
            }
        )
    )  # type: ignore[arg-type]

    artifacts = out["current_question"]["selection_artifacts"]
    assert artifacts["question_items"][0]["seed_id"] == "system_design.cache_consistency"
    assert artifacts["question_items"][0]["injected"] is False
    assert artifacts["question_fit_profile"]["anchor_confidence"] == "medium"
    assert "candidate_anchor" not in artifacts
    assert generated_kwargs["retrieval_block"] == "[1] retrieved prompt block"
    assert generated_kwargs.get("question_seed_block", "") == ""
    assert generated_kwargs.get("candidate_anchor_block", "") == ""
    assert "question_seed" not in (generated_kwargs.get("contract_hints") or {})
    assert select_kwargs["fit_profile"].dimension == "system_design"
    assert recorded["question_selector_mode"] == "structured_shadow"
    assert [candidate.injected for candidate in recorded["candidates"]] == [False]


def test_question_selector_structured_shadow_reranker_records_artifact_but_keeps_rule_top(
    monkeypatch,
) -> None:
    generated_kwargs: dict[str, Any] = {}
    recorded_rerank: dict[str, Any] = {}
    candidate_1 = _question_candidate(rank=1)
    candidate_2 = QuestionCandidate(
        **{
            **candidate_1.__dict__,
            "seed_id": "system_design.queue_backpressure",
            "variant_id": "system_design.queue_backpressure.opening",
            "rank": 2,
            "match_score": 41.0,
            "title": "Queue backpressure",
        }
    )

    def fake_generate_question(**kwargs):
        generated_kwargs.update(kwargs)
        return _fake_generate_question(**kwargs)

    def fake_rerank(**_kwargs):
        return SimpleNamespace(
            status="ok",
            preferred_variant_id=candidate_2.variant_id,
            ranked_variant_ids=[candidate_2.variant_id, candidate_1.variant_id],
            fit_scores={candidate_2.variant_id: 0.9},
            anchor_choice="Inventory",
            reasons=["shadow prefers queue"],
            confidence=0.7,
            model="shadow",
            latency_ms=100,
            error=None,
            as_artifact=lambda: {
                "status": "ok",
                "preferred_variant_id": candidate_2.variant_id,
                "ranked_variant_ids": [candidate_2.variant_id, candidate_1.variant_id],
                "confidence": 0.7,
            },
        )

    _install_default_patches(
        monkeypatch,
        retrieval=_make_retrieval(),
        strategies=[_make_strategy()],
        skills=[_make_skill()],
        enable_question_reranker_shadow=True,
    )
    monkeypatch.setattr(ask_mod, "generate_question", fake_generate_question)
    monkeypatch.setattr(
        ask_mod,
        "select_question_candidates",
        lambda **_kwargs: QuestionSelectionResult(candidates=[candidate_1, candidate_2]),
    )
    monkeypatch.setattr(ask_mod, "rerank_question_candidates", fake_rerank)
    monkeypatch.setattr(
        ask_mod,
        "record_question_rerank_usage",
        lambda **kwargs: recorded_rerank.update(kwargs),
    )

    out = ask_mod.ask_question_node(
        _base_state(
            runtime_config={
                "rag_mode": "vector",
                "question_selector_mode": "structured_shadow",
            }
        )
    )  # type: ignore[arg-type]

    artifacts = out["current_question"]["selection_artifacts"]
    assert artifacts["question_items"][0]["variant_id"] == candidate_1.variant_id
    assert artifacts["question_items"][0]["injected"] is False
    assert artifacts["question_reranker"]["preferred_variant_id"] == candidate_2.variant_id
    assert generated_kwargs["question_seed_block"] == ""
    assert generated_kwargs.get("candidate_anchor_block", "") == ""
    assert recorded_rerank["result"].preferred_variant_id == candidate_2.variant_id


def test_question_selector_structured_primary_injects_top_seed_and_shadows_rag(
    monkeypatch,
) -> None:
    generated_kwargs: dict[str, Any] = {}
    negotiated_kwargs: dict[str, Any] = {}
    recorded: dict[str, Any] = {}

    def fake_generate_question(**kwargs):
        generated_kwargs.update(kwargs)
        return _fake_generate_question(**kwargs)

    def fake_negotiate(**kwargs):
        negotiated_kwargs.update(kwargs)
        return _fake_negotiate(**kwargs)

    def fake_record(**kwargs):
        recorded.update(kwargs)

    _install_default_patches(
        monkeypatch,
        retrieval=_make_retrieval(),
        strategies=[_make_strategy()],
        skills=[_make_skill()],
    )
    monkeypatch.setattr(ask_mod, "generate_question", fake_generate_question)
    monkeypatch.setattr(ask_mod, "negotiate_contract_via_evaluator", fake_negotiate)
    monkeypatch.setattr(
        ask_mod,
        "select_question_candidates",
        lambda **_kwargs: QuestionSelectionResult(candidates=[_question_candidate()]),
    )
    monkeypatch.setattr(ask_mod, "record_question_usages", fake_record)

    out = ask_mod.ask_question_node(
        _base_state(
            runtime_config={
                "rag_mode": "hybrid",
                "rag_top_k": 2,
                "question_selector_mode": "structured_primary",
            }
        )
    )  # type: ignore[arg-type]

    artifacts = out["current_question"]["selection_artifacts"]
    assert artifacts["rag"]["mode"] == "hybrid"
    assert artifacts["question_items"][0]["injected"] is True
    assert generated_kwargs["retrieval_block"] == ""
    assert "秒杀库存读多写少" in generated_kwargs["question_seed_block"]
    assert "redis" in generated_kwargs["candidate_anchor_block"]
    assert artifacts["candidate_anchor"]["variant_id"] == (
        "system_design.cache_consistency.flash_sale_inventory"
    )
    assert generated_kwargs["contract_hints"]["question_seed"]["seed_id"] == (
        "system_design.cache_consistency"
    )
    assert negotiated_kwargs["contract_hints"]["question_seed"]["variant_id"] == (
        "system_design.cache_consistency.flash_sale_inventory"
    )
    assert recorded["question_selector_mode"] == "structured_primary"
    assert [candidate.injected for candidate in recorded["candidates"]] == [True]


def test_question_selector_structured_primary_covered_tech_role_injects_seed(
    monkeypatch,
) -> None:
    generated_kwargs: dict[str, Any] = {}
    recorded: dict[str, Any] = {}
    frontend_candidate = QuestionCandidate(
        **{
            **_question_candidate().__dict__,
            "seed_id": "system_design.frontend_performance",
            "variant_id": "system_design.frontend_performance.opening",
            "title": "Frontend performance",
            "role_tags": ["frontend_web"],
        }
    )

    def fake_generate_question(**kwargs):
        generated_kwargs.update(kwargs)
        return _fake_generate_question(**kwargs)

    def fake_record(**kwargs):
        recorded.update(kwargs)

    _install_default_patches(
        monkeypatch,
        retrieval=_make_retrieval(),
        strategies=[_make_strategy()],
        skills=[_make_skill()],
    )
    monkeypatch.setattr(ask_mod, "generate_question", fake_generate_question)
    monkeypatch.setattr(
        ask_mod,
        "select_question_candidates",
        lambda **_kwargs: QuestionSelectionResult(candidates=[frontend_candidate]),
    )
    monkeypatch.setattr(ask_mod, "record_question_usages", fake_record)

    out = ask_mod.ask_question_node(
        _base_state(
            job_spec={
                "title": "高级前端开发工程师",
                "level": "senior",
                "required_skills": ["react"],
                "interview_direction": "frontend",
            },
            runtime_config={
                "rag_mode": "hybrid",
                "rag_top_k": 2,
                "question_selector_mode": "structured_primary",
            },
        )
    )  # type: ignore[arg-type]

    artifacts = out["current_question"]["selection_artifacts"]
    assert artifacts["question_items"][0]["role_tags"] == ["frontend_web"]
    assert artifacts["question_items"][0]["injected"] is True
    assert generated_kwargs["retrieval_block"] == ""
    assert "Frontend performance" in generated_kwargs["question_seed_block"]
    assert generated_kwargs.get("candidate_anchor_block", "")
    assert [candidate.injected for candidate in recorded["candidates"]] == [True]


def test_question_selector_structured_primary_covered_business_role_injects_seed(
    monkeypatch,
) -> None:
    generated_kwargs: dict[str, Any] = {}
    recorded: dict[str, Any] = {}
    product_candidate = QuestionCandidate(
        **{
            **_question_candidate().__dict__,
            "seed_id": "user_insight.user_journey_pain_point",
            "variant_id": "user_insight.user_journey_pain_point.onboarding",
            "title": "User journey pain point",
            "dimension": "user_insight",
            "direction_tags": ["business"],
            "role_tags": ["product_manager"],
            "skill_tags": ["user_research", "journey_map"],
            "scenario_skill_tags": ["user_research", "conversion_funnel"],
        }
    )

    def fake_generate_question(**kwargs):
        generated_kwargs.update(kwargs)
        return _fake_generate_question(**kwargs)

    def fake_record(**kwargs):
        recorded.update(kwargs)

    _install_default_patches(
        monkeypatch,
        retrieval=_make_retrieval(),
        strategies=[_make_strategy()],
        skills=[_make_skill()],
    )
    monkeypatch.setattr(ask_mod, "generate_question", fake_generate_question)
    monkeypatch.setattr(
        ask_mod,
        "select_question_candidates",
        lambda **_kwargs: QuestionSelectionResult(candidates=[product_candidate]),
    )
    monkeypatch.setattr(ask_mod, "record_question_usages", fake_record)

    out = ask_mod.ask_question_node(
        _base_state(
            job_spec={
                "title": "产品经理",
                "level": "mid",
                "required_skills": ["用户洞察", "PRD", "指标"],
                "interview_direction": "product_manager",
            },
            runtime_config={
                "rag_mode": "hybrid",
                "rag_top_k": 2,
                "question_selector_mode": "structured_primary",
            },
        )
    )  # type: ignore[arg-type]

    artifacts = out["current_question"]["selection_artifacts"]
    assert artifacts["question_items"][0]["direction_tags"] == ["business"]
    assert artifacts["question_items"][0]["role_tags"] == ["product_manager"]
    assert artifacts["question_items"][0]["injected"] is True
    assert generated_kwargs["retrieval_block"] == ""
    assert "User journey pain point" in generated_kwargs["question_seed_block"]
    assert generated_kwargs.get("candidate_anchor_block", "")
    assert [candidate.injected for candidate in recorded["candidates"]] == [True]


def test_question_selector_structured_primary_service_role_injects_seed(
    monkeypatch,
) -> None:
    generated_kwargs: dict[str, Any] = {}
    recorded: dict[str, Any] = {}
    customer_success_candidate = QuestionCandidate(
        **{
            **_question_candidate().__dict__,
            "seed_id": "customer_success.renewal_risk",
            "variant_id": "customer_success.renewal_risk.opening",
            "title": "Renewal risk",
            "dimension": "customer_empathy",
            "direction_tags": ["business"],
            "role_tags": ["customer_success"],
            "skill_tags": ["renewal", "risk"],
            "scenario_skill_tags": ["renewal", "stakeholder_alignment"],
        }
    )

    def fake_generate_question(**kwargs):
        generated_kwargs.update(kwargs)
        return _fake_generate_question(**kwargs)

    def fake_record(**kwargs):
        recorded.update(kwargs)

    _install_default_patches(
        monkeypatch,
        retrieval=_make_retrieval(),
        strategies=[_make_strategy()],
        skills=[_make_skill()],
    )
    monkeypatch.setattr(ask_mod, "generate_question", fake_generate_question)
    monkeypatch.setattr(
        ask_mod,
        "select_question_candidates",
        lambda **_kwargs: QuestionSelectionResult(
            candidates=[customer_success_candidate]
        ),
    )
    monkeypatch.setattr(ask_mod, "record_question_usages", fake_record)

    out = ask_mod.ask_question_node(
        _base_state(
            job_spec={
                "title": "Customer Success Manager",
                "level": "mid",
                "required_skills": ["renewal", "risk"],
                "interview_direction": "customer_success",
            },
            runtime_config={
                "rag_mode": "hybrid",
                "rag_top_k": 2,
                "question_selector_mode": "structured_primary",
            },
            current_dimension="customer_empathy",
            dimensions=["customer_empathy"],
            dimension_status={"customer_empathy": "active"},
        )
    )  # type: ignore[arg-type]

    artifacts = out["current_question"]["selection_artifacts"]
    assert artifacts["question_items"][0]["role_tags"] == ["customer_success"]
    assert artifacts["question_items"][0]["injected"] is True
    assert generated_kwargs["retrieval_block"] == ""
    assert "Renewal risk" in generated_kwargs["question_seed_block"]
    assert generated_kwargs.get("candidate_anchor_block", "")
    assert [candidate.injected for candidate in recorded["candidates"]] == [True]


def test_question_selector_structured_primary_uncovered_role_stays_shadow(
    monkeypatch,
) -> None:
    generated_kwargs: dict[str, Any] = {}
    recorded: dict[str, Any] = {}
    finance_candidate = QuestionCandidate(
        **{
            **_question_candidate().__dict__,
            "seed_id": "finance.cashflow_forecast",
            "variant_id": "finance.cashflow_forecast.opening",
            "title": "Cashflow forecast",
            "dimension": "cashflow_management",
            "direction_tags": ["business"],
            "role_tags": ["finance"],
            "skill_tags": ["finance", "cashflow"],
            "scenario_skill_tags": ["forecast", "cashflow"],
        }
    )

    def fake_generate_question(**kwargs):
        generated_kwargs.update(kwargs)
        return _fake_generate_question(**kwargs)

    def fake_record(**kwargs):
        recorded.update(kwargs)

    _install_default_patches(
        monkeypatch,
        retrieval=_make_retrieval(),
        strategies=[_make_strategy()],
        skills=[_make_skill()],
    )
    monkeypatch.setattr(ask_mod, "generate_question", fake_generate_question)
    monkeypatch.setattr(
        ask_mod,
        "select_question_candidates",
        lambda **_kwargs: QuestionSelectionResult(candidates=[finance_candidate]),
    )
    monkeypatch.setattr(ask_mod, "record_question_usages", fake_record)

    out = ask_mod.ask_question_node(
        _base_state(
            job_spec={
                "title": "Finance Manager",
                "level": "mid",
                "required_skills": ["forecast", "cashflow"],
                "interview_direction": "finance",
            },
            runtime_config={
                "rag_mode": "hybrid",
                "rag_top_k": 2,
                "question_selector_mode": "structured_primary",
            },
            current_dimension="cashflow_management",
            dimensions=["cashflow_management"],
            dimension_status={"cashflow_management": "active"},
        )
    )  # type: ignore[arg-type]

    artifacts = out["current_question"]["selection_artifacts"]
    assert artifacts["question_items"][0]["role_tags"] == ["finance"]
    assert artifacts["question_items"][0]["injected"] is False
    assert generated_kwargs["retrieval_block"] == "[1] retrieved prompt block"
    assert generated_kwargs.get("question_seed_block", "") == ""
    assert generated_kwargs.get("candidate_anchor_block", "") == ""
    assert [candidate.injected for candidate in recorded["candidates"]] == [False]


def test_question_selector_structured_primary_falls_back_to_rag_without_hit(
    monkeypatch,
) -> None:
    generated_kwargs: dict[str, Any] = {}

    def fake_generate_question(**kwargs):
        generated_kwargs.update(kwargs)
        return _fake_generate_question(**kwargs)

    _install_default_patches(
        monkeypatch,
        retrieval=_make_retrieval(),
        strategies=[_make_strategy()],
        skills=[_make_skill()],
    )
    monkeypatch.setattr(ask_mod, "generate_question", fake_generate_question)
    monkeypatch.setattr(
        ask_mod,
        "select_question_candidates",
        lambda **_kwargs: QuestionSelectionResult(candidates=[]),
    )

    out = ask_mod.ask_question_node(
        _base_state(
            runtime_config={
                "rag_mode": "vector",
                "rag_top_k": 2,
                "question_selector_mode": "structured_primary",
            }
        )
    )  # type: ignore[arg-type]

    artifacts = out["current_question"]["selection_artifacts"]
    assert artifacts["question_items"] == []
    assert generated_kwargs["retrieval_block"] == "[1] retrieved prompt block"
    assert generated_kwargs.get("question_seed_block", "") == ""
    assert generated_kwargs.get("candidate_anchor_block", "") == ""
    assert "candidate_anchor" not in artifacts
