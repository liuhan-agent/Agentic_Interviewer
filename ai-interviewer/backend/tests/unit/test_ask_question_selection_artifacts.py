from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.engine.rag.retriever import RetrievalContext
from app.engine.rag.vectorstore import RetrievedDoc
from app.engine.workflow.nodes import ask_question as ask_mod
from app.memory import skill_store
from app.memory.skill_store import SkillEntry
from app.memory.strategy_store import StrategyEntry
from app.models.base import Base
from app.models.skill_playbook import SkillPlaybookCard
from app.services.question_selector import (
    QuestionCandidate,
    QuestionSelectionResult,
    build_question_history_selection_artifacts,
)
from app.services.session_anchor_retriever import CandidateAnchorRagResult

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
        display_name_zh="系统设计容量追问卡",
        display_description_zh="引导系统设计回答说明容量假设和失效边界。",
        priority=4,
        direction_tags=["internet_tech"],
        role_tags=["java_backend"],
        dimensions=["system_design"],
        job_levels=["senior"],
        probe_intents=["architecture_challenge"],
        failure_categories=["missing_scale_reasoning"],
        generator_moves=["Ask for one concrete failure mode."],
        watch_for=["Quantified scale argument."],
        avoid=["Accepting generic scalability claims."],
        evaluator_rubric_hints=["Credit concrete failure mode and scale bound."],
        positive_signals=["Names load, bottleneck, and mitigation."],
        negative_signals=["No failure mode."],
        score_bias_rules=["Soft positive for quantified bound."],
        evaluator_visibility=True,
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
            "display_name_zh": "系统设计容量追问卡",
            "display_description_zh": "引导系统设计回答说明容量假设和失效边界。",
            "status": "active",
            "priority": 4,
            "direction_tags": ["internet_tech"],
            "role_tags": ["java_backend"],
            "dimensions": ["system_design"],
            "job_levels": ["senior"],
            "probe_intents": ["architecture_challenge"],
            "failure_categories": ["missing_scale_reasoning"],
            "generator_moves": ["Ask for one concrete failure mode."],
            "watch_for": ["Quantified scale argument."],
            "avoid": ["Accepting generic scalability claims."],
            "evaluator_rubric_hints": [
                "Credit concrete failure mode and scale bound."
            ],
            "positive_signals": ["Names load, bottleneck, and mitigation."],
            "negative_signals": ["No failure mode."],
            "score_bias_rules": ["Soft positive for quantified bound."],
            "evaluator_visibility": True,
            "evaluator_payload": {
                "rubric_hints": [
                    "Credit concrete failure mode and scale bound."
                ],
                "positive_signals": [
                    "Names load, bottleneck, and mitigation."
                ],
                "negative_signals": ["No failure mode."],
                "score_bias_rules": [
                    "Soft positive for quantified bound."
                ],
            },
            "match_score": 42.0,
            "match_reasons": ["dimension:system_design", "role_tag:java_backend"],
            "rank": 1,
            "reward_shadow_rank": None,
            "reward_shadow_score": None,
            "reward_shadow_rank_changed": False,
            "usage_stats": None,
            "reward_shadow_reason": None,
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


def test_skill_card_ref_groups_evaluator_payload_when_visible() -> None:
    """Phase-A observability — evaluator_payload mirrors the four
    evaluator-visible frontmatter lists, but only when the card author
    has opted in via ``evaluator_visibility: true``.
    """
    entry = SkillEntry(
        path=Path("tech_production_incident_probe.md"),
        id="tech_production_incident_probe",
        name="Production Incident Probe",
        description="Probe incident answers.",
        display_name_zh="生产事故追问卡",
        display_description_zh="引导事故回答覆盖发现信号、缓解动作、根因和预防措施。",
        status="active",
        priority=7,
        direction_tags=["internet_tech"],
        role_tags=["sre"],
        dimensions=["problem_solving"],
        job_levels=["senior"],
        probe_intents=["debugging_probe"],
        failure_categories=["root_cause_missing"],
        generator_moves=["Ask for detection signal."],
        watch_for=["Separates mitigation from root cause."],
        avoid=["Accepting code-only incident answers."],
        evaluator_rubric_hints=["Credit detect / mitigate / scope / diagnose / prevent."],
        positive_signals=["Names blast radius and permanent guardrail."],
        negative_signals=["Skips blast radius."],
        score_bias_rules=["Soft positive when prevention is technical + process."],
        evaluator_visibility=True,
        body="Use when the answer touches outage or degraded behavior.",
        match_score=27.0,
        match_reasons=["dimension:problem_solving"],
    )

    ref = ask_mod._skill_card_ref(entry)

    assert ref["display_name_zh"] == "生产事故追问卡"
    assert ref["display_description_zh"] == "引导事故回答覆盖发现信号、缓解动作、根因和预防措施。"
    assert ref["evaluator_visibility"] is True
    assert ref["evaluator_payload"] == {
        "rubric_hints": ["Credit detect / mitigate / scope / diagnose / prevent."],
        "positive_signals": ["Names blast radius and permanent guardrail."],
        "negative_signals": ["Skips blast radius."],
        "score_bias_rules": [
            "Soft positive when prevention is technical + process."
        ],
    }
    # Flat fields stay populated for backward compatibility with any
    # existing reader (admin observability + downstream audits).
    assert ref["evaluator_rubric_hints"] == [
        "Credit detect / mitigate / scope / diagnose / prevent."
    ]
    assert ref["positive_signals"] == [
        "Names blast radius and permanent guardrail."
    ]
    assert ref["negative_signals"] == ["Skips blast radius."]
    assert ref["score_bias_rules"] == [
        "Soft positive when prevention is technical + process."
    ]


def test_skill_card_ref_evaluator_payload_is_none_when_card_opts_out() -> None:
    """A card without ``evaluator_visibility`` must surface
    ``evaluator_payload: None`` so admin observability can hide the
    evaluator-visible column entirely instead of recombining four list
    fields. Flat fields are still exported for any existing reader.
    """
    entry = SkillEntry(
        path=Path("internal_only_card.md"),
        id="internal_only_card",
        name="Internal Only Card",
        description="Generator hint without an evaluator surface.",
        status="active",
        priority=3,
        evaluator_rubric_hints=["Internal rubric hint that must not surface."],
        positive_signals=["Internal positive signal."],
        negative_signals=["Internal negative signal."],
        score_bias_rules=["Internal score bias rule."],
        evaluator_visibility=False,
        body="Generator only.",
    )

    ref = ask_mod._skill_card_ref(entry)

    assert ref["evaluator_visibility"] is False
    assert ref["evaluator_payload"] is None
    # Flat fields are still exported so existing readers keep their
    # contract; admin should filter by ``evaluator_payload is None`` to
    # decide whether to display the evaluator column.
    assert ref["evaluator_rubric_hints"] == [
        "Internal rubric hint that must not surface."
    ]
    assert ref["score_bias_rules"] == ["Internal score bias rule."]


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
        generator_moves=["Ask for one concrete failure mode."],
        watch_for=["Quantified scale argument."],
        avoid=["Accepting generic scalability claims."],
        evaluator_rubric_hints=["Credit concrete failure mode and scale bound."],
        positive_signals=["Names load, bottleneck, and mitigation."],
        negative_signals=["No failure mode."],
        score_bias_rules=["Soft positive for quantified bound."],
        evaluator_visibility=True,
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


def _install_db_skill_playbook(monkeypatch, card: SkillPlaybookCard) -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    session_local = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    with session_local() as sess:
        sess.add(card)
        sess.commit()

    @contextmanager
    def fake_get_session():
        with session_local() as sess:
            yield sess

    monkeypatch.setattr(skill_store, "get_session", fake_get_session, raising=False)


def _db_playbook_card() -> SkillPlaybookCard:
    return SkillPlaybookCard(
        id="db_system_design_probe",
        name="DB System Design Probe",
        description="Probe rollout and failure evidence.",
        body_markdown="DB playbook: ask for rollback blast radius and concrete metrics.",
        status="active",
        priority=9,
        direction_tags=["internet_tech"],
        role_tags=["java_backend"],
        dimensions=["system_design"],
        job_levels=["senior"],
        probe_intents=["architecture_challenge"],
        failure_categories=["missing_metrics"],
        generator_moves=["Ask for rollback blast radius."],
        watch_for=["Concrete metric and owner."],
        avoid=["Accepting vague launch safety claims."],
        evaluator_rubric_hints=["Credit rollback and blast-radius evidence."],
        positive_signals=["Names rollback trigger."],
        negative_signals=["No metric."],
        score_bias_rules=["Soft positive for measurable rollback gate."],
        evaluator_visibility=True,
        source="manual_markdown",
        content_hash="sha1:db_system_design_probe",
    )


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
    shadow_candidate = QuestionCandidate(
        **{
            **_question_candidate().__dict__,
            "reward_shadow_rank": 1,
            "reward_shadow_score": 56.5,
            "reward_shadow_rank_changed": False,
            "usage_stats": {"uses": 4, "rewarded_uses": 2},
            "reward_shadow_reason": {
                "uses": 4,
                "rewarded_uses": 2,
                "sample_confidence": 0.1,
                "metadata_rank": 1,
            },
        }
    )
    monkeypatch.setattr(
        ask_mod,
        "select_question_candidates",
        lambda **kwargs: select_kwargs.update(kwargs)
        or QuestionSelectionResult(candidates=[shadow_candidate]),
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
    assert select_kwargs["question_selector_mode"] == "structured_shadow"
    assert artifacts["question_items"][0]["reward_shadow_rank"] == 1
    assert artifacts["question_items"][0]["reward_shadow_reason"]["metadata_rank"] == 1
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
    selected_candidate = QuestionCandidate(
        **{
            **_question_candidate().__dict__,
            "reviewed_acceptance_checks": _reviewed_acceptance_checks(),
        }
    )
    monkeypatch.setattr(
        ask_mod,
        "select_question_candidates",
        lambda **_kwargs: QuestionSelectionResult(candidates=[selected_candidate]),
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
    assert "seed_version" not in generated_kwargs["contract_hints"]["question_seed"]
    assert "variant_version" not in generated_kwargs["contract_hints"]["question_seed"]
    assert (
        "reviewed_acceptance_checks"
        not in generated_kwargs["contract_hints"]["question_seed"]
    )
    assert negotiated_kwargs["contract_hints"]["question_seed"]["variant_id"] == (
        "system_design.cache_consistency.flash_sale_inventory"
    )
    assert "seed_version" not in negotiated_kwargs["contract_hints"]["question_seed"]
    assert "variant_version" not in negotiated_kwargs["contract_hints"]["question_seed"]
    assert (
        "reviewed_acceptance_checks"
        not in negotiated_kwargs["contract_hints"]["question_seed"]
    )
    assert recorded["question_selector_mode"] == "structured_primary"
    assert [candidate.injected for candidate in recorded["candidates"]] == [True]


def _ascii_question_candidate(**overrides: Any) -> QuestionCandidate:
    values = {
        **_question_candidate().__dict__,
        "seed_version": 2,
        "variant_version": 5,
        "rubric": {
            "must_cover": ["seed consistency"],
            "minimum_bar": "Seed minimum bar.",
        },
        "rubric_additions": ["seed invalidation window"],
        "expected_signals": ["seed signal"],
        "anti_patterns": ["seed anti-pattern"],
        "good_answer_hints": ["seed hint"],
    }
    values.update(overrides)
    return QuestionCandidate(**values)


def _reviewed_acceptance_checks() -> list[dict[str, Any]]:
    return [
        {
            "check_id": "reviewed:cache-consistency:core:v1",
            "source": "must_cover",
            "source_text": "seed consistency",
            "acceptance_check": "Answer defines the target consistency level.",
            "severity": "core",
            "review_status": "reviewed",
            "version": 1,
            "reviewed_seed_version": 2,
            "reviewed_variant_version": 5,
            "reviewed_by": "qa-lead",
            "reviewed_at": "2026-06-01",
        },
        {
            "check_id": "reviewed:cache-consistency:draft:v1",
            "source": "manual",
            "source_text": "draft",
            "acceptance_check": "Draft check must stay out of runtime.",
            "severity": "supporting",
            "review_status": "draft",
            "version": 1,
            "reviewed_seed_version": 2,
            "reviewed_variant_version": 5,
            "reviewed_by": "qa-lead",
            "reviewed_at": "2026-06-01",
        },
    ]


def test_locked_core_shadow_keeps_negotiated_contract_and_traces_diff(
    monkeypatch,
) -> None:
    captured_trace = _install_default_patches(
        monkeypatch,
        retrieval=_make_retrieval(),
        strategies=[_make_strategy()],
        skills=[_make_skill()],
    )

    def fake_generate_question(**kwargs):
        return {
            "question": "请说明一次缓存一致性设计。",
            "dimension": kwargs["dimension"],
            "proposed_contract": {
                "must_cover": ["llm-only"],
                "acceptance_checks": ["Answer mentions llm-only."],
                "minimum_bar": "LLM minimum bar.",
                "bar_level": "standard",
            },
        }

    def fake_negotiate(**kwargs):
        return {**kwargs["proposed_contract"], "signed_by": ["generator", "evaluator"]}

    monkeypatch.setattr(ask_mod, "generate_question", fake_generate_question)
    monkeypatch.setattr(ask_mod, "negotiate_contract_via_evaluator", fake_negotiate)
    monkeypatch.setattr(
        ask_mod,
        "select_question_candidates",
        lambda **_kwargs: QuestionSelectionResult(
            candidates=[_ascii_question_candidate()]
        ),
    )
    monkeypatch.setattr(ask_mod, "record_question_usages", lambda **_kwargs: None)

    out = ask_mod.ask_question_node(
        _base_state(
            runtime_config={
                "rag_mode": "vector",
                "question_selector_mode": "structured_primary",
            }
        )
    )  # type: ignore[arg-type]

    contract = out["current_contract"]
    assert contract["must_cover"] == ["llm-only"]
    diagnostics = captured_trace["contract_diagnostics"]
    assert diagnostics["contract_core_mode"] == "shadow"
    assert diagnostics["locked_core_present"] is True
    assert diagnostics["locked_core_applied"] is False
    assert diagnostics["locked_core_seed_ref"]["seed_version"] == 2
    assert diagnostics["locked_core_missing_from_final"] == ["seed consistency"]


def test_locked_core_mode_overrides_negotiated_core_fields(
    monkeypatch,
) -> None:
    captured_trace = _install_default_patches(
        monkeypatch,
        retrieval=_make_retrieval(),
        strategies=[_make_strategy()],
        skills=[_make_skill()],
    )

    def fake_generate_question(**kwargs):
        return {
            "question": "请说明一次缓存一致性设计。",
            "dimension": kwargs["dimension"],
            "proposed_contract": {
                "must_cover": ["llm-only"],
                "acceptance_checks": ["Answer mentions llm-only."],
                "minimum_bar": "LLM minimum bar.",
                "bar_level": "intro",
            },
        }

    def fake_negotiate(**kwargs):
        return {**kwargs["proposed_contract"], "signed_by": ["generator", "evaluator"]}

    monkeypatch.setattr(ask_mod, "generate_question", fake_generate_question)
    monkeypatch.setattr(ask_mod, "negotiate_contract_via_evaluator", fake_negotiate)
    monkeypatch.setattr(
        ask_mod,
        "select_question_candidates",
        lambda **_kwargs: QuestionSelectionResult(
            candidates=[_ascii_question_candidate()]
        ),
    )
    monkeypatch.setattr(ask_mod, "record_question_usages", lambda **_kwargs: None)

    out = ask_mod.ask_question_node(
        _base_state(
            runtime_config={
                "rag_mode": "vector",
                "question_selector_mode": "structured_primary",
                "contract_core_mode": "locked",
            },
            target_difficulty="hard",
        )
    )  # type: ignore[arg-type]

    contract = out["current_contract"]
    assert contract["must_cover"] == ["seed consistency"]
    assert contract["minimum_bar"] == "Seed minimum bar."
    assert contract["bar_level"] == "deep_probe"
    assert contract["acceptance_checks"] == ["Answer mentions llm-only."]
    assert captured_trace["contract_diagnostics"]["locked_core_applied"] is True


def test_locked_core_mode_overrides_simple_plan_generator_only_contract(
    monkeypatch,
) -> None:
    _install_default_patches(
        monkeypatch,
        retrieval=_make_retrieval(),
        strategies=[_make_strategy()],
        skills=[_make_skill()],
    )
    monkeypatch.setattr(
        ask_mod,
        "select_question_candidates",
        lambda **_kwargs: QuestionSelectionResult(
            candidates=[_ascii_question_candidate()]
        ),
    )
    monkeypatch.setattr(ask_mod, "record_question_usages", lambda **_kwargs: None)

    out = ask_mod.ask_question_node(
        _base_state(
            runtime_config={
                "rag_mode": "vector",
                "question_selector_mode": "structured_primary",
                "contract_core_mode": "locked",
            },
            selected_action={"id": "give_hint"},
        )
    )  # type: ignore[arg-type]

    contract = out["current_contract"]
    assert contract["must_cover"] == ["seed consistency"]
    assert contract["minimum_bar"] == "Seed minimum bar."
    assert contract["signed_by"] == ["generator"]


def test_compiled_acceptance_shadow_keeps_negotiated_checks_and_traces_candidates(
    monkeypatch,
) -> None:
    captured_trace = _install_default_patches(
        monkeypatch,
        retrieval=_make_retrieval(),
        strategies=[_make_strategy()],
        skills=[_make_skill()],
    )

    def fake_generate_question(**kwargs):
        return {
            "question": "请说明一次缓存一致性设计。",
            "dimension": kwargs["dimension"],
            "proposed_contract": {
                "must_cover": ["llm-only"],
                "acceptance_checks": ["Answer mentions llm-only."],
                "minimum_bar": "LLM minimum bar.",
                "bar_level": "standard",
            },
        }

    def fake_negotiate(**kwargs):
        return {**kwargs["proposed_contract"], "signed_by": ["generator", "evaluator"]}

    monkeypatch.setattr(ask_mod, "generate_question", fake_generate_question)
    monkeypatch.setattr(ask_mod, "negotiate_contract_via_evaluator", fake_negotiate)
    monkeypatch.setattr(
        ask_mod,
        "select_question_candidates",
        lambda **_kwargs: QuestionSelectionResult(
            candidates=[_ascii_question_candidate()]
        ),
    )
    monkeypatch.setattr(ask_mod, "record_question_usages", lambda **_kwargs: None)

    out = ask_mod.ask_question_node(
        _base_state(
            runtime_config={
                "rag_mode": "vector",
                "question_selector_mode": "structured_primary",
            }
        )
    )  # type: ignore[arg-type]

    assert out["current_contract"]["acceptance_checks"] == [
        "Answer mentions llm-only."
    ]
    diagnostics = captured_trace["contract_diagnostics"]
    assert diagnostics["contract_acceptance_mode"] == "shadow"
    assert diagnostics["compiled_acceptance_present"] is True
    assert diagnostics["compiled_acceptance_applied"] is False
    assert diagnostics["compiled_acceptance_append_candidates"] == [
        "Answer explicitly covers seed consistency.",
        "Answer provides evidence for seed invalidation window.",
    ]
    assert diagnostics["compiled_acceptance_missing_from_final"] == [
        "Answer explicitly covers seed consistency.",
        "Answer provides evidence for seed invalidation window.",
    ]


def test_compiled_acceptance_append_locked_adds_missing_checks(
    monkeypatch,
) -> None:
    captured_trace = _install_default_patches(
        monkeypatch,
        retrieval=_make_retrieval(),
        strategies=[_make_strategy()],
        skills=[_make_skill()],
    )

    def fake_generate_question(**kwargs):
        return {
            "question": "请说明一次缓存一致性设计。",
            "dimension": kwargs["dimension"],
            "proposed_contract": {
                "must_cover": ["llm-only"],
                "acceptance_checks": ["Answer mentions llm-only."],
                "minimum_bar": "LLM minimum bar.",
                "bar_level": "standard",
            },
        }

    def fake_negotiate(**kwargs):
        return {**kwargs["proposed_contract"], "signed_by": ["generator", "evaluator"]}

    monkeypatch.setattr(ask_mod, "generate_question", fake_generate_question)
    monkeypatch.setattr(ask_mod, "negotiate_contract_via_evaluator", fake_negotiate)
    monkeypatch.setattr(
        ask_mod,
        "select_question_candidates",
        lambda **_kwargs: QuestionSelectionResult(
            candidates=[_ascii_question_candidate()]
        ),
    )
    monkeypatch.setattr(ask_mod, "record_question_usages", lambda **_kwargs: None)

    out = ask_mod.ask_question_node(
        _base_state(
            runtime_config={
                "rag_mode": "vector",
                "question_selector_mode": "structured_primary",
                "contract_acceptance_mode": "append_locked",
            }
        )
    )  # type: ignore[arg-type]

    assert out["current_contract"]["acceptance_checks"] == [
        "Answer mentions llm-only.",
        "Answer explicitly covers seed consistency.",
        "Answer provides evidence for seed invalidation window.",
    ]
    items = out["current_contract"]["acceptance_check_items"]
    assert [item["text"] for item in items] == out["current_contract"][
        "acceptance_checks"
    ]
    assert [item["source"] for item in items] == [
        "adaptive_context",
        "compiled_fallback",
        "compiled_fallback",
    ]
    diagnostics = captured_trace["contract_diagnostics"]
    assert diagnostics["contract_acceptance_mode"] == "append_locked"
    assert diagnostics["compiled_acceptance_applied"] is True
    assert diagnostics["acceptance_check_items_present"] is True
    assert diagnostics["acceptance_check_projection_match"] is True
    assert diagnostics["acceptance_check_item_source_counts"] == {
        "adaptive_context": 1,
        "compiled_fallback": 2,
    }
    assert diagnostics["compiled_acceptance_append_candidates"] == [
        "Answer explicitly covers seed consistency.",
        "Answer provides evidence for seed invalidation window.",
    ]


def test_compiled_acceptance_append_locked_supports_generator_only_plan(
    monkeypatch,
) -> None:
    _install_default_patches(
        monkeypatch,
        retrieval=_make_retrieval(),
        strategies=[_make_strategy()],
        skills=[_make_skill()],
    )

    def fake_generate_question(**kwargs):
        return {
            "question": "请说明一次缓存一致性设计。",
            "dimension": kwargs["dimension"],
            "proposed_contract": {
                "must_cover": ["llm-only"],
                "acceptance_checks": ["Answer mentions llm-only."],
                "minimum_bar": "LLM minimum bar.",
                "bar_level": "standard",
            },
        }

    monkeypatch.setattr(ask_mod, "generate_question", fake_generate_question)
    monkeypatch.setattr(
        ask_mod,
        "select_question_candidates",
        lambda **_kwargs: QuestionSelectionResult(
            candidates=[_ascii_question_candidate()]
        ),
    )
    monkeypatch.setattr(ask_mod, "record_question_usages", lambda **_kwargs: None)

    out = ask_mod.ask_question_node(
        _base_state(
            runtime_config={
                "rag_mode": "vector",
                "question_selector_mode": "structured_primary",
                "contract_acceptance_mode": "append_locked",
            },
            selected_action={"id": "give_hint"},
        )
    )  # type: ignore[arg-type]

    assert out["current_contract"]["signed_by"] == ["generator"]
    assert "Answer explicitly covers seed consistency." in out["current_contract"][
        "acceptance_checks"
    ]
    assert "Answer provides evidence for seed invalidation window." in out[
        "current_contract"
    ]["acceptance_checks"]
    assert [item["text"] for item in out["current_contract"]["acceptance_check_items"]] == (
        out["current_contract"]["acceptance_checks"]
    )
    assert "adaptive_context" in {
        item["source"] for item in out["current_contract"]["acceptance_check_items"]
    }
    assert "compiled_fallback" in {
        item["source"] for item in out["current_contract"]["acceptance_check_items"]
    }


def test_compiled_acceptance_mode_off_suppresses_compiled_diagnostics(
    monkeypatch,
) -> None:
    captured_trace = _install_default_patches(
        monkeypatch,
        retrieval=_make_retrieval(),
        strategies=[_make_strategy()],
        skills=[_make_skill()],
    )
    monkeypatch.setattr(
        ask_mod,
        "select_question_candidates",
        lambda **_kwargs: QuestionSelectionResult(
            candidates=[_ascii_question_candidate()]
        ),
    )
    monkeypatch.setattr(ask_mod, "record_question_usages", lambda **_kwargs: None)

    ask_mod.ask_question_node(
        _base_state(
            runtime_config={
                "rag_mode": "vector",
                "question_selector_mode": "structured_primary",
                "contract_acceptance_mode": "off",
            }
        )
    )  # type: ignore[arg-type]

    diagnostics = captured_trace["contract_diagnostics"]
    assert diagnostics["contract_acceptance_mode"] == "off"
    assert diagnostics["compiled_acceptance_present"] is False
    assert diagnostics["compiled_acceptance_checks"] == []
    assert diagnostics["compiled_acceptance_warnings"] == []


def test_compiled_acceptance_invalid_mode_falls_back_in_trace(
    monkeypatch,
) -> None:
    captured_trace = _install_default_patches(
        monkeypatch,
        retrieval=_make_retrieval(),
        strategies=[_make_strategy()],
        skills=[_make_skill()],
    )
    monkeypatch.setattr(
        ask_mod,
        "select_question_candidates",
        lambda **_kwargs: QuestionSelectionResult(
            candidates=[_ascii_question_candidate()]
        ),
    )
    monkeypatch.setattr(ask_mod, "record_question_usages", lambda **_kwargs: None)

    ask_mod.ask_question_node(
        _base_state(
            runtime_config={
                "rag_mode": "vector",
                "question_selector_mode": "structured_primary",
                "contract_acceptance_mode": "surprise",
            }
        )
    )  # type: ignore[arg-type]

    diagnostics = captured_trace["contract_diagnostics"]
    assert diagnostics["contract_acceptance_mode"] == "shadow"
    assert (
        "invalid_acceptance_mode_fallback"
        in diagnostics["compiled_acceptance_warnings"]
    )


def test_reviewed_acceptance_shadow_keeps_negotiated_checks_and_traces_reviewed(
    monkeypatch,
) -> None:
    captured_trace = _install_default_patches(
        monkeypatch,
        retrieval=_make_retrieval(),
        strategies=[_make_strategy()],
        skills=[_make_skill()],
    )

    def fake_generate_question(**kwargs):
        return {
            "question": "请说明一次缓存一致性设计。",
            "dimension": kwargs["dimension"],
            "proposed_contract": {
                "must_cover": ["llm-only"],
                "acceptance_checks": ["Answer mentions llm-only."],
                "minimum_bar": "LLM minimum bar.",
                "bar_level": "standard",
            },
        }

    def fake_negotiate(**kwargs):
        return {**kwargs["proposed_contract"], "signed_by": ["generator", "evaluator"]}

    monkeypatch.setattr(ask_mod, "generate_question", fake_generate_question)
    monkeypatch.setattr(ask_mod, "negotiate_contract_via_evaluator", fake_negotiate)
    monkeypatch.setattr(
        ask_mod,
        "select_question_candidates",
        lambda **_kwargs: QuestionSelectionResult(
            candidates=[
                _ascii_question_candidate(
                    reviewed_acceptance_checks=_reviewed_acceptance_checks()
                )
            ]
        ),
    )
    monkeypatch.setattr(ask_mod, "record_question_usages", lambda **_kwargs: None)

    out = ask_mod.ask_question_node(
        _base_state(
            runtime_config={
                "rag_mode": "vector",
                "question_selector_mode": "structured_primary",
                "contract_acceptance_mode": "reviewed_shadow",
            }
        )
    )  # type: ignore[arg-type]

    assert out["current_contract"]["acceptance_checks"] == [
        "Answer mentions llm-only."
    ]
    diagnostics = captured_trace["contract_diagnostics"]
    assert diagnostics["reviewed_acceptance_mode"] == "reviewed_shadow"
    assert diagnostics["reviewed_acceptance_present"] is True
    assert diagnostics["reviewed_acceptance_source"] == "reviewed"
    assert diagnostics["reviewed_acceptance_applied"] is False
    assert diagnostics["reviewed_acceptance_missing_from_final"] == [
        "Answer defines the target consistency level."
    ]
    assert diagnostics["reviewed_acceptance_checks"][0]["check_id"] == (
        "reviewed:cache-consistency:core:v1"
    )
    assert "Draft check must stay out of runtime." not in [
        check["acceptance_check"]
        for check in diagnostics["reviewed_acceptance_checks"]
    ]


def test_reviewed_acceptance_append_adds_reviewed_checks(
    monkeypatch,
) -> None:
    captured_trace = _install_default_patches(
        monkeypatch,
        retrieval=_make_retrieval(),
        strategies=[_make_strategy()],
        skills=[_make_skill()],
    )

    def fake_generate_question(**kwargs):
        return {
            "question": "请说明一次缓存一致性设计。",
            "dimension": kwargs["dimension"],
            "proposed_contract": {
                "must_cover": ["llm-only"],
                "acceptance_checks": ["Answer mentions llm-only."],
                "minimum_bar": "LLM minimum bar.",
                "bar_level": "standard",
            },
        }

    def fake_negotiate(**kwargs):
        return {**kwargs["proposed_contract"], "signed_by": ["generator", "evaluator"]}

    monkeypatch.setattr(ask_mod, "generate_question", fake_generate_question)
    monkeypatch.setattr(ask_mod, "negotiate_contract_via_evaluator", fake_negotiate)
    monkeypatch.setattr(
        ask_mod,
        "select_question_candidates",
        lambda **_kwargs: QuestionSelectionResult(
            candidates=[
                _ascii_question_candidate(
                    reviewed_acceptance_checks=_reviewed_acceptance_checks()
                )
            ]
        ),
    )
    monkeypatch.setattr(ask_mod, "record_question_usages", lambda **_kwargs: None)

    out = ask_mod.ask_question_node(
        _base_state(
            runtime_config={
                "rag_mode": "vector",
                "question_selector_mode": "structured_primary",
                "contract_acceptance_mode": "reviewed_append",
            }
        )
    )  # type: ignore[arg-type]

    assert out["current_contract"]["acceptance_checks"] == [
        "Answer mentions llm-only.",
        "Answer defines the target consistency level.",
    ]
    items = out["current_contract"]["acceptance_check_items"]
    assert [item["text"] for item in items] == out["current_contract"][
        "acceptance_checks"
    ]
    assert [item["source"] for item in items] == [
        "adaptive_context",
        "reviewed",
    ]
    assert [item["severity"] for item in items] == ["supporting", "core"]
    diagnostics = captured_trace["contract_diagnostics"]
    assert diagnostics["reviewed_acceptance_source"] == "reviewed"
    assert diagnostics["reviewed_acceptance_applied"] is True
    assert diagnostics["reviewed_acceptance_missing_from_final"] == []
    assert diagnostics["acceptance_check_projection_match"] is True
    assert diagnostics["acceptance_check_item_source_counts"] == {
        "adaptive_context": 1,
        "reviewed": 1,
    }


def test_reviewed_acceptance_append_preserves_reviewed_metadata_when_text_covered(
    monkeypatch,
) -> None:
    captured_trace = _install_default_patches(
        monkeypatch,
        retrieval=_make_retrieval(),
        strategies=[_make_strategy()],
        skills=[_make_skill()],
    )

    def fake_generate_question(**kwargs):
        return {
            "question": "璇疯鏄庝竴娆＄紦瀛樹竴鑷存€ц璁°€?",
            "dimension": kwargs["dimension"],
            "proposed_contract": {
                "must_cover": ["llm consistency"],
                "acceptance_checks": ["Answer defines the target consistency level."],
                "minimum_bar": "LLM minimum bar.",
                "bar_level": "standard",
            },
        }

    def fake_negotiate(**kwargs):
        return {**kwargs["proposed_contract"], "signed_by": ["generator", "evaluator"]}

    monkeypatch.setattr(ask_mod, "generate_question", fake_generate_question)
    monkeypatch.setattr(ask_mod, "negotiate_contract_via_evaluator", fake_negotiate)
    monkeypatch.setattr(
        ask_mod,
        "select_question_candidates",
        lambda **_kwargs: QuestionSelectionResult(
            candidates=[
                _ascii_question_candidate(
                    reviewed_acceptance_checks=_reviewed_acceptance_checks()
                )
            ]
        ),
    )
    monkeypatch.setattr(ask_mod, "record_question_usages", lambda **_kwargs: None)

    out = ask_mod.ask_question_node(
        _base_state(
            runtime_config={
                "rag_mode": "vector",
                "question_selector_mode": "structured_primary",
                "contract_acceptance_mode": "reviewed_append",
            }
        )
    )  # type: ignore[arg-type]

    assert out["current_contract"]["acceptance_checks"] == [
        "Answer defines the target consistency level."
    ]
    item = out["current_contract"]["acceptance_check_items"][0]
    assert item["check_id"] == "reviewed:cache-consistency:core:v1"
    assert item["text"] == "Answer defines the target consistency level."
    assert item["source"] == "reviewed"
    assert item["severity"] == "core"
    assert item["source_text"] == "seed consistency"
    assert item["seed_ref"] == {
        "seed_id": "system_design.cache_consistency",
        "variant_id": "system_design.cache_consistency.flash_sale_inventory",
        "seed_version": 2,
        "variant_version": 5,
    }
    assert item["origin"] == "question_variant"
    assert item["metadata"]["criterion_source"] == "must_cover"
    assert item["metadata"]["review_status"] == "reviewed"
    assert item["metadata"]["reviewed_seed_version"] == 2
    assert item["metadata"]["reviewed_variant_version"] == 5
    diagnostics = captured_trace["contract_diagnostics"]
    assert diagnostics["reviewed_acceptance_source"] == "reviewed"
    assert diagnostics["reviewed_acceptance_applied"] is True
    assert diagnostics["reviewed_acceptance_missing_from_final"] == []
    assert diagnostics["reviewed_acceptance_missing_source_metadata"] == []
    assert diagnostics["acceptance_check_item_source_counts"] == {"reviewed": 1}
    assert diagnostics["acceptance_check_item_severity_counts"] == {"core": 1}


def test_reviewed_acceptance_modes_fallback_to_compiled_when_reviewed_missing(
    monkeypatch,
) -> None:
    captured_trace = _install_default_patches(
        monkeypatch,
        retrieval=_make_retrieval(),
        strategies=[_make_strategy()],
        skills=[_make_skill()],
    )
    monkeypatch.setattr(
        ask_mod,
        "select_question_candidates",
        lambda **_kwargs: QuestionSelectionResult(
            candidates=[_ascii_question_candidate()]
        ),
    )
    monkeypatch.setattr(ask_mod, "record_question_usages", lambda **_kwargs: None)

    out = ask_mod.ask_question_node(
        _base_state(
            runtime_config={
                "rag_mode": "vector",
                "question_selector_mode": "structured_primary",
                "contract_acceptance_mode": "reviewed_append",
            },
            selected_action={"id": "give_hint"},
        )
    )  # type: ignore[arg-type]

    assert out["current_contract"]["signed_by"] == ["generator"]
    assert "Answer explicitly covers seed consistency." in out["current_contract"][
        "acceptance_checks"
    ]
    assert "compiled_fallback" in {
        item["source"] for item in out["current_contract"]["acceptance_check_items"]
    }
    diagnostics = captured_trace["contract_diagnostics"]
    assert diagnostics["reviewed_acceptance_source"] == "compiled_fallback"
    assert (
        "reviewed_acceptance_missing_fallback_compiled"
        in diagnostics["reviewed_acceptance_warnings"]
    )


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


def test_structured_primary_seed_hit_injects_db_playbook_and_keeps_rag_shadow(
    monkeypatch,
) -> None:
    generated_kwargs: dict[str, Any] = {}
    recorded: dict[str, Any] = {}
    captured_trace: dict[str, Any] = {}

    def fake_generate_question(**kwargs):
        generated_kwargs.update(kwargs)
        return _fake_generate_question(**kwargs)

    def fake_record(**kwargs):
        recorded.update(kwargs)

    _install_db_skill_playbook(monkeypatch, _db_playbook_card())
    monkeypatch.setattr(ask_mod, "retrieve_for_question", lambda **_kw: _make_retrieval())
    monkeypatch.setattr(ask_mod, "retrieve_strategies", lambda **_kw: [_make_strategy()])
    monkeypatch.setattr(
        ask_mod,
        "format_strategies_for_prompt",
        lambda entries: "\n".join(entry.body for entry in entries),
    )
    monkeypatch.setattr(
        ask_mod,
        "build_generator_avoid_patterns",
        lambda **_kw: "avoid shallow evidence",
    )
    monkeypatch.setattr(ask_mod, "generate_question", fake_generate_question)
    monkeypatch.setattr(ask_mod, "negotiate_contract_via_evaluator", _fake_negotiate)
    monkeypatch.setattr(
        ask_mod,
        "select_question_candidates",
        lambda **_kw: QuestionSelectionResult(candidates=[_question_candidate()]),
    )
    monkeypatch.setattr(ask_mod, "record_question_usages", fake_record)
    monkeypatch.setattr(
        ask_mod,
        "get_settings",
        lambda: SimpleNamespace(
            enable_llm_memory_selector=False,
            enable_skill_injection=True,
            skill_retrieval_limit=3,
            skill_playbook_backend="db",
            enable_generator_avoid_patterns=True,
            drift_feedback_top_n=3,
            drift_feedback_min_support=2,
            enable_question_fit_profile=True,
            enable_question_reranker_shadow=False,
            question_reranker_timeout_ms=4000,
            question_primary_role_tags=list(_COVERED_PRIMARY_ROLE_TAGS),
        ),
    )

    class _Tracer:
        def trace_node_event(self, _state, *, node, payload, **_kwargs):
            if node == "ask_question":
                captured_trace.update(payload)

    monkeypatch.setattr(ask_mod, "get_tracer", lambda: _Tracer())

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
    assert captured_trace["selection_artifacts"] == artifacts
    assert artifacts["rag"]["mode"] == "hybrid"
    assert artifacts["rag"]["empty"] is False
    assert artifacts["question_items"][0]["injected"] is True
    assert artifacts["skills"]["refs"][0]["id"] == "db_system_design_probe"
    assert generated_kwargs["retrieval_block"] == ""
    assert "Dimension: system_design" in generated_kwargs["question_seed_block"]
    assert "redis" in generated_kwargs["candidate_anchor_block"]
    assert "Generator moves:" in generated_kwargs["skill_block"]
    assert "Ask for rollback blast radius." in generated_kwargs["skill_block"]
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


def test_structured_primary_seed_miss_still_injects_db_playbook_with_rag_fallback(
    monkeypatch,
) -> None:
    generated_kwargs: dict[str, Any] = {}

    def fake_generate_question(**kwargs):
        generated_kwargs.update(kwargs)
        return _fake_generate_question(**kwargs)

    _install_db_skill_playbook(monkeypatch, _db_playbook_card())
    monkeypatch.setattr(ask_mod, "retrieve_for_question", lambda **_kw: _make_retrieval())
    monkeypatch.setattr(ask_mod, "retrieve_strategies", lambda **_kw: [_make_strategy()])
    monkeypatch.setattr(
        ask_mod,
        "format_strategies_for_prompt",
        lambda entries: "\n".join(entry.body for entry in entries),
    )
    monkeypatch.setattr(
        ask_mod,
        "build_generator_avoid_patterns",
        lambda **_kw: "avoid shallow evidence",
    )
    monkeypatch.setattr(ask_mod, "generate_question", fake_generate_question)
    monkeypatch.setattr(ask_mod, "negotiate_contract_via_evaluator", _fake_negotiate)
    monkeypatch.setattr(
        ask_mod,
        "select_question_candidates",
        lambda **_kw: QuestionSelectionResult(candidates=[]),
    )
    monkeypatch.setattr(
        ask_mod,
        "get_settings",
        lambda: SimpleNamespace(
            enable_llm_memory_selector=False,
            enable_skill_injection=True,
            skill_retrieval_limit=3,
            skill_playbook_backend="db",
            enable_generator_avoid_patterns=True,
            drift_feedback_top_n=3,
            drift_feedback_min_support=2,
            enable_question_fit_profile=True,
            enable_question_reranker_shadow=False,
            question_reranker_timeout_ms=4000,
            question_primary_role_tags=list(_COVERED_PRIMARY_ROLE_TAGS),
        ),
    )

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
    assert artifacts["question_items"] == []
    assert artifacts["skills"]["refs"][0]["id"] == "db_system_design_probe"
    assert generated_kwargs["retrieval_block"] == "[1] retrieved prompt block"
    assert generated_kwargs.get("question_seed_block", "") == ""
    assert generated_kwargs.get("candidate_anchor_block", "") == ""
    assert "Generator moves:" in generated_kwargs["skill_block"]
    assert "Ask for rollback blast radius." in generated_kwargs["skill_block"]


def test_generator_context_slot_order_baseline(monkeypatch) -> None:
    captured_keys: list[str] = []

    def fake_generate_question(**kwargs):
        captured_keys.extend(kwargs.keys())
        return _fake_generate_question(**kwargs)

    monkeypatch.setattr(ask_mod, "generate_question", fake_generate_question)

    ask_mod._step_draft_question(
        _base_state(),
        {
            "dimension": "system_design",
            "retrieval_block": "knowledge slot",
            "question_seed_block": "seed slot",
            "candidate_anchor_block": "rule anchor slot",
            "resume_rag_block": "resume semantic slot",
            "self_intro_rag_block": "self intro semantic slot",
            "strategy_block": "strategy slot",
            "skill_block": "skill slot",
            "avoid_patterns": "avoid slot",
            "resume_anchor": {
                "project_name": "Smart Learning Coupon Guard",
                "tech_stack": ["Redis"],
            },
            "target_skills": ["Redis"],
            "probe_intent": None,
            "contract_hints": {},
        },
    )

    expected_relative_order = [
        "retrieval_block",
        "question_seed_block",
        "candidate_anchor_block",
        "resume_rag_block",
        "self_intro_rag_block",
        "strategy_block",
        "skill_block",
        "avoid_patterns_block",
        "resume_anchor",
    ]
    positions = [captured_keys.index(key) for key in expected_relative_order]
    assert positions == sorted(positions)


def test_retrieval_block_for_prompt_returns_empty_on_seed_hit() -> None:
    ctx = {"structured_primary_seed_hit": True, "retrieval_block": "something"}
    assert ask_mod._retrieval_block_for_prompt(ctx) == ""


def test_retrieval_block_for_prompt_returns_block_without_seed_hit() -> None:
    ctx = {"structured_primary_seed_hit": False, "retrieval_block": "knowledge body"}
    assert ask_mod._retrieval_block_for_prompt(ctx) == "knowledge body"


def test_prompt_slots_record_final_generator_inputs_and_truncation() -> None:
    ctx = {
        "structured_primary_seed_hit": True,
        "retrieval_block": "legacy knowledge that should be skipped",
        "question_seed_block": "Seed: Cache Consistency",
        "candidate_anchor_block": "Candidate project: Coupon Guard",
        "resume_rag_block": "[resume] " + ("Redis " * 20),
        "self_intro_rag_block": "[self_intro] Lua atomic deduction",
        "strategy_block": "(no relevant strategy memories)",
        "skill_block": "(no relevant interview skills)",
    }

    slots = ask_mod._prompt_slots_for_trace(ctx, text_limit=24)
    by_label = {slot["prompt_label"]: slot for slot in slots}

    retrieved = by_label["RETRIEVED_KNOWLEDGE"]
    assert retrieved["source_key"] == "retrieval_block"
    assert retrieved["legacy"] is True
    assert retrieved["text"] == ""
    assert retrieved["injected"] is False
    assert retrieved["empty_reason"] == "structured_question_seed_hit"

    resume = by_label["CANDIDATE_RESUME_RAG"]
    assert resume["chars"] > len(resume["text"])
    assert resume["truncated"] is False
    assert resume["prompt_truncated"] is False
    assert resume["trace_text_truncated"] is True
    assert resume["text"] == ("[resume] " + ("Redis " * 20))[:24]
    assert resume["injected"] is True

    assert by_label["STRATEGY_MEMORY"]["injected"] is False
    assert by_label["STRATEGY_MEMORY"]["empty_reason"] == "no_relevant_strategy_memories"
    assert by_label["INTERVIEW_SKILLS"]["empty_reason"] == "no_relevant_interview_skills"


def test_ask_question_records_soft_followup_context_shadow_without_prompt_injection(
    monkeypatch,
) -> None:
    captured_trace = _install_default_patches(
        monkeypatch,
        retrieval=_make_retrieval(docs=[]),
        strategies=[],
        skills=[],
    )
    generator_kwargs: dict[str, Any] = {}

    def fake_generate_question(**kwargs):
        generator_kwargs.update(kwargs)
        return _fake_generate_question(**kwargs)

    monkeypatch.setattr(ask_mod, "generate_question", fake_generate_question)

    quality_hint = {
        "hint_id": "soft_followup:quality",
        "suggestion_id": "soft_gap:quality",
        "source": "reviewed_supporting",
        "intent": "probe_quality_gap",
        "check_id": "reviewed:support:retry_boundary",
        "verdict": "partial",
        "reason": "partial",
        "text": "Ask for retry boundary details.",
        "focus": "Probe quality gap without treating it as a hard gate: Ask for retry boundary details.",
        "evidence_count": 1,
    }
    context_hint = {
        "hint_id": "soft_followup:context",
        "suggestion_id": "soft_gap:context",
        "source": "adaptive_context",
        "intent": "probe_context_gap",
        "check_id": "adaptive:resume:payment-project",
        "verdict": "no",
        "reason": "no",
        "text": "Tie the answer to the payment migration project.",
        "focus": "Probe context gap without overriding reviewed core: Tie the answer to the payment migration project.",
        "evidence_count": 0,
    }

    out = ask_mod.ask_question_node(
        _base_state(
            turn_idx=2,
            formal_turn_idx=1,
            runtime_config={
                "rag_mode": "vector",
                "rag_top_k": 2,
                "soft_followup_prompt_mode": "shadow",
            },
            selected_action={"id": "plan_deep_probe", "plan_template": "deep_probe"},
            qa_history=[
                {
                    "turn_idx": 1,
                    "dimension": "system_design",
                    "question": "How would you handle retries?",
                    "answer": "I would retry.",
                    "evaluation": {
                        "passed": False,
                        "recommended_next": "refine",
                        "soft_followup_hints": {
                            "present": True,
                            "mode": "shadow",
                            "applied": False,
                            "source": "soft_gap_training_suggestions",
                            "quality_hints": [quality_hint],
                            "context_hints": [context_hint],
                            "priority_order": [
                                "soft_followup:quality",
                                "soft_followup:context",
                            ],
                            "counts": {"quality": 1, "context": 1, "total": 2},
                        },
                    },
                }
            ],
        )
    )  # type: ignore[arg-type]

    shadow = captured_trace["current_gaps_shadow"]["soft_followup_hints"]
    assert shadow["present"] is True
    assert shadow["mode"] == "shadow"
    assert shadow["applied"] is False
    assert shadow["not_applied_reason"] == "prompt_shadow"
    assert shadow["selected_hint_ids"] == [
        "soft_followup:quality",
        "soft_followup:context",
    ]
    assert shadow["quality_hints"][0]["check_id"] == "reviewed:support:retry_boundary"
    assert shadow["context_hints"][0]["source"] == "adaptive_context"
    assert shadow["constraints"]["do_not_override_seed"] is True

    artifacts = out["current_question"]["selection_artifacts"]
    assert artifacts["current_gaps"]["soft_followup_hints"] == shadow
    assert captured_trace["selection_artifacts"] == artifacts
    assert captured_trace["history_context"]["current_gaps_shadow"] == {
        "soft_followup_hints": shadow
    }

    prompt_text = "\n".join(
        str(slot.get("text") or "") for slot in captured_trace["prompt_slots"]
    )
    assert "Ask for retry boundary details." not in prompt_text
    assert "payment migration project" not in prompt_text
    assert "Ask for retry boundary details." not in str(
        generator_kwargs.get("history_section_override") or ""
    )
    assert len(out["current_contract"]["acceptance_checks"]) == 1
    assert out["current_contract"]["signed_by"] == ["generator", "evaluator"]


def test_ask_question_defaults_soft_followup_prompt_mode_off(monkeypatch) -> None:
    captured_trace = _install_default_patches(
        monkeypatch,
        retrieval=_make_retrieval(docs=[]),
        strategies=[],
        skills=[],
    )

    ask_mod.ask_question_node(
        _base_state(
            turn_idx=2,
            formal_turn_idx=1,
            selected_action={"id": "plan_deep_probe", "plan_template": "deep_probe"},
            qa_history=[
                {
                    "turn_idx": 1,
                    "dimension": "system_design",
                    "evaluation": {
                        "soft_followup_hints": {
                            "present": True,
                            "mode": "shadow",
                            "applied": False,
                            "quality_hints": [
                                {
                                    "hint_id": "soft_followup:quality",
                                    "text": "Ask for retry boundary details.",
                                }
                            ],
                            "context_hints": [],
                            "priority_order": ["soft_followup:quality"],
                            "counts": {"quality": 1, "context": 0, "total": 1},
                        }
                    },
                }
            ],
        )
    )  # type: ignore[arg-type]

    shadow = captured_trace["current_gaps_shadow"]["soft_followup_hints"]
    assert shadow["mode"] == "off"
    assert shadow["present"] is False
    assert shadow["applied"] is False
    assert shadow["not_applied_reason"] == "disabled"
    assert "Ask for retry boundary details." not in "\n".join(
        str(slot.get("text") or "") for slot in captured_trace["prompt_slots"]
    )


def test_ask_question_advisory_mode_injects_soft_hints_into_current_gaps_only(
    monkeypatch,
) -> None:
    captured_trace = _install_default_patches(
        monkeypatch,
        retrieval=_make_retrieval(docs=[]),
        strategies=[],
        skills=[],
    )
    generator_kwargs: dict[str, Any] = {}

    def fake_generate_question(**kwargs):
        generator_kwargs.update(kwargs)
        return _fake_generate_question(**kwargs)

    monkeypatch.setattr(ask_mod, "generate_question", fake_generate_question)

    out = ask_mod.ask_question_node(
        _base_state(
            turn_idx=2,
            formal_turn_idx=1,
            runtime_config={
                "rag_mode": "vector",
                "rag_top_k": 2,
                "soft_followup_prompt_mode": "advisory",
            },
            selected_action={"id": "plan_deep_probe", "plan_template": "deep_probe"},
            qa_history=[
                {
                    "turn_idx": 1,
                    "dimension": "system_design",
                    "question": "How would you handle retries?",
                    "answer": "I would retry.",
                    "evaluation": {
                        "passed": False,
                        "recommended_next": "refine",
                        "soft_followup_hints": {
                            "present": True,
                            "mode": "shadow",
                            "applied": False,
                            "source": "soft_gap_training_suggestions",
                            "quality_hints": [
                                {
                                    "hint_id": "soft_followup:quality",
                                    "suggestion_id": "soft_gap:quality",
                                    "source": "reviewed_supporting",
                                    "intent": "probe_quality_gap",
                                    "check_id": "reviewed:support:retry_boundary",
                                    "verdict": "partial",
                                    "reason": "partial",
                                    "text": "Ask for retry boundary details.",
                                    "focus": "Ask for retry boundary details.",
                                }
                            ],
                            "context_hints": [
                                {
                                    "hint_id": "soft_followup:context",
                                    "suggestion_id": "soft_gap:context",
                                    "source": "adaptive_context",
                                    "intent": "probe_context_gap",
                                    "check_id": "adaptive:resume:payment-project",
                                    "verdict": "no",
                                    "reason": "no",
                                    "text": "Tie the answer to the payment migration project.",
                                    "focus": "Tie the answer to the payment migration project.",
                                }
                            ],
                            "priority_order": [
                                "soft_followup:quality",
                                "soft_followup:context",
                            ],
                            "counts": {"quality": 1, "context": 1, "total": 2},
                        },
                    },
                }
            ],
        )
    )  # type: ignore[arg-type]

    shadow = captured_trace["current_gaps_shadow"]["soft_followup_hints"]
    assert shadow["mode"] == "advisory"
    assert shadow["present"] is True
    assert shadow["applied"] is True
    assert shadow["applied_to_slot"] == "CURRENT_GAPS"
    assert shadow["not_applied_reason"] is None
    assert shadow["selected_hint_ids"] == [
        "soft_followup:quality",
        "soft_followup:context",
    ]
    assert captured_trace["soft_followup_prompt_mode"] == "advisory"
    artifacts = out["current_question"]["selection_artifacts"]
    assert artifacts["current_gaps"]["soft_followup_hints"] == shadow

    current_gaps_slot = next(
        slot
        for slot in captured_trace["prompt_slots"]
        if slot["prompt_label"] == "CURRENT_GAPS"
    )
    assert isinstance(current_gaps_slot["value"], dict)
    assert current_gaps_slot["value"]["soft_followup_hints"]["mode"] == "advisory"
    assert current_gaps_slot["value"]["soft_followup_hints"]["advisory_only"] is True
    assert "Ask for retry boundary details." in current_gaps_slot["text"]
    assert "Tie the answer to the payment migration project." in current_gaps_slot["text"]
    assert "Ask for retry boundary details." in str(
        generator_kwargs.get("history_section_override") or ""
    )
    assert out["current_contract"]["signed_by"] == ["generator", "evaluator"]


def test_ask_question_advisory_topic_affinity_rejects_cross_seed_hints(
    monkeypatch,
) -> None:
    captured_trace = _install_default_patches(
        monkeypatch,
        retrieval=_make_retrieval(docs=[]),
        strategies=[],
        skills=[],
    )
    generator_kwargs: dict[str, Any] = {}

    def fake_generate_question(**kwargs):
        generator_kwargs.update(kwargs)
        return _fake_generate_question(**kwargs)

    monkeypatch.setattr(ask_mod, "generate_question", fake_generate_question)
    monkeypatch.setattr(
        ask_mod,
        "select_question_candidates",
        lambda **_kwargs: QuestionSelectionResult(
            candidates=[
                _ascii_question_candidate(
                    seed_id="coding_quality.java_service_testability",
                    variant_id=(
                        "coding_quality.java_service_testability."
                        "transaction_service_boundary"
                    ),
                    dimension="coding_quality",
                )
            ]
        ),
    )
    monkeypatch.setattr(ask_mod, "record_question_usages", lambda **_kwargs: None)

    ask_mod.ask_question_node(
        _base_state(
            current_dimension="coding_quality",
            dimensions=["coding_quality"],
            dimension_status={"coding_quality": "active"},
            turn_idx=9,
            formal_turn_idx=8,
            runtime_config={
                "rag_mode": "vector",
                "rag_top_k": 2,
                "question_selector_mode": "structured_primary",
                "soft_followup_prompt_mode": "advisory",
            },
            selected_action={"id": "plan_deep_probe", "plan_template": "deep_probe"},
            qa_history=[
                {
                    "turn_idx": 8,
                    "dimension": "coding_quality",
                    "selection_artifacts": {
                        "question_items": [
                            {
                                "seed_id": (
                                    "coding_quality.java_api_contract_idempotency"
                                ),
                                "variant_id": (
                                    "coding_quality.java_api_contract_idempotency."
                                    "payment_create_retry"
                                ),
                                "rank": 1,
                                "injected": True,
                            }
                        ]
                    },
                    "evaluation": {
                        "soft_followup_hints": {
                            "present": True,
                            "mode": "shadow",
                            "applied": False,
                            "quality_hints": [
                                {
                                    "hint_id": "soft_followup:quality",
                                    "source": "reviewed_supporting",
                                    "intent": "probe_quality_gap",
                                    "check_id": "reviewed:cq:idempotency",
                                    "text": "Ask for idempotency key scope.",
                                    "focus": "Ask for idempotency key scope.",
                                    "verdict": "partial",
                                }
                            ],
                            "context_hints": [],
                            "priority_order": ["soft_followup:quality"],
                            "counts": {"quality": 1, "context": 0, "total": 1},
                        }
                    },
                }
            ],
        )
    )  # type: ignore[arg-type]

    shadow = captured_trace["current_gaps_shadow"]["soft_followup_hints"]
    assert shadow["mode"] == "advisory"
    assert shadow["present"] is False
    assert shadow["applied"] is False
    assert shadow["selected_hint_ids"] == []
    assert shadow["rejected_reasons"] == {"topic_affinity_mismatch": 1}
    assert shadow["topic_affinity_policy"] == "balanced"
    assert shadow["topic_affinity_rejected_count"] == 1
    assert shadow["topic_affinity_rejected_reasons"] == {
        "topic_affinity_mismatch": 1
    }

    artifacts = captured_trace["selection_artifacts"]
    assert artifacts["current_gaps"]["soft_followup_hints"] == shadow
    prompt_text = "\n".join(
        str(slot.get("text") or "") for slot in captured_trace["prompt_slots"]
    )
    assert "Ask for idempotency key scope." not in prompt_text
    assert "Ask for idempotency key scope." not in str(
        generator_kwargs.get("history_section_override") or ""
    )


def test_ask_question_advisory_topic_affinity_allows_same_seed_variant_family(
    monkeypatch,
) -> None:
    captured_trace = _install_default_patches(
        monkeypatch,
        retrieval=_make_retrieval(docs=[]),
        strategies=[],
        skills=[],
    )
    generator_kwargs: dict[str, Any] = {}

    def fake_generate_question(**kwargs):
        generator_kwargs.update(kwargs)
        return _fake_generate_question(**kwargs)

    monkeypatch.setattr(ask_mod, "generate_question", fake_generate_question)
    monkeypatch.setattr(
        ask_mod,
        "select_question_candidates",
        lambda **_kwargs: QuestionSelectionResult(
            candidates=[
                _ascii_question_candidate(
                    seed_id="coding_quality.java_service_testability",
                    variant_id=(
                        "coding_quality.java_service_testability."
                        "transaction_service_boundary"
                    ),
                    dimension="coding_quality",
                )
            ]
        ),
    )
    monkeypatch.setattr(ask_mod, "record_question_usages", lambda **_kwargs: None)

    ask_mod.ask_question_node(
        _base_state(
            current_dimension="coding_quality",
            dimensions=["coding_quality"],
            dimension_status={"coding_quality": "active"},
            turn_idx=9,
            formal_turn_idx=8,
            runtime_config={
                "rag_mode": "vector",
                "rag_top_k": 2,
                "question_selector_mode": "structured_primary",
                "soft_followup_prompt_mode": "advisory",
            },
            selected_action={"id": "plan_deep_probe", "plan_template": "deep_probe"},
            qa_history=[
                {
                    "turn_idx": 8,
                    "dimension": "coding_quality",
                    "selection_artifacts": {
                        "question_items": [
                            {
                                "seed_id": "coding_quality.java_service_testability",
                                "variant_id": (
                                    "coding_quality.java_service_testability."
                                    "async_job_test"
                                ),
                                "rank": 1,
                                "injected": True,
                            }
                        ]
                    },
                    "evaluation": {
                        "soft_followup_hints": {
                            "present": True,
                            "mode": "shadow",
                            "applied": False,
                            "quality_hints": [
                                {
                                    "hint_id": "soft_followup:quality",
                                    "source": "reviewed_supporting",
                                    "intent": "probe_quality_gap",
                                    "check_id": "reviewed:cq:testability",
                                    "text": "Ask for test seam details.",
                                    "focus": "Ask for test seam details.",
                                    "verdict": "partial",
                                }
                            ],
                            "context_hints": [],
                            "priority_order": ["soft_followup:quality"],
                            "counts": {"quality": 1, "context": 0, "total": 1},
                        }
                    },
                }
            ],
        )
    )  # type: ignore[arg-type]

    shadow = captured_trace["current_gaps_shadow"]["soft_followup_hints"]
    assert shadow["mode"] == "advisory"
    assert shadow["present"] is True
    assert shadow["applied"] is True
    assert shadow["applied_to_slot"] == "CURRENT_GAPS"
    assert shadow["selected_hint_ids"] == ["soft_followup:quality"]
    assert shadow["quality_hints"][0]["topic_affinity"] == "same_seed"
    assert shadow["quality_hints"][0]["source_seed_id"] == (
        "coding_quality.java_service_testability"
    )

    artifacts = captured_trace["selection_artifacts"]
    assert artifacts["current_gaps"]["soft_followup_hints"] == shadow
    current_gaps_slot = next(
        slot
        for slot in captured_trace["prompt_slots"]
        if slot["prompt_label"] == "CURRENT_GAPS"
    )
    assert "Ask for test seam details." in current_gaps_slot["text"]
    assert "Ask for test seam details." in str(
        generator_kwargs.get("history_section_override") or ""
    )


def test_ask_question_advisory_mode_does_not_cross_dimension_inject(
    monkeypatch,
) -> None:
    captured_trace = _install_default_patches(
        monkeypatch,
        retrieval=_make_retrieval(docs=[]),
        strategies=[],
        skills=[],
    )

    ask_mod.ask_question_node(
        _base_state(
            turn_idx=2,
            formal_turn_idx=1,
            runtime_config={
                "rag_mode": "vector",
                "rag_top_k": 2,
                "soft_followup_prompt_mode": "advisory",
            },
            current_dimension="coding_quality",
            dimensions=["coding_quality"],
            dimension_status={"coding_quality": "active"},
            selected_action={"id": "plan_deep_probe", "plan_template": "deep_probe"},
            qa_history=[
                {
                    "turn_idx": 1,
                    "dimension": "system_design",
                    "evaluation": {
                        "soft_followup_hints": {
                            "present": True,
                            "mode": "shadow",
                            "applied": False,
                            "quality_hints": [
                                {
                                    "hint_id": "soft_followup:quality",
                                    "text": "Ask for retry boundary details.",
                                }
                            ],
                            "context_hints": [],
                            "priority_order": ["soft_followup:quality"],
                            "counts": {"quality": 1, "context": 0, "total": 1},
                        }
                    },
                }
            ],
        )
    )  # type: ignore[arg-type]

    shadow = captured_trace["current_gaps_shadow"]["soft_followup_hints"]
    assert shadow["mode"] == "advisory"
    assert shadow["present"] is False
    assert shadow["applied"] is False
    assert shadow["not_applied_reason"] == "no_eligible_hints"
    assert shadow["rejected_reasons"] == {"dimension_mismatch": 1}
    prompt_text = "\n".join(
        str(slot.get("text") or "") for slot in captured_trace["prompt_slots"]
    )
    assert "Ask for retry boundary details." not in prompt_text


def test_ask_question_invalid_soft_followup_prompt_mode_falls_back_off(
    monkeypatch,
) -> None:
    captured_trace = _install_default_patches(
        monkeypatch,
        retrieval=_make_retrieval(docs=[]),
        strategies=[],
        skills=[],
    )

    ask_mod.ask_question_node(
        _base_state(
            runtime_config={
                "rag_mode": "vector",
                "rag_top_k": 2,
                "soft_followup_prompt_mode": "surprise",
            }
        )
    )  # type: ignore[arg-type]

    shadow = captured_trace["current_gaps_shadow"]["soft_followup_hints"]
    assert captured_trace["soft_followup_prompt_mode"] == "off"
    assert captured_trace["soft_followup_prompt_mode_warnings"] == [
        "invalid_soft_followup_prompt_mode_fallback"
    ]
    assert shadow["mode"] == "off"
    assert shadow["warnings"] == ["invalid_soft_followup_prompt_mode_fallback"]


def test_prompt_slots_include_strategy_skill_runtime_diagnostics() -> None:
    ctx = {
        "structured_primary_seed_hit": False,
        "retrieval_block": "",
        "question_seed_block": "",
        "candidate_anchor_block": "",
        "resume_rag_block": "",
        "self_intro_rag_block": "",
        "strategy_block": "strategy guidance " * 20,
        "skill_block": "skill guidance " * 20,
        "strategy_prompt_diagnostics": {
            "runtime_truncated": True,
            "budget_chars": 3200,
            "budget_level": "tight",
            "budget_source": "prompt_budget_diagnostics",
            "global_budget_pressure": "tight",
            "original_chars": 5000,
            "injected_chars": 3000,
            "items": [
                {
                    "rank": 1,
                    "id": "strategy-1",
                    "name": "Strategy 1",
                    "body_budget_chars": 1200,
                    "original_body_chars": 2000,
                    "injected_body_chars": 1200,
                    "runtime_truncated": True,
                    "truncation_reason": "body_budget_exceeded",
                }
            ],
        },
        "skill_prompt_diagnostics": {
            "runtime_truncated": False,
            "budget_chars": 3600,
            "original_chars": 900,
            "injected_chars": 900,
            "items": [
                {
                    "rank": 1,
                    "skill_id": "skill-1",
                    "name": "Skill 1",
                    "body_budget_chars": 1100,
                    "original_body_chars": 600,
                    "injected_body_chars": 600,
                    "runtime_truncated": False,
                    "truncation_reason": None,
                }
            ],
        },
    }

    slots = ask_mod._prompt_slots_for_trace(ctx, text_limit=32)
    by_label = {slot["prompt_label"]: slot for slot in slots}

    strategy = by_label["STRATEGY_MEMORY"]
    assert strategy["prompt_truncated"] is True
    assert strategy["runtime_truncated"] is True
    assert strategy["trace_text_truncated"] is True
    assert strategy["runtime_budget_chars"] == 3200
    assert strategy["runtime_budget_level"] == "tight"
    assert strategy["runtime_budget_source"] == "prompt_budget_diagnostics"
    assert strategy["runtime_global_budget_pressure"] == "tight"
    assert strategy["runtime_original_chars"] == 5000
    assert strategy["runtime_injected_chars"] == 3000
    assert strategy["runtime_items"][0]["id"] == "strategy-1"
    assert strategy["runtime_items"][0]["truncation_reason"] == "body_budget_exceeded"

    skill = by_label["INTERVIEW_SKILLS"]
    assert skill["prompt_truncated"] is False
    assert skill["runtime_truncated"] is False
    assert skill["trace_text_truncated"] is True
    assert skill["runtime_items"][0]["skill_id"] == "skill-1"


def test_apply_auxiliary_prompt_budget_expands_strategy_and_skill(monkeypatch) -> None:
    monkeypatch.setattr(
        ask_mod,
        "get_settings",
        lambda: SimpleNamespace(
            llm_provider="openai",
            llm_model="gpt-4o-mini",
            llm_model_per_agent={},
            llm_max_tokens=2048,
        ),
    )
    monkeypatch.setattr(ask_mod, "_runtime_llm_override", lambda: None)
    ctx = {
        "structured_primary_seed_hit": False,
        "retrieval_block": "retrieval",
        "question_seed_block": "seed",
        "candidate_anchor_block": "anchor",
        "resume_rag_block": "resume",
        "self_intro_rag_block": "intro",
        "history_section": "history " * 100,
        "contract_hints": {"must_cover": ["Redis"]},
        "strategy_entries": [
            StrategyEntry(
                path=Path(f"strategy-{idx}.md"),
                id=f"strategy-{idx}",
                name=f"Strategy {idx}",
                dimensions=["technical_depth"],
                job_levels=["junior"],
                body=chr(96 + idx) * 3000,
            )
            for idx in range(1, 4)
        ],
        "skill_entries": [
            SkillEntry(
                path=Path(f"skill-{idx}.md"),
                id=f"skill-{idx}",
                name=f"Skill {idx}",
                description="Probe deeply.",
                dimensions=["technical_depth"],
                job_levels=["junior"],
                body=chr(96 + idx) * 3000,
            )
            for idx in range(1, 4)
        ],
    }

    ask_mod._apply_auxiliary_prompt_budget(ctx)

    budget = ctx["prompt_budget_diagnostics"]
    assert budget["budget_level"] == "expanded"
    assert budget["strategy_budget_chars"] == 4800
    assert budget["skill_budget_chars"] == 5200
    assert budget["fallback_used"] is False
    assert budget["protected_slot_chars"] == sum(
        slot["chars"] for slot in budget["protected_slots"]
    )
    assert ctx["strategy_prompt_diagnostics"]["budget_level"] == "expanded"
    assert ctx["strategy_prompt_diagnostics"]["items"][0]["body_budget_chars"] == 1800
    assert ctx["skill_prompt_diagnostics"]["budget_level"] == "expanded"
    assert ctx["skill_prompt_diagnostics"]["items"][0]["body_budget_chars"] == 1700


def test_apply_auxiliary_prompt_budget_falls_back_for_unknown_model(monkeypatch) -> None:
    monkeypatch.setattr(
        ask_mod,
        "get_settings",
        lambda: SimpleNamespace(
            llm_provider="openai_compatible",
            llm_model="custom-local-model",
            llm_model_per_agent={},
            llm_max_tokens=2048,
        ),
    )
    monkeypatch.setattr(ask_mod, "_runtime_llm_override", lambda: None)
    ctx = {
        "structured_primary_seed_hit": False,
        "retrieval_block": "",
        "strategy_entries": [
            StrategyEntry(
                path=Path("strategy.md"),
                id="strategy",
                name="Fallback Strategy",
                dimensions=["communication"],
                job_levels=["junior"],
                body="x" * 3000,
            )
        ],
        "skill_entries": [
            SkillEntry(
                path=Path("skill.md"),
                id="skill",
                name="Fallback Skill",
                description="Probe clearly.",
                dimensions=["communication"],
                job_levels=["junior"],
                body="y" * 3000,
            )
        ],
    }

    ask_mod._apply_auxiliary_prompt_budget(ctx)

    budget = ctx["prompt_budget_diagnostics"]
    assert budget["budget_level"] == "fallback"
    assert budget["fallback_used"] is True
    assert budget["fallback_reason"] == "unknown_model_context_window"
    assert ctx["strategy_prompt_diagnostics"]["budget_chars"] == 3200
    assert ctx["strategy_prompt_diagnostics"]["items"][0]["body_budget_chars"] == 1200
    assert ctx["skill_prompt_diagnostics"]["budget_chars"] == 3600
    assert ctx["skill_prompt_diagnostics"]["items"][0]["body_budget_chars"] == 1100


def test_prompt_slots_include_candidate_rag_runtime_diagnostics() -> None:
    ctx = {
        "structured_primary_seed_hit": False,
        "retrieval_block": "",
        "question_seed_block": "",
        "candidate_anchor_block": "",
        "resume_rag_block": "[resume] Coupon Guard: Redis " * 20,
        "self_intro_rag_block": "[self_intro] Opening claim: Lua " * 20,
        "strategy_block": "",
        "skill_block": "",
        "resume_rag_prompt_diagnostics": {
            "runtime_truncated": True,
            "budget_chars": 800,
            "original_chars": 1400,
            "injected_chars": 780,
            "items": [
                {
                    "rank": 1,
                    "id": 10,
                    "source_type": "resume",
                    "project_name": "Coupon Guard",
                    "heading": "Redis consistency",
                    "chunk_index": 0,
                    "score": 0.91,
                    "body_budget_chars": 520,
                    "original_body_chars": 1000,
                    "injected_body_chars": 520,
                    "runtime_truncated": True,
                    "truncation_reason": "body_budget_exceeded",
                }
            ],
        },
        "self_intro_rag_prompt_diagnostics": {
            "runtime_truncated": False,
            "budget_chars": 500,
            "original_chars": 240,
            "injected_chars": 240,
            "items": [
                {
                    "rank": 1,
                    "id": 11,
                    "source_type": "self_intro",
                    "project_name": "",
                    "heading": "Opening claim",
                    "chunk_index": 0,
                    "score": 0.86,
                    "body_budget_chars": 220,
                    "original_body_chars": 200,
                    "injected_body_chars": 200,
                    "runtime_truncated": False,
                    "truncation_reason": None,
                }
            ],
        },
    }

    slots = ask_mod._prompt_slots_for_trace(ctx, text_limit=32)
    by_label = {slot["prompt_label"]: slot for slot in slots}

    resume = by_label["CANDIDATE_RESUME_RAG"]
    assert resume["prompt_truncated"] is True
    assert resume["runtime_truncated"] is True
    assert resume["trace_text_truncated"] is True
    assert resume["runtime_budget_chars"] == 800
    assert resume["runtime_original_chars"] == 1400
    assert resume["runtime_injected_chars"] == 780
    assert resume["runtime_items"][0]["source_type"] == "resume"
    assert resume["runtime_items"][0]["project_name"] == "Coupon Guard"
    assert resume["runtime_items"][0]["truncation_reason"] == "body_budget_exceeded"

    self_intro = by_label["SELF_INTRO_RAG"]
    assert self_intro["prompt_truncated"] is False
    assert self_intro["runtime_truncated"] is False
    assert self_intro["trace_text_truncated"] is True
    assert self_intro["runtime_budget_chars"] == 500
    assert self_intro["runtime_items"][0]["source_type"] == "self_intro"


def test_prompt_slots_include_candidate_anchor_field_runtime_diagnostics() -> None:
    ctx = {
        "structured_primary_seed_hit": False,
        "retrieval_block": "",
        "question_seed_block": "",
        "candidate_anchor_block": "Project summary: " + ("Redis " * 20),
        "resume_rag_block": "",
        "self_intro_rag_block": "",
        "strategy_block": "",
        "skill_block": "",
        "candidate_anchor_prompt_diagnostics": {
            "runtime_truncated": True,
            "budget_chars": 120,
            "original_chars": 360,
            "injected_chars": 120,
            "items": [
                {
                    "rank": 1,
                    "id": "project_summary",
                    "field": "project_summary",
                    "name": "Project summary",
                    "limit": 240,
                    "limit_type": "chars",
                    "body_budget_chars": 240,
                    "original_body_chars": 420,
                    "injected_body_chars": 240,
                    "runtime_truncated": True,
                    "truncation_reason": "field_char_limit",
                }
            ],
        },
    }

    slots = ask_mod._prompt_slots_for_trace(ctx, text_limit=32)
    by_label = {slot["prompt_label"]: slot for slot in slots}

    candidate_anchor = by_label["CANDIDATE_ANCHOR"]
    assert candidate_anchor["prompt_truncated"] is True
    assert candidate_anchor["runtime_truncated"] is True
    assert candidate_anchor["trace_text_truncated"] is True
    assert candidate_anchor["runtime_items"][0]["field"] == "project_summary"
    assert candidate_anchor["runtime_items"][0]["limit_type"] == "chars"
    assert candidate_anchor["runtime_items"][0]["truncation_reason"] == "field_char_limit"


def test_candidate_anchor_rag_shadow_writes_artifact_but_not_blocks(monkeypatch) -> None:
    monkeypatch.setattr(
        ask_mod,
        "get_settings",
        lambda: SimpleNamespace(resume_rag_mode="shadow"),
    )
    monkeypatch.setattr(
        ask_mod,
        "retrieve_candidate_anchors",
        lambda **_kwargs: CandidateAnchorRagResult(
            resume_block="[resume] Redis Lua coupon guard",
            self_intro_block="[self_intro] 50w QPS Lua atomic",
            hits=[],
            latency_ms=12,
            fallback_reason=None,
            skipped=False,
        ),
    )
    ctx = {
        "dimension": "system_design",
        "question_items": [{"scenario_brief": "Redis consistency"}],
        "resume_anchor": {"project_name": "Coupon Guard"},
        "target_skills": ["Redis"],
    }

    ask_mod._step_retrieve_candidate_anchors(
        _base_state(
            candidate={
                "resume_parsed": {},
                "resume_vector_status": {
                    "status": "ready",
                    "resume_revision_id": "rev_1",
                },
            },
            self_intro_vector_status={
                "status": "ready",
                "self_intro_revision_id": "intro_rev_1",
            },
            self_intro_profile={"emphasized_projects": ["Coupon Guard"]},
        ),
        ctx,
    )

    assert ctx["resume_rag_block"] == ""
    assert ctx["self_intro_rag_block"] == ""
    assert ctx["candidate_anchor_rag_artifact"]["status"] == "shadow"


def test_candidate_anchor_rag_sample_rate_can_skip_retrieval(monkeypatch) -> None:
    monkeypatch.setattr(
        ask_mod,
        "get_settings",
        lambda: SimpleNamespace(
            resume_rag_mode="shadow",
            resume_rag_session_sample_rate=0.0,
        ),
    )
    monkeypatch.setattr(
        ask_mod,
        "retrieve_candidate_anchors",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("should not retrieve")),
    )
    ctx = {
        "dimension": "system_design",
        "question_items": [{"scenario_brief": "Redis consistency"}],
        "resume_anchor": {"project_name": "Coupon Guard"},
        "target_skills": ["Redis"],
    }

    ask_mod._step_retrieve_candidate_anchors(
        _base_state(
            candidate={
                "resume_parsed": {},
                "resume_vector_status": {
                    "status": "ready",
                    "resume_revision_id": "rev_1",
                },
            },
        ),
        ctx,
    )

    assert ctx["resume_rag_block"] == ""
    assert ctx["self_intro_rag_block"] == ""
    assert ctx["candidate_anchor_rag_artifact"] == {
        "status": "shadow",
        "skipped": True,
        "fallback_reason": "sampled_out",
        "hits": [],
    }


def test_anchor_rag_blocks_survive_structured_primary_seed_hit(monkeypatch) -> None:
    monkeypatch.setattr(
        ask_mod,
        "get_settings",
        lambda: SimpleNamespace(resume_rag_mode="primary"),
    )
    monkeypatch.setattr(
        ask_mod,
        "retrieve_candidate_anchors",
        lambda **_kwargs: CandidateAnchorRagResult(
            resume_block="[resume] Redis Lua coupon guard",
            self_intro_block="[self_intro] 50w QPS Lua atomic",
            hits=[],
            latency_ms=12,
            fallback_reason=None,
            skipped=False,
        ),
    )
    state = _base_state(
        candidate={
            "resume_parsed": {},
            "resume_vector_status": {
                "status": "ready",
                "resume_revision_id": "rev_1",
            },
        },
        self_intro_vector_status={
            "status": "ready",
            "self_intro_revision_id": "intro_rev_1",
        },
    )
    ctx = {
        "dimension": "system_design",
        "question_items": [{"scenario_brief": "Redis consistency"}],
        "resume_anchor": {"project_name": "Coupon Guard"},
        "target_skills": ["Redis"],
        "structured_primary_seed_hit": True,
    }

    ask_mod._step_retrieve_candidate_anchors(state, ctx)

    assert ctx["resume_rag_block"] == "[resume] Redis Lua coupon guard"
    assert ctx["self_intro_rag_block"] == "[self_intro] 50w QPS Lua atomic"
    assert ctx["candidate_anchor_rag_artifact"]["status"] == "primary"


def test_candidate_anchor_rag_rebinds_missing_cache_hit_chunks(monkeypatch) -> None:
    monkeypatch.setattr(
        ask_mod,
        "get_settings",
        lambda: SimpleNamespace(resume_rag_mode="primary"),
    )
    count_results = [
        {"resume": 0, "self_intro": 0, "total": 0},
        {"resume": 24, "self_intro": 0, "total": 24},
    ]
    count_calls: list[dict[str, Any]] = []

    def fake_count_session_anchor_chunks(**kwargs):
        count_calls.append(kwargs)
        return count_results.pop(0)

    rebind_calls: list[dict[str, Any]] = []

    def fake_try_bind_cached_resume_anchors(**kwargs):
        rebind_calls.append(kwargs)
        return {"status": "ready", "chunk_count": 24, "cache_hit": True}

    captured: dict[str, Any] = {}

    def fake_retrieve_candidate_anchors(**kwargs):
        captured.update(kwargs)
        return CandidateAnchorRagResult(
            resume_block="[resume] rebound cached chunk",
            self_intro_block="",
            hits=[],
            latency_ms=12,
            fallback_reason=None,
            skipped=False,
        )

    monkeypatch.setattr(
        ask_mod,
        "_count_session_anchor_chunks",
        fake_count_session_anchor_chunks,
        raising=False,
    )
    monkeypatch.setattr(
        ask_mod,
        "try_bind_cached_resume_anchors",
        fake_try_bind_cached_resume_anchors,
        raising=False,
    )
    monkeypatch.setattr(
        ask_mod,
        "retrieve_candidate_anchors",
        fake_retrieve_candidate_anchors,
    )

    ctx = {
        "dimension": "system_design",
        "question_items": [{"scenario_brief": "Redis consistency"}],
        "resume_anchor": {"project_name": "Coupon Guard"},
        "target_skills": ["Redis"],
    }

    ask_mod._step_retrieve_candidate_anchors(
        _base_state(
            candidate={
                "resume_parsed": {},
                "resume_vector_status": {
                    "status": "ready",
                    "resume_revision_id": "rev_1",
                    "source_artifact_id": "artifact_1",
                    "source_cache_key": "cache_1",
                    "embedding_model_version": "qwen:text-embedding-v4:1536@v1",
                    "cache_hit": True,
                    "chunk_count": 24,
                },
            },
        ),
        ctx,
    )

    assert ctx["resume_rag_block"] == "[resume] rebound cached chunk"
    assert captured["resume_revision_id"] == "rev_1"
    assert captured["self_intro_revision_id"] is None
    assert len(count_calls) == 2
    assert rebind_calls == [
        {
            "session_id": "sess-selection-artifacts",
            "resume_revision_id": "rev_1",
            "source_artifact_id": "artifact_1",
            "cache_key": "cache_1",
            "embedding_model_version": "qwen:text-embedding-v4:1536@v1",
        }
    ]
    validation = ctx["candidate_anchor_rag_artifact"]["bind_validation"]
    assert validation["bound_count"] == 24
    assert validation["rebind_attempted"] is True
    assert validation["rebind_success"] is True
    assert validation["fallback_reason"] is None


def test_candidate_anchor_rag_reports_bind_missing_without_retrieval(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        ask_mod,
        "get_settings",
        lambda: SimpleNamespace(resume_rag_mode="primary"),
    )
    monkeypatch.setattr(
        ask_mod,
        "_count_session_anchor_chunks",
        lambda **_kwargs: {"resume": 0, "self_intro": 0, "total": 0},
        raising=False,
    )
    monkeypatch.setattr(
        ask_mod,
        "try_bind_cached_resume_anchors",
        lambda **_kwargs: None,
        raising=False,
    )
    monkeypatch.setattr(
        ask_mod,
        "retrieve_candidate_anchors",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("retrieve_candidate_anchors should not run")
        ),
    )
    ctx = {
        "dimension": "system_design",
        "question_items": [{"scenario_brief": "Redis consistency"}],
        "resume_anchor": {"project_name": "Coupon Guard"},
        "target_skills": ["Redis"],
    }

    ask_mod._step_retrieve_candidate_anchors(
        _base_state(
            candidate={
                "resume_parsed": {},
                "resume_vector_status": {
                    "status": "ready",
                    "resume_revision_id": "rev_1",
                    "source_artifact_id": "artifact_1",
                    "source_cache_key": "cache_1",
                    "embedding_model_version": "qwen:text-embedding-v4:1536@v1",
                    "cache_hit": True,
                    "chunk_count": 24,
                },
            },
        ),
        ctx,
    )

    assert ctx["resume_rag_block"] == ""
    assert ctx["self_intro_rag_block"] == ""
    artifact = ctx["candidate_anchor_rag_artifact"]
    assert artifact["status"] == "primary"
    assert artifact["fallback_reason"] == "session_anchor_bind_missing"
    assert artifact["prompt_injected"] is False
    assert artifact["hits"] == []
    validation = artifact["bind_validation"]
    assert validation["bound_count"] == 0
    assert validation["rebind_attempted"] is True
    assert validation["rebind_success"] is False
    assert validation["fallback_reason"] == "session_anchor_bind_missing"


def test_ask_question_node_refreshes_pending_resume_vector_status(monkeypatch) -> None:
    retrieval = RetrievalContext(docs=[], as_prompt_block="")
    _install_default_patches(
        monkeypatch,
        retrieval=retrieval,
        strategies=[],
        skills=[],
    )
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
            enable_question_fit_profile=True,
            enable_question_reranker_shadow=False,
            question_reranker_timeout_ms=4000,
            question_primary_role_tags=list(_COVERED_PRIMARY_ROLE_TAGS),
            resume_rag_mode="primary",
            resume_rag_session_sample_rate=1.0,
        ),
    )
    monkeypatch.setattr(
        ask_mod,
        "refresh_resume_vector_status",
        lambda **kwargs: {
            "status": "ready",
            "resume_source_id": kwargs["resume_source_id"],
            "resume_revision_id": "rev_ready",
            "chunk_count": 12,
        },
    )
    captured: dict[str, Any] = {}

    def fake_retrieve_candidate_anchors(**kwargs):
        captured.update(kwargs)
        return CandidateAnchorRagResult(
            resume_block="[resume] Redis Lua coupon guard",
            self_intro_block="",
            hits=[],
            latency_ms=12,
            fallback_reason=None,
            skipped=False,
        )

    monkeypatch.setattr(
        ask_mod,
        "retrieve_candidate_anchors",
        fake_retrieve_candidate_anchors,
    )

    out = ask_mod.ask_question_node(
        _base_state(
            candidate={
                "resume_parsed": {"summary": "candidate"},
                "resume_source_id": "artifact_1",
                "resume_vector_status": {
                    "status": "pending_background",
                    "resume_source_id": "artifact_1",
                    "resume_revision_id": None,
                },
            },
        )
    )

    assert out["candidate"]["resume_vector_status"]["status"] == "ready"
    assert out["candidate"]["resume_vector_status"]["resume_revision_id"] == "rev_ready"
    assert captured["resume_revision_id"] == "rev_ready"


def test_challenge_with_reference_prefers_resume_then_self_intro_then_legacy() -> None:
    ctx = {
        "question_payload": {},
        "resume_rag_block": "",
        "self_intro_rag_block": "[self_intro] Redis Lua coupon guard",
        "retrieval_block": "(legacy stuff)",
    }

    ask_mod._step_challenge_with_reference(_base_state(), ctx)

    assert "Redis Lua coupon guard" in ctx["question_payload"]["challenge_context"]


def test_step_select_structured_question_uses_rule_anchor_only(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    class _FitProfile:
        def as_artifact(self) -> dict[str, Any]:
            return {"anchor_confidence": "medium"}

    def fake_build_question_fit_profile(**kwargs):
        captured["fit_kwargs"] = kwargs
        return _FitProfile()

    def fake_select_question_candidates(**kwargs):
        captured["kwargs"] = kwargs
        return QuestionSelectionResult(candidates=[])

    monkeypatch.setattr(
        ask_mod,
        "build_question_fit_profile",
        fake_build_question_fit_profile,
    )
    monkeypatch.setattr(
        ask_mod,
        "select_question_candidates",
        fake_select_question_candidates,
    )
    monkeypatch.setattr(
        ask_mod,
        "get_settings",
        lambda: SimpleNamespace(
            enable_question_fit_profile=True,
            enable_question_reranker_shadow=False,
            question_reranker_timeout_ms=4000,
            question_primary_role_tags=list(_COVERED_PRIMARY_ROLE_TAGS),
        ),
    )

    state = _base_state(
        runtime_config={
            "question_selector_mode": "structured_shadow",
            "rag_mode": "vector",
        }
    )
    ctx = {
        "dimension": "system_design",
        "target_skills": ["Redis"],
        "contract_hints": {},
        "resume_anchor": {
            "project_name": "Smart Learning Coupon Guard",
            "tech_stack": ["Redis"],
        },
        "resume_rag_block": "[resume] Redis Lua coupon guard",
        "self_intro_rag_block": "[self_intro] 50w QPS Lua atomic",
        "candidate_anchor_rag_artifact": {"status": "primary"},
    }

    ask_mod._step_select_structured_question(state, ctx, probe_intent=None)

    assert captured["kwargs"]["resume_anchor_text"]
    assert "resume_rag_block" not in captured["kwargs"]
    assert "self_intro_rag_block" not in captured["kwargs"]
    assert "candidate_anchor_rag_artifact" not in captured["kwargs"]
    assert "resume_rag_block" not in captured["fit_kwargs"]
    assert "self_intro_rag_block" not in captured["fit_kwargs"]
    assert "candidate_anchor_rag_artifact" not in captured["fit_kwargs"]


def test_selection_artifacts_baseline_keys_superset_after_rag() -> None:
    artifacts = ask_mod._build_selection_artifacts(
        {
            "dimension": "system_design",
            "rag_artifact": {
                "mode": "vector",
                "top_k": 2,
                "doc_refs": [],
                "empty": True,
                "reason": "no_relevant_knowledge",
            },
            "strategy_memory_refs": [],
            "skill_artifact": {"enabled": False, "refs": []},
            "avoid_pattern_artifact": {
                "enabled": False,
                "rendered": False,
                "dimension": "system_design",
                "top_n": 0,
                "min_support": 0,
            },
            "question_items": [],
            "contract_hints": {},
            "candidate_anchor_rag_artifact": {"status": "primary"},
        }
    )
    expected_baseline = {
        "rag",
        "strategies",
        "skills",
        "avoid_patterns",
        "question_items",
        "failure_categories",
        "candidate_anchor_rag",
    }
    assert expected_baseline.issubset(set(artifacts.keys()))
    assert artifacts["candidate_anchor_rag"]["status"] == "primary"


def test_selection_artifacts_exposes_resume_anchor_query_subject() -> None:
    resume_anchor = {
        "anchor_key": "focus-coupon-consistency",
        "label": "Coupon consistency",
        "project_name": "Coupon Guard",
    }

    artifacts = ask_mod._build_selection_artifacts(
        {
            "dimension": "system_design",
            "resume_anchor": resume_anchor,
            "anchor_scheduler": {
                "available": True,
                "anchor_key": "focus-coupon-consistency",
                "anchor_attempt": 1,
                "max_anchor_attempts": 2,
                "expansion_reason": "first_pass_self_intro_match",
            },
            "candidate_anchor_rag_artifact": {
                "status": "primary",
                "anchor_key": "focus-coupon-consistency",
                "hits": [{"project_name": "Coupon Guard"}],
            },
        }
    )

    assert artifacts["resume_anchor"] == resume_anchor
    assert artifacts["anchor_scheduler"]["anchor_key"] == "focus-coupon-consistency"
    assert artifacts["candidate_anchor_rag"]["hits"][0]["project_name"] == "Coupon Guard"


def test_history_selection_artifacts_preserves_question_decision_basis() -> None:
    history_artifacts = build_question_history_selection_artifacts(
        {
            "selection_artifacts": {
                "question_decision_basis": {
                    "version": "v1",
                    "sources": ["resume", "job"],
                    "dimension": "system_design",
                    "resume_anchor": {
                        "label": "Coupon consistency",
                        "project_id": "proj-coupon",
                        "source": "resume",
                    },
                    "target_skills": [
                        {"value": "Redis", "source": "job_spec"},
                    ],
                    "reason_codes": ["covers_target_skills"],
                    "prompt_slot": "must-not-survive",
                },
                "question_items": [
                    {
                        "seed_id": "seed-1",
                        "variant_id": "variant-1",
                        "rank": 1,
                        "injected": True,
                    }
                ],
            }
        }
    )

    assert history_artifacts["question_decision_basis"] == {
        "version": "v1",
        "sources": ["resume", "job"],
        "dimension": "system_design",
        "resume_anchor": {
            "label": "Coupon consistency",
            "project_id": "proj-coupon",
            "source": "resume",
        },
        "target_skills": [{"value": "Redis", "source": "job_spec"}],
        "reason_codes": ["covers_target_skills"],
    }
    assert history_artifacts["question_items"] == [
        {
            "seed_id": "seed-1",
            "variant_id": "variant-1",
            "rank": 1,
            "injected": True,
        }
    ]


def test_ask_question_applies_depth_followup_slot(monkeypatch) -> None:
    retrieval = RetrievalContext(docs=[], as_prompt_block="")
    captured_trace = _install_default_patches(
        monkeypatch,
        retrieval=retrieval,
        strategies=[],
        skills=[],
    )
    resume_anchor = {
        "anchor_key": "focus-redis",
        "label": "Redis coupon consistency",
        "project_id": "proj_coupon",
        "skills": ["Redis"],
        "dimensions": ["technical_depth"],
    }
    slot = {
        "phase": "depth_followup",
        "source_turn_idx": 8,
        "dimension": "technical_depth",
        "resume_anchor": resume_anchor,
        "probe_intent": "debugging_probe",
        "plan_template": "deep_probe",
        "depth_reason": "recent_refine_then_passed",
        "depth_slot_rank": 1,
        "depth_target_turns": 12,
    }

    out = ask_mod.ask_question_node(
        _base_state(
            current_dimension="technical_depth",
            selected_action={
                "id": "plan_deep_probe",
                "plan_template": "deep_probe",
                "diagnostics": {
                    "mode": "depth_followup",
                    "depth_followup_slot": slot,
                },
            },
            runtime_config={"interview_depth": "deep", "rag_mode": "vector"},
            formal_turn_idx=10,
            max_turns=12,
            qa_history=[
                {
                    "turn_idx": 8,
                    "dimension": "technical_depth",
                    "resume_anchor": resume_anchor,
                    "evaluation": {"score": 9.0, "passed": True},
                }
            ],
        )
    )

    question = out["current_question"]
    artifacts = question["selection_artifacts"]
    assert question["phase"] == "depth_followup"
    assert question["depth_followup"]["source_turn_idx"] == 8
    assert question["probe_intent"] == "debugging_probe"
    assert question["resume_anchor"] == resume_anchor
    assert artifacts["depth_followup"]["depth_reason"] == "recent_refine_then_passed"
    assert artifacts["depth_followup"]["depth_slot_rank"] == 1
    assert artifacts["resume_anchor"] == resume_anchor
    assert captured_trace["selection_artifacts"] == artifacts


def test_ask_question_records_question_decision_basis(monkeypatch) -> None:
    retrieval = RetrievalContext(docs=[], as_prompt_block="")
    captured_trace = _install_default_patches(
        monkeypatch,
        retrieval=retrieval,
        strategies=[],
        skills=[],
    )
    resume_anchor = {
        "anchor_key": "focus-coupon-consistency",
        "label": "Coupon consistency",
        "project_id": "proj-coupon",
        "skills": ["Redis"],
        "knowledge_source": "local",
    }

    monkeypatch.setattr(
        ask_mod,
        "select_resume_anchor_with_schedule",
        lambda **_kwargs: {
            "resume_anchor": resume_anchor,
            "scheduler": {
                "available": True,
                "anchor_key": "focus-coupon-consistency",
                "anchor_attempt": 1,
                "max_anchor_attempts": 2,
                "expansion_reason": "first_pass",
            },
        },
    )
    monkeypatch.setattr(
        ask_mod,
        "select_target_skills",
        lambda **_kwargs: {
            "target_skills": ["Redis", "Kafka"],
            "focus_source": "jd_resume_overlap",
        },
    )

    out = ask_mod.ask_question_node(
        _base_state(
            current_dimension="system_design",
            candidate={
                "resume_parsed": {"skills": ["Redis", "Kafka"]},
                "resume_parse_audit": {
                    "version": "v1",
                    "mode": "ai_refined",
                    "field_sources": {"skills": "mixed"},
                    "skills_summary": {
                        "both": ["Redis"],
                        "llm_only": ["Kafka"],
                    },
                },
            },
            job_spec={
                "title": "Backend Engineer",
                "level": "senior",
                "required_skills": ["Redis"],
                "interview_direction": "java_backend",
            },
            refine_mode=True,
            pending_contract_hints={"failure_reason": "thin metrics"},
        )
    )

    artifacts = out["current_question"]["selection_artifacts"]
    basis = artifacts["question_decision_basis"]

    assert {"resume", "job", "followup"}.issubset(set(basis["sources"]))
    assert basis["dimension"] == "system_design"
    assert basis["resume_anchor"]["label"] == "Coupon consistency"
    assert {"value": "Redis", "source": "job_spec"} in basis["target_skills"]
    assert {"value": "Kafka", "source": "resume_parse_audit"} in basis["target_skills"]
    assert "covers_target_skills" in basis["reason_codes"]
    assert captured_trace["selection_artifacts"] == artifacts
