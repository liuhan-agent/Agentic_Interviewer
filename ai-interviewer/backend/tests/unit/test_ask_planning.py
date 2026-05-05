"""Tests for the opt-in LLM ask-planner wired into ``ask_question_node``.

The P0 default path (``runtime_config.ask_planning=False``) is already
covered by ``tests/unit/test_plan_contract_p0.py``; this file focuses
on the P1 opt-in branch that was shipped behind a flag but never
actually hooked up to the node. The integration is:

1. ``ask_planning=True`` + non-stub -> try ``build_llm_ask_plan`` first,
   fall back to :func:`resolve_ask_plan` when it returns ``None``.
2. ``ask_planning=True`` + stub     -> skip the LLM path entirely so
   unit/CI runs stay deterministic.
3. ``ask_planning`` absent / False  -> never call the LLM planner.
"""
from __future__ import annotations

from typing import Any

from app.engine.workflow.nodes import ask_question as ask_mod


def _base_state() -> dict[str, Any]:
    return {
        "session_id": "sess-ap",
        "trace_id": "trace-ap",
        "job_spec": {"title": "Backend Engineer", "level": "senior"},
        "candidate": {"name": "Alex", "resume_parsed": {"highlights": []}},
        "dimensions": ["technical_depth"],
        "dimension_status": {"technical_depth": "active"},
        "current_dimension": "technical_depth",
        "turn_idx": 1,
        "qa_history": [],
        "runtime_config": {},
        "refine_mode": False,
        "current_ask_plan": None,
        "current_contract": None,
        "pending_plan_template": None,
        "pending_contract_hints": None,
        "selected_action": {"id": "deepen_technical"},
    }


def _wire_fake_steps(monkeypatch) -> None:
    """Replace every step-dispatch side effect with cheap stubs.

    The ask-planner tests only care which ``plan`` object flowed into
    ``_run_plan``; the steps themselves are exhaustively covered by
    ``test_plan_contract_p0.py``, so we neutralise them here.
    """

    def fake_retrieve(*, job_spec, dimension, previous_qa, top_k, mode):
        class _Ctx:
            as_prompt_block = "(stub)"

        return _Ctx()

    def fake_retrieve_strategies(**_kwargs):
        return []

    def fake_format_strategies(_entries):
        return "(no relevant strategy memories)"

    def fake_generate_question(**kwargs):
        return {
            "question": "stub question",
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
    monkeypatch.setattr(ask_mod, "retrieve_strategies", fake_retrieve_strategies)
    monkeypatch.setattr(ask_mod, "format_strategies_for_prompt", fake_format_strategies)
    monkeypatch.setattr(ask_mod, "generate_question", fake_generate_question)
    monkeypatch.setattr(ask_mod, "negotiate_contract_via_evaluator", fake_negotiate)


def _force_non_stub(monkeypatch) -> None:
    """Fake ``get_settings().use_stub_llm`` so the planner branch runs.

    The real ``Settings`` object reads ``LLM_PROVIDER`` at import time;
    tests would otherwise have to plumb real API keys to exercise the
    non-stub branch.
    """

    class _S:
        use_stub_llm = False

    monkeypatch.setattr(ask_mod, "get_settings", lambda: _S())


def test_ask_planning_off_never_calls_llm_planner(monkeypatch):
    """The LLM planner must not be consulted when the flag is absent."""
    _wire_fake_steps(monkeypatch)
    _force_non_stub(monkeypatch)

    called: dict[str, int] = {"llm": 0}

    def fail_planner(**_kwargs):
        called["llm"] += 1
        return None

    monkeypatch.setattr(ask_mod, "build_llm_ask_plan", fail_planner)

    state = _base_state()
    out = ask_mod.ask_question_node(state)  # type: ignore[arg-type]

    assert called["llm"] == 0, "planner must be skipped when ask_planning is not set"
    assert out["current_ask_plan"]["source"] == "default"


def test_ask_planning_on_but_stub_skips_llm_planner(monkeypatch):
    """Stub mode always skips the planner so CI stays deterministic."""
    _wire_fake_steps(monkeypatch)

    class _Stub:
        use_stub_llm = True

    monkeypatch.setattr(ask_mod, "get_settings", lambda: _Stub())

    called: dict[str, int] = {"llm": 0}

    def fail_planner(**_kwargs):
        called["llm"] += 1
        return None

    monkeypatch.setattr(ask_mod, "build_llm_ask_plan", fail_planner)

    state = _base_state()
    state["runtime_config"] = {"ask_planning": True}
    out = ask_mod.ask_question_node(state)  # type: ignore[arg-type]

    assert called["llm"] == 0, "planner must be skipped in stub mode"
    assert out["current_ask_plan"]["source"] == "default"


def test_ask_planning_on_uses_llm_plan_when_available(monkeypatch):
    """Non-stub + flag on: the planner's plan is adopted as-is."""
    _wire_fake_steps(monkeypatch)
    _force_non_stub(monkeypatch)

    fabricated: dict[str, Any] = {
        "plan_id": "ask-adaptive-llm-abcdef",
        "template": "adaptive",
        "complexity": "medium",
        "source": "llm",
        "steps": [
            {
                "step_id": 1,
                "kind": "retrieve_rag",
                "goal": "",
                "success_criteria": "",
                "produced_keys": [],
                "dependencies": [],
                "optional": False,
            },
            {
                "step_id": 2,
                "kind": "draft_question",
                "goal": "",
                "success_criteria": "",
                "produced_keys": [],
                "dependencies": [1],
                "optional": False,
            },
            {
                "step_id": 3,
                "kind": "guardrail_check",
                "goal": "",
                "success_criteria": "",
                "produced_keys": [],
                "dependencies": [2],
                "optional": False,
            },
        ],
    }

    def fake_planner(**_kwargs):
        return fabricated

    monkeypatch.setattr(ask_mod, "build_llm_ask_plan", fake_planner)

    state = _base_state()
    state["runtime_config"] = {"ask_planning": True}
    out = ask_mod.ask_question_node(state)  # type: ignore[arg-type]

    assert out["current_ask_plan"]["source"] == "llm"
    assert out["current_ask_plan"]["plan_id"].endswith("abcdef")


def test_ask_planning_falls_back_when_planner_returns_none(monkeypatch):
    """Planner returning ``None`` must degrade to the deterministic resolver."""
    _wire_fake_steps(monkeypatch)
    _force_non_stub(monkeypatch)

    monkeypatch.setattr(ask_mod, "build_llm_ask_plan", lambda **_kw: None)

    state = _base_state()
    state["runtime_config"] = {"ask_planning": True}
    # deepen_technical + refine_mode=False maps to adaptive by the
    # legacy action->template table, regardless of planner status.
    out = ask_mod.ask_question_node(state)  # type: ignore[arg-type]

    assert out["current_ask_plan"]["source"] == "default"
    assert out["current_ask_plan"]["template"] == "adaptive"
