"""P0 regression tests for the Plan + Contract integration.

Covers:
- Default plan templates are well-formed.
- ``ask_question_node`` runs the plan and writes ``current_contract``
  / ``current_ask_plan``.
- ``evaluator_agent.evaluate_answer`` consumes a contract and emits
  ``acceptance_check_results`` + ``recommended_next_plan``.
- ``refine_followup_node`` translates the evaluator suggestion into
  ``pending_plan_template`` / ``pending_contract_hints``.
- ``director_sample_node`` surfaces the pending template as a hint
  on ``selected_action.plan_template_hint`` and leaves the template
  field on state untouched for ``ask_question_node`` to consume.
- Legacy ``runtime_config.iterative_contract`` still produces a
  usable contract even without pending_plan_template.
"""
from __future__ import annotations

import json
import random
from typing import Any

import pytest

from app.engine.workflow.nodes import refine_followup as refine_mod
from app.engine.workflow.nodes.director_sample import director_sample_node
from app.engine.workflow.nodes.refine_followup import refine_followup_node
from app.engine.workflow.plans import PLAN_TEMPLATES, resolve_ask_plan
from app.ml.rl import thompson as thompson_mod


def _install_zero_exploration_bandit(monkeypatch) -> None:
    bandit = thompson_mod.ThompsonBandit(exploration_rate=0.0, rng=random.Random(0))
    monkeypatch.setattr(thompson_mod, "_singleton", bandit, raising=False)


def _base_state() -> dict[str, Any]:
    return {
        "session_id": "sess-p0",
        "trace_id": "trace-p0",
        "job_spec": {"title": "Backend Engineer", "level": "mid"},
        "candidate": {"name": "Alex", "resume_parsed": {"highlights": []}},
        "dimensions": ["technical_depth", "communication"],
        "dimension_status": {"technical_depth": "active", "communication": "pending"},
        "current_dimension": "technical_depth",
        "turn_idx": 1,
        "qa_history": [],
        "runtime_config": {},
        "refine_mode": False,
        "current_ask_plan": None,
        "current_contract": None,
        "pending_plan_template": None,
        "pending_contract_hints": None,
    }


# ---------------------------------------------------------------------------
# 1. Plan templates
# ---------------------------------------------------------------------------


def test_ask_plan_templates_exist_and_have_steps():
    assert set(PLAN_TEMPLATES.keys()) == {
        "simple",
        "quick_review",
        "adaptive",
        "deep_probe",
    }
    for name, spec in PLAN_TEMPLATES.items():
        steps = spec.get("steps")
        assert steps, f"template {name} has no steps"
        kinds = [s.get("kind") for s in steps]
        assert kinds[-1] == "guardrail_check", (
            f"template {name} must end with guardrail_check, got {kinds}"
        )
        if name in {"adaptive", "deep_probe"}:
            assert "negotiate_contract" in kinds, (
                f"template {name} must include negotiate_contract"
            )
        if name in {"simple", "quick_review"}:
            assert "negotiate_contract" not in kinds, (
                f"{name} plan must skip negotiate_contract"
            )


def test_resolve_ask_plan_prefers_pending_template():
    plan = resolve_ask_plan(
        selected_action={"id": "deepen_technical"},
        refine_mode=False,
        pending_plan_template="deep_probe",
        runtime_config={},
    )
    assert plan["template"] == "deep_probe"


def test_resolve_ask_plan_uses_action_mapping():
    plan = resolve_ask_plan(
        selected_action={"id": "give_hint"},
        refine_mode=False,
        pending_plan_template=None,
        runtime_config={},
    )
    assert plan["template"] == "simple"

    plan2 = resolve_ask_plan(
        selected_action={"id": "deepen_technical"},
        refine_mode=True,
        pending_plan_template=None,
        runtime_config={},
    )
    assert plan2["template"] == "deep_probe"


def test_resolve_ask_plan_legacy_flag_maps_to_adaptive():
    plan = resolve_ask_plan(
        selected_action=None,
        refine_mode=False,
        pending_plan_template=None,
        runtime_config={"iterative_contract": True},
    )
    assert plan["template"] == "adaptive"


def test_contract_diagnostics_accepts_evaluator_signed_contract():
    from app.engine.workflow.nodes import ask_question as ask_mod

    contract = {
        "must_cover": ["zero-downtime", "rollback plan"],
        "acceptance_checks": [
            "Answer explains zero-downtime migration.",
            "Answer includes a rollback plan.",
        ],
        "bar_level": "standard",
        "signed_by": ["generator", "evaluator"],
    }

    diagnostics = ask_mod._contract_diagnostics_for_trace(
        contract,
        proposed_contract=contract,
        plan={"template": "adaptive"},
        target_difficulty="medium",
        rewrite_fallback=False,
    )

    assert diagnostics["source"] == "evaluator_signed"
    assert diagnostics["signed_status"] == "evaluator_signed"
    assert diagnostics["bar_level_match"] is True
    assert diagnostics["uncovered_must_cover_items"] == []
    assert diagnostics["generic_items"] == []
    assert diagnostics["warnings"] == []


def test_contract_diagnostics_flags_generator_only_and_generic_items():
    from app.engine.workflow.nodes import ask_question as ask_mod

    contract = {
        "must_cover": ["depth", "clarity"],
        "acceptance_checks": ["Answer has enough depth."],
        "bar_level": "intro",
        "signed_by": ["generator"],
    }

    diagnostics = ask_mod._contract_diagnostics_for_trace(
        contract,
        proposed_contract=contract,
        plan={"template": "simple"},
        target_difficulty="easy",
        rewrite_fallback=False,
    )

    assert diagnostics["source"] == "generator_only"
    assert diagnostics["signed_status"] == "generator_only"
    assert "not_evaluator_signed" in diagnostics["warnings"]
    assert "generic_contract_item" in diagnostics["warnings"]
    assert diagnostics["generic_items"] == ["depth", "clarity"]


def test_contract_diagnostics_reports_uncovered_must_cover_and_bar_mismatch():
    from app.engine.workflow.nodes import ask_question as ask_mod

    contract = {
        "must_cover": ["latency budget", "backpressure"],
        "acceptance_checks": ["Answer mentions backpressure handling."],
        "bar_level": "standard",
        "signed_by": ["generator", "evaluator"],
    }

    diagnostics = ask_mod._contract_diagnostics_for_trace(
        contract,
        proposed_contract=contract,
        plan={"template": "deep_probe"},
        target_difficulty="hard",
        rewrite_fallback=False,
    )

    assert diagnostics["expected_bar_level"] == "deep_probe"
    assert diagnostics["bar_level_match"] is False
    assert diagnostics["uncovered_must_cover_items"] == ["latency budget"]
    assert "must_cover_without_acceptance_check" in diagnostics["warnings"]
    assert "bar_level_mismatch" in diagnostics["warnings"]


def test_contract_diagnostics_accepts_semantically_aligned_chinese_checks():
    from app.engine.workflow.nodes import ask_question as ask_mod

    contract = {
        "must_cover": [
            "用户侧可理解的事实和影响",
            "研发恢复与补偿计划（含时间线）",
            "最终一致性延迟对用户体验的具体影响",
            "引用项目MQ具体机制（如延迟队列、幂等、死信、补偿）",
        ],
        "acceptance_checks": [
            "YES: 明确区分客服口径和技术恢复计划",
            "YES: 给出具体时间线和补偿机制（如手动补单或对账）",
            "YES: 引用项目中的MQ具体机制（如延迟队列、幂等、死信、补偿）",
            "YES: 说明最终一致性延迟对用户的具体影响（如用户看到订单未确认但实际已扣款）",
        ],
        "bar_level": "deep_probe",
        "signed_by": ["generator", "evaluator"],
    }

    diagnostics = ask_mod._contract_diagnostics_for_trace(
        contract,
        proposed_contract=contract,
        plan={"template": "adaptive"},
        target_difficulty="hard",
        rewrite_fallback=False,
    )

    assert diagnostics["uncovered_must_cover_items"] == []
    assert "must_cover_without_acceptance_check" not in diagnostics["warnings"]


def test_contract_diagnostics_marks_rewrite_fallback_source():
    from app.engine.workflow.nodes import ask_question as ask_mod

    contract = {
        "must_cover": ["具体项目证据", "方案取舍"],
        "acceptance_checks": [
            "回答包含具体项目证据。",
            "回答说明方案取舍。",
        ],
        "bar_level": "standard",
        "signed_by": ["generator"],
    }

    diagnostics = ask_mod._contract_diagnostics_for_trace(
        contract,
        proposed_contract={"must_cover": ["stale"]},
        plan={"template": "adaptive"},
        target_difficulty="medium",
        rewrite_fallback=True,
    )

    assert diagnostics["source"] == "rewrite_fallback"
    assert "rewrite_fallback" in diagnostics["warnings"]


def test_contract_negotiator_enforces_target_difficulty_bar_level(monkeypatch):
    from app.engine.agents import contract as contract_mod

    def fake_call_chat(*args, **kwargs):
        return json.dumps(
            {
                "must_cover": ["恢复计划", "用户影响"],
                "acceptance_checks": [
                    "YES: 给出恢复计划",
                    "YES: 说明用户影响",
                ],
                "minimum_bar": "覆盖恢复计划和用户影响。",
                "review_focus": ["恢复计划"],
                "bar_level": "standard",
            },
            ensure_ascii=False,
        )

    monkeypatch.setattr(contract_mod, "call_chat", fake_call_chat)

    contract = contract_mod.negotiate_contract_via_evaluator(
        dimension="communication",
        job_level="junior",
        question="请说明 MQ 积压时如何对客服说明用户影响和恢复计划。",
        proposed_contract={
            "must_cover": ["恢复计划", "用户影响"],
            "acceptance_checks": ["说明恢复计划", "说明用户影响"],
            "bar_level": "standard",
        },
        contract_hints={},
        target_difficulty="hard",
    )

    assert contract["signed_by"] == ["generator", "evaluator"]
    assert contract["bar_level"] == "deep_probe"


# ---------------------------------------------------------------------------
# 2. ask_question_node (via stub LLM)
# ---------------------------------------------------------------------------


def test_ask_question_writes_plan_and_contract(monkeypatch):
    """Drive the plan executor with a stub LLM and assert state writes."""
    from app.engine.workflow.nodes import ask_question as ask_mod

    def fake_retrieve(*, job_spec, dimension, previous_qa, top_k, mode):
        class _Ctx:
            as_prompt_block = "(stub retrieval)"

        return _Ctx()

    def fake_retrieve_strategies(**kwargs):
        return []

    def fake_format_strategies(entries):
        return "(no relevant strategy memories)"

    def fake_generate_question(**kwargs):
        return {
            "question": "请说明你如何在大规模系统中处理 schema migration。",
            "dimension": kwargs["dimension"],
            "rubric_points": ["zero-downtime", "rollback plan"],
            "difficulty": "medium",
            "rationale": "probes operational depth",
            "proposed_contract": {
                "must_cover": ["zero-downtime", "rollback plan"],
                "acceptable_if_missing": [],
                "acceptance_checks": [
                    "Discusses zero-downtime strategies.",
                    "Mentions a rollback plan.",
                ],
                "minimum_bar": "Names one zero-downtime technique.",
                "review_focus": ["rollback plan"],
                "bar_level": "standard",
            },
        }

    def fake_negotiate(**kwargs):
        return {
            **kwargs["proposed_contract"],
            "signed_by": ["generator", "evaluator"],
        }

    monkeypatch.setattr(ask_mod, "retrieve_for_question", fake_retrieve)
    monkeypatch.setattr(ask_mod, "retrieve_strategies", fake_retrieve_strategies)
    monkeypatch.setattr(
        ask_mod, "format_strategies_for_prompt", fake_format_strategies
    )
    monkeypatch.setattr(ask_mod, "generate_question", fake_generate_question)
    monkeypatch.setattr(
        ask_mod, "negotiate_contract_via_evaluator", fake_negotiate
    )
    traced_payloads: list[dict[str, Any]] = []

    class _Tracer:
        def trace_node_event(self, _state, *, node, payload, **_kwargs):
            if node == "ask_question":
                traced_payloads.append(payload)

    monkeypatch.setattr(ask_mod, "get_tracer", lambda: _Tracer())

    state = _base_state()
    state["selected_action"] = {"id": "deepen_technical"}  # -> adaptive

    out = ask_mod.ask_question_node(state)  # type: ignore[arg-type]

    assert out["current_ask_plan"]["template"] == "adaptive"
    assert out["current_contract"]["signed_by"] == ["generator", "evaluator"]
    question_payload = out["current_question"]
    assert "contract" in question_payload
    assert question_payload["contract"]["signed_by"] == ["generator", "evaluator"]
    assert out["pending_plan_template"] is None
    assert out["pending_contract_hints"] is None
    assert traced_payloads[-1]["contract_must_cover_count"] == 2
    assert traced_payloads[-1]["contract_acceptance_check_count"] == 2
    assert traced_payloads[-1]["contract_bar_level"] == "standard"
    assert traced_payloads[-1]["contract"]["must_cover"] == [
        "zero-downtime",
        "rollback plan",
    ]
    assert traced_payloads[-1]["contract_diagnostics"]["source"] == "evaluator_signed"
    assert traced_payloads[-1]["contract_diagnostics"]["warnings"] == []


def test_ask_question_passes_probe_intent_into_generator(monkeypatch):
    """Probe intent must shape generation, not only decorate the result."""
    from app.engine.workflow.nodes import ask_question as ask_mod

    captured: dict[str, Any] = {}

    def fake_retrieve(*, job_spec, dimension, previous_qa, top_k, mode):
        class _Ctx:
            as_prompt_block = "(stub)"

        return _Ctx()

    def fake_generate_question(**kwargs):
        captured.update(kwargs)
        return {
            "question": "Walk me through the architecture trade-off.",
            "dimension": kwargs["dimension"],
            "rubric_points": ["trade-off"],
            "proposed_contract": {
                "must_cover": ["trade-off"],
                "acceptance_checks": ["Names a trade-off."],
                "minimum_bar": "One concrete trade-off.",
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
    monkeypatch.setattr(
        ask_mod,
        "resolve_probe_intent",
        lambda **_kwargs: "architecture_challenge",
    )

    state = _base_state()
    state["job_spec"]["interview_direction"] = "java_backend"
    state["current_dimension"] = "system_design"
    state["dimensions"] = ["system_design"]
    state["dimension_status"] = {"system_design": "active"}
    state["selected_action"] = {"id": "deepen_technical"}

    out = ask_mod.ask_question_node(state)  # type: ignore[arg-type]

    assert captured["probe_intent"] == "architecture_challenge"
    assert out["current_question"]["probe_intent"] == "architecture_challenge"


def test_ask_question_uses_coverage_closeout_when_turn_budget_is_tight(monkeypatch):
    """Coverage pressure should shape the question without adding a plan template."""
    from app.engine.workflow.nodes import ask_question as ask_mod

    captured: dict[str, Any] = {}

    def fake_retrieve(*, job_spec, dimension, previous_qa, top_k, mode):
        class _Ctx:
            as_prompt_block = "(stub)"

        return _Ctx()

    def fake_generate_question(**kwargs):
        captured.update(kwargs)
        return {
            "question": "Quickly cover this remaining dimension.",
            "dimension": kwargs["dimension"],
            "rubric_points": ["baseline"],
            "proposed_contract": {
                "must_cover": ["baseline"],
                "acceptance_checks": ["Covers the baseline."],
                "minimum_bar": "One direct answer.",
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

    state = _base_state()
    state["job_spec"]["interview_direction"] = "java_backend"
    state["dimensions"] = ["technical_depth", "system_design", "communication"]
    state["current_dimension"] = "technical_depth"
    state["dimension_status"] = {
        "technical_depth": "active",
        "system_design": "pending",
        "communication": "pending",
    }
    state["turn_budget_remaining"] = 2
    state["selected_action"] = {"id": "deepen_technical"}

    out = ask_mod.ask_question_node(state)  # type: ignore[arg-type]

    assert out["current_ask_plan"]["template"] == "adaptive"
    assert captured["probe_intent"] == "coverage_closeout"
    assert out["current_question"]["probe_intent"] == "coverage_closeout"
    assert out["pending_contract_hints"] is None


def test_ask_question_simple_plan_is_generator_only_signed(monkeypatch):
    """Simple plan skips negotiation -> contract signed by generator only."""
    from app.engine.workflow.nodes import ask_question as ask_mod

    captured: dict[str, Any] = {}

    def fake_retrieve(*, job_spec, dimension, previous_qa, top_k, mode):
        class _Ctx:
            as_prompt_block = "(stub)"

        return _Ctx()

    def fail_retrieve_strategies(**_kwargs):
        pytest.fail("simple plan must not retrieve strategy memories")

    def fake_generate_question(**kwargs):
        captured.update(kwargs)
        return {
            "question": "Walk me through a recent project.",
            "dimension": kwargs["dimension"],
            "rubric_points": ["depth"],
            "proposed_contract": {
                "must_cover": ["depth"],
                "acceptance_checks": ["Names a concrete project."],
                "minimum_bar": "One concrete example.",
                "bar_level": "intro",
            },
        }

    def fake_negotiate(**kwargs):
        pytest.fail("simple plan must not call negotiate_contract")

    monkeypatch.setattr(ask_mod, "retrieve_for_question", fake_retrieve)
    monkeypatch.setattr(ask_mod, "retrieve_strategies", fail_retrieve_strategies)
    monkeypatch.setattr(
        ask_mod,
        "retrieve_skills",
        lambda **_kwargs: [object()],
    )
    monkeypatch.setattr(
        ask_mod,
        "build_skills_block",
        lambda _entries: "skill playbook guidance",
    )
    monkeypatch.setattr(ask_mod, "generate_question", fake_generate_question)
    monkeypatch.setattr(
        ask_mod, "negotiate_contract_via_evaluator", fake_negotiate
    )

    state = _base_state()
    state["selected_action"] = {"id": "give_hint"}  # -> simple

    out = ask_mod.ask_question_node(state)  # type: ignore[arg-type]
    assert out["current_ask_plan"]["template"] == "simple"
    assert out["current_contract"]["signed_by"] == ["generator"]
    assert captured["skill_block"] == "skill playbook guidance"


# ---------------------------------------------------------------------------
# 3. evaluator_agent
# ---------------------------------------------------------------------------


def test_evaluator_reads_contract_and_emits_acceptance_checks(monkeypatch):
    from app.engine.agents import evaluator_agent as eval_mod

    captured: dict[str, Any] = {}

    def fake_call(messages, *, json_mode=False, **kwargs):
        captured["json_mode"] = json_mode
        captured["messages"] = messages
        return (
            '{"score": 8.2, "passed": true, '
            '"strengths": ["clear"], "weaknesses": [], '
            '"acceptance_check_results": {'
            '"Discusses zero-downtime strategies.": "yes", '
            '"Mentions a rollback plan.": "partial"}, '
            '"recommended_next": "advance", '
            '"recommended_next_plan": "adaptive", '
            '"rationale": "solid answer"}'
        )

    monkeypatch.setattr(eval_mod, "call_chat", fake_call)

    contract = {
        "must_cover": ["zero-downtime", "rollback plan"],
        "acceptance_checks": [
            "Discusses zero-downtime strategies.",
            "Mentions a rollback plan.",
        ],
        "minimum_bar": "Names one zero-downtime technique.",
        "bar_level": "standard",
        "signed_by": ["generator", "evaluator"],
    }

    result = eval_mod.evaluate_answer(
        dimension="technical_depth",
        question="How do you handle schema migrations at scale?",
        rubric_points=["zero-downtime", "rollback plan"],
        answer="We use shadow tables and backfills...",
        quality_threshold=7.5,
        contract=contract,
    )

    assert captured["json_mode"] is True
    assert result["passed"] is True
    assert result["recommended_next_plan"] == "adaptive"
    # The stub above returns the **legacy** string shape
    # (``"yes" / "partial"``); ``_normalize_check_result`` must
    # upgrade it to the canonical dict shape so the rest of the pipeline
    # (Verifier, final_report) sees a uniform structure regardless of what
    # the model actually emitted. ``evidence_spans`` is additive and may be
    # absent when EVIDENCE_SPAN_ALIGNMENT=false in CI.
    acceptance = result["acceptance_check_results"]
    assert acceptance["Discusses zero-downtime strategies."]["verdict"] == "yes"
    assert acceptance["Discusses zero-downtime strategies."]["evidence"] == []
    assert acceptance["Discusses zero-downtime strategies."].get("evidence_spans", []) == []
    assert acceptance["Mentions a rollback plan."]["verdict"] == "partial"
    assert acceptance["Mentions a rollback plan."]["evidence"] == []
    assert acceptance["Mentions a rollback plan."].get("evidence_spans", []) == []
    # derived rubric coverage must reflect acceptance check outcomes
    # (still works because ``_derive_rubric_coverage`` goes through
    # ``_verdict_of``, not raw string comparison).
    assert result["rubric_coverage"]["zero-downtime"] == "covered"
    assert result["rubric_coverage"]["rollback plan"] == "partial"


def test_evaluator_legacy_path_without_contract(monkeypatch):
    """Old callers that pass only rubric_points still work; new fields empty."""
    from app.engine.agents import evaluator_agent as eval_mod

    def fake_call(messages, *, json_mode=False, **kwargs):
        return '{"score": 4.0, "passed": false, "recommended_next": "refine"}'

    monkeypatch.setattr(eval_mod, "call_chat", fake_call)

    result = eval_mod.evaluate_answer(
        dimension="communication",
        question="Tell me about a time you disagreed with a teammate.",
        rubric_points=["conflict resolution", "empathy"],
        answer="",
        quality_threshold=7.5,
    )

    assert result["passed"] is False
    assert result["recommended_next"] == "refine"
    assert result["recommended_next_plan"] is None
    assert result["acceptance_check_results"] == {}


def test_evaluator_keeps_probe_intent_fields(monkeypatch):
    from app.engine.agents import evaluator_agent as eval_mod

    def fake_call(messages, *, json_mode=False, **kwargs):
        return (
            '{"score": 5.0, "passed": false, "recommended_next": "refine", '
            '"recommended_next_plan": "adaptive", '
            '"recommended_probe_intent": "metric_probe", '
            '"failure_reason": "answer lacks metrics"}'
        )

    monkeypatch.setattr(eval_mod, "call_chat", fake_call)

    result = eval_mod.evaluate_answer(
        dimension="metrics_thinking",
        question="How did you measure success?",
        rubric_points=["metric definition"],
        answer="We looked at whether users liked it.",
        quality_threshold=7.5,
    )

    assert result["recommended_next_plan"] == "adaptive"
    assert result["recommended_probe_intent"] == "metric_probe"
    assert result["failure_reason"] == "answer lacks metrics"


def test_evaluator_node_attaches_followup_reason_after_consistency(monkeypatch):
    from app.engine.workflow.nodes import evaluator as eval_node_mod

    captured: dict[str, Any] = {}

    def fake_evaluate_answer(**_kwargs):
        return {
            "score": 5.0,
            "passed": True,
            "rationale": "The answer names Redis but does not size capacity.",
            "strengths": ["Names Redis"],
            "weaknesses": ["Capacity estimate is thin"],
            "rubric_coverage": {"Capacity estimate": "missing"},
            "recommended_next": "advance",
            "recommended_next_plan": "deep_probe",
            "recommended_probe_intent": "evidence_probe",
            "acceptance_check_results": {},
        }

    class _Tracer:
        def trace_evaluator(self, state, **_kwargs):
            captured["trace_evaluation"] = state["evaluation"]

    monkeypatch.setattr(eval_node_mod, "evaluate_answer", fake_evaluate_answer)
    monkeypatch.setattr(eval_node_mod, "get_tracer", lambda: _Tracer())

    state = _base_state()
    state.update(
        {
            "current_question": {
                "question": "How would you size Redis capacity?",
                "dimension": "technical_depth",
                "rubric_points": ["Capacity estimate"],
            },
            "current_answer": "Use Redis for hot reads.",
            "selected_action": {"id": "deepen_technical"},
            "scores_per_dim": {},
            "turn_budget_remaining": 2,
            "quality_threshold": 7.5,
        }
    )

    out = eval_node_mod.evaluator_node(state)  # type: ignore[arg-type]

    reason = out["evaluation"]["followup_reason"]
    assert out["evaluation"]["recommended_next"] == "refine"
    assert reason["title"] == "为什么继续追问"
    assert "Capacity estimate" in reason["summary"]
    assert "补充证据" in reason["chips"]
    assert captured["trace_evaluation"]["followup_reason"] == reason


def test_evaluator_node_persists_question_basis_in_qa_history(monkeypatch):
    from app.engine.workflow.nodes import evaluator as eval_node_mod

    question_basis = {
        "title": "为什么问这一题",
        "summary": "这题结合了简历中的支付迁移项目，并围绕技术深度确认 Redis。",
        "chips": ["来自简历", "评分维度", "技术深度", "Redis"],
    }

    def fake_evaluate_answer(**_kwargs):
        return {
            "score": 8.0,
            "passed": True,
            "rationale": "Clear answer.",
            "strengths": ["Concrete"],
            "weaknesses": [],
            "recommended_next": "advance",
            "acceptance_check_results": {},
        }

    class _Tracer:
        def trace_evaluator(self, _state, **_kwargs):
            return None

    monkeypatch.setattr(eval_node_mod, "evaluate_answer", fake_evaluate_answer)
    monkeypatch.setattr(eval_node_mod, "get_tracer", lambda: _Tracer())

    state = _base_state()
    state.update(
        {
            "current_question": {
                "question": "How did you use Redis in the payment migration?",
                "dimension": "technical_depth",
                "rubric_points": ["Redis"],
                "question_basis": question_basis,
            },
            "current_answer": "I used Redis for hot reads.",
            "selected_action": {"id": "deepen_technical"},
            "scores_per_dim": {},
            "turn_budget_remaining": 2,
            "quality_threshold": 7.5,
        }
    )

    out = eval_node_mod.evaluator_node(state)  # type: ignore[arg-type]

    assert out["qa_history"][0]["question_basis"] == question_basis


# ---------------------------------------------------------------------------
# 4. refine_followup_node
# ---------------------------------------------------------------------------


def test_refine_followup_writes_pending_plan_template():
    state = _base_state()
    state["evaluation"] = {
        "score": 5.0,
        "passed": False,
        "weaknesses": ["missed quantification", "no rollback plan"],
        "rubric_coverage": {
            "zero-downtime": "partial",
            "rollback plan": "missing",
        },
        "recommended_next_plan": "deep_probe",
    }
    out = refine_followup_node(state)  # type: ignore[arg-type]
    assert out["refine_mode"] is True
    assert out["pending_plan_template"] == "deep_probe"
    hints = out["pending_contract_hints"]
    assert "missed quantification" in hints["must_address"]
    assert "rollback plan" in hints["missing_must_cover"]


def test_refine_followup_trace_payload_includes_pending_hints(monkeypatch):
    traced: list[dict[str, Any]] = []

    class _Tracer:
        def trace_node_event(self, _state, *, node, payload, **_kwargs):
            if node == "refine_followup":
                traced.append(dict(payload))

    monkeypatch.setattr(refine_mod, "get_tracer", lambda: _Tracer())

    state = _base_state()
    state["evaluation"] = {
        "score": 5.0,
        "passed": False,
        "weaknesses": ["missed quantification"],
        "rubric_coverage": {"rollback plan": "missing"},
        "recommended_next_plan": "adaptive",
        "recommended_probe_intent": "metric_probe",
        "failure_reason": "answer lacks metrics",
        "failure_categories": ["missing_metrics"],
        "soft_warnings": ["weak evidence quote"],
    }

    out = refine_followup_node(state)  # type: ignore[arg-type]

    assert traced
    payload = traced[-1]
    assert payload["refine_mode"] is True
    assert payload["pending_plan_template"] == out["pending_plan_template"]
    assert payload["pending_contract_hints"] == out["pending_contract_hints"]
    assert payload["must_address_count"] == 1
    assert payload["missing_must_cover_count"] == 1
    assert payload["failure_categories"] == ["missing_metrics"]
    assert payload["probe_intent"] == "metric_probe"
    assert payload["failure_reason"] == "answer lacks metrics"
    assert payload["prior_soft_warnings"] == ["weak evidence quote"]


def test_refine_followup_carries_probe_intent_hints():
    state = _base_state()
    state["evaluation"] = {
        "score": 5.0,
        "passed": False,
        "weaknesses": ["no metric definition"],
        "recommended_next_plan": "adaptive",
        "recommended_probe_intent": "metric_probe",
        "failure_reason": "answer lacks metrics",
    }

    out = refine_followup_node(state)  # type: ignore[arg-type]

    hints = out["pending_contract_hints"]
    assert out["pending_plan_template"] == "adaptive"
    assert hints["probe_intent"] == "metric_probe"
    assert hints["failure_reason"] == "answer lacks metrics"


def test_refine_followup_normalizes_failure_category_and_probe_intent():
    state = _base_state()
    state["job_spec"]["interview_direction"] = "product_manager"
    state["current_dimension"] = "metrics_thinking"
    state["evaluation"] = {
        "score": 5.0,
        "passed": False,
        "weaknesses": ["没有定义核心指标"],
        "recommended_next_plan": "adaptive",
        "failure_reason": "answer lacks metrics",
    }

    out = refine_followup_node(state)  # type: ignore[arg-type]

    hints = out["pending_contract_hints"]
    assert out["pending_plan_template"] == "adaptive"
    assert hints["failure_category"] == "missing_metrics"
    assert hints["probe_intent"] == "metric_probe"
    assert hints["failure_reason"] == "answer lacks metrics"


def test_refine_followup_defaults_to_deep_probe_when_missing():
    state = _base_state()
    state["evaluation"] = {"passed": False, "weaknesses": []}
    out = refine_followup_node(state)  # type: ignore[arg-type]
    assert out["pending_plan_template"] == "deep_probe"


# ---------------------------------------------------------------------------
# 5. director_sample_node keeps pending_plan_template for ask_question
# ---------------------------------------------------------------------------


def test_director_surfaces_plan_template_hint(monkeypatch):
    _install_zero_exploration_bandit(monkeypatch)

    state = _base_state()
    state["pending_plan_template"] = "deep_probe"
    state["refine_mode"] = True

    out = director_sample_node(state)  # type: ignore[arg-type]
    action = out["selected_action"]
    assert action["plan_template_hint"] == "deep_probe"
    # director must NOT clear pending_plan_template; that's ask_question's job.
    assert "pending_plan_template" not in out
