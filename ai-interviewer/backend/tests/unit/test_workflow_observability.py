from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from app.engine.workflow.nodes import turn_finalize as tnode
from app.engine.workflow.nodes import verification as vnode


def test_trace_node_aliases_normalize_compress_context() -> None:
    from app.services.trace_nodes import (
        normalize_trace_node,
        trace_node_aliases,
        trace_node_display_name,
    )

    assert normalize_trace_node("turn_finalize") == "turn_finalize"
    assert normalize_trace_node("compress_context") == "turn_finalize"
    assert "compress_context" in trace_node_aliases("turn_finalize")
    assert trace_node_display_name("turn_finalize") == "轮次收尾"


def test_verification_changes_empty_for_verifier_pass() -> None:
    evaluation = {
        "passed": True,
        "recommended_next": "next_question",
    }
    verification = {
        "verifier_available": True,
        "verdict": "pass",
        "confidence": 0.9,
    }

    updated = vnode._apply_verification(evaluation, verification)
    changes = vnode._verification_changes(evaluation, updated, verification)

    assert changes == []
    assert vnode._verification_effect(True, changes) == "no_change"
    assert vnode._verification_effect(False, changes) == "not_triggered"


def test_verification_changes_describe_low_confidence_soft_warning() -> None:
    evaluation = {
        "passed": True,
        "recommended_next": "next_question",
    }
    for verdict in ["partial", "fail"]:
        verification = {
            "verifier_available": True,
            "verdict": verdict,
            "confidence": 0.1,
            "reasons_to_doubt": ["missing tradeoff evidence"],
        }

        updated = vnode._apply_verification(evaluation, verification)
        changes = vnode._verification_changes(evaluation, updated, verification)

        assert [change["field"] for change in changes] == [
            "soft_warnings",
            "verifier_abstained",
        ]
        assert changes[0]["label"] == "软警告"
        assert changes[0]["after"] == ["missing tradeoff evidence"]
        assert changes[0]["reason"] == "verifier_low_confidence_abstain"
        assert vnode._verification_effect(True, changes) == "soft_warning_only"


def test_verification_changes_describe_high_confidence_partial_override() -> None:
    evaluation = {
        "passed": True,
        "recommended_next": "next_question",
    }
    verification = {
        "verifier_available": True,
        "verdict": "partial",
        "confidence": 0.9,
        "reasons_to_doubt": ["missing operational metrics"],
    }

    updated = vnode._apply_verification(evaluation, verification)
    changes = vnode._verification_changes(evaluation, updated, verification)

    by_field = {change["field"]: change for change in changes}
    assert by_field["passed"]["label"] == "是否通过"
    assert by_field["passed"]["before"] is True
    assert by_field["passed"]["after"] is False
    assert by_field["recommended_next"]["after"] == "refine"
    assert by_field["recommended_next_plan"]["after"] == "deep_probe"
    assert by_field["weaknesses"]["after"] == ["missing operational metrics"]
    assert by_field["passed"]["reason"] == "verifier_high_confidence_partial"
    assert vnode._verification_effect(True, changes) == "overruled_to_refine"


def test_verification_changes_describe_high_confidence_fail_forced_refine() -> None:
    evaluation = {
        "passed": True,
        "recommended_next": "next_question",
    }
    verification = {
        "verifier_available": True,
        "verdict": "fail",
        "confidence": 0.95,
        "reasons_to_doubt": ["answer contradicts evidence"],
    }

    updated = vnode._apply_verification(evaluation, verification)
    changes = vnode._verification_changes(evaluation, updated, verification)

    by_field = {change["field"]: change for change in changes}
    assert by_field["verifier_forced_refine"]["label"] == "强制追问"
    assert by_field["verifier_forced_refine"]["before"] is False
    assert by_field["verifier_forced_refine"]["after"] is True
    assert by_field["verifier_forced_refine"]["reason"] == "verifier_high_confidence_fail"
    assert vnode._verification_effect(True, changes) == "overruled_to_refine"


def test_verification_trace_payload_includes_outcome_metrics(monkeypatch) -> None:
    traced_payloads: list[dict[str, Any]] = []

    class _Tracer:
        def trace_node_event(self, _state, *, node, payload, **_kwargs) -> None:
            if node == "verification":
                traced_payloads.append(payload)

    monkeypatch.setattr(vnode, "get_tracer", lambda: _Tracer())
    monkeypatch.setattr(
        vnode,
        "get_settings",
        lambda: SimpleNamespace(enable_verifier_drift_monitor=False),
    )
    monkeypatch.setattr(vnode, "should_trigger", lambda **_kwargs: True)
    monkeypatch.setattr(
        vnode,
        "verify_answer",
        lambda **_kwargs: {
            "verifier_available": True,
            "verdict": "fail",
            "confidence": 0.95,
            "reasons_to_doubt": ["missing operational metrics"],
        },
    )

    state: dict[str, Any] = {
        "current_question": {
            "dimension": "technical_depth",
            "question": "How would you migrate this safely?",
        },
        "current_contract": {
            "bar_level": "standard",
            "acceptance_checks": ["Mentions rollback."],
        },
        "current_answer": "I would use a canary rollout.",
        "evaluation": {
            "score": 8.0,
            "passed": True,
            "recommended_next": "next_question",
        },
        "dimension_status": {"technical_depth": "passed"},
        "job_spec": {"level": "senior"},
        "quality_threshold": 7.5,
    }

    out = vnode.verification_node(state)  # type: ignore[arg-type]

    assert out["evaluation"]["passed"] is False
    assert out["dimension_status"]["technical_depth"] == "active"
    assert traced_payloads[-1]["evaluator_passed"] is True
    assert traced_payloads[-1]["updated_passed"] is False
    assert traced_payloads[-1]["verdict_changed"] is True
    assert traced_payloads[-1]["verifier_abstained"] is False
    assert traced_payloads[-1]["verification_effect"] == "overruled_to_refine"
    assert traced_payloads[-1]["verification_change_count"] >= 1
    assert {
        change["field"] for change in traced_payloads[-1]["verification_changes"]
    } >= {
        "passed",
        "recommended_next",
        "recommended_next_plan",
        "weaknesses",
        "verifier_forced_refine",
    }


def test_turn_finalize_traces_route_decision_after_eval(monkeypatch) -> None:
    traced: list[tuple[str, dict[str, Any], int | None]] = []

    class _Tracer:
        def trace_node_event(
            self,
            _state,
            *,
            node,
            payload,
            logical_turn_idx=None,
            **_kwargs,
        ) -> None:
            traced.append((node, payload, logical_turn_idx))

    monkeypatch.setattr(tnode, "get_tracer", lambda: _Tracer())

    state: dict[str, Any] = {
        "turn_idx": 2,
        "formal_turn_idx": 2,
        "max_turns": 6,
        "turn_budget_remaining": 4,
        "current_dimension": "system_design",
        "dimensions": ["system_design", "communication"],
        "dimension_status": {"system_design": "active", "communication": "pending"},
        "evaluation": {
            "passed": False,
            "recommended_next": "refine",
        },
        "qa_history": [
            {
                "turn_idx": 1,
                "dimension": "system_design",
                "evaluation": {"passed": False},
            }
        ],
    }

    tnode.turn_finalize_node(state)  # type: ignore[arg-type]

    finalize_events = [item for item in traced if item[0] == "turn_finalize"]
    assert finalize_events
    _node, finalize_payload, finalize_logical_turn_idx = finalize_events[-1]
    assert finalize_payload["phase"] == "turn_finalize"
    assert finalize_payload["reason"] == "turn_finalize"
    assert finalize_payload["workflow_node"] == "turn_finalize"
    assert finalize_payload["semantic_node"] == "turn_finalize"
    assert finalize_payload["node_aliases"] == ["compress_context"]
    assert finalize_payload["display_name_zh"] == "轮次收尾"
    assert finalize_payload["raw_answer_cleared"] is False
    assert finalize_payload["summary_updated"] is False
    assert finalize_payload["summary_mode"] == "none"
    assert finalize_payload["history_projection_owner"] == "ask_question"
    assert finalize_payload["compressed_turns"] == 0
    assert finalize_payload["qa_history_count"] == 1
    assert finalize_payload["next_step"] == "route_decision"
    assert finalize_logical_turn_idx == 1

    route_events = [item for item in traced if item[0] == "route_decision"]
    assert route_events
    _node, payload, logical_turn_idx = route_events[-1]
    assert payload["router"] == "route_after_eval"
    assert payload["decision"] == "refine"
    assert payload["recommended_next"] == "refine"
    assert payload["passed"] is False
    assert payload["dimension"] == "system_design"
    assert payload["next_node"] == "refine_followup"
    assert payload["decision_reason"] == "evaluator_recommended_refine"
    assert payload["recommended_next_plan"] is None
    assert payload["recommended_probe_intent"] is None
    assert payload["evaluation_source"] is None
    assert payload["fallback_reason"] is None
    assert payload["decision_inputs"]["all_dimensions_done"] is False
    assert payload["decision_inputs"]["coverage_advance"] is False
    assert payload["decision_inputs"]["current_dimension_attempts"] == 1
    assert payload["decision_inputs"]["max_refines_per_dimension"] == 2
    assert payload["decision_inputs"]["has_pending_other_dimension"] is True
    assert logical_turn_idx == 1


def test_turn_finalize_trace_payload_never_updates_history_projection(
    monkeypatch,
) -> None:
    traced: list[tuple[str, dict[str, Any], int | None]] = []

    class _Tracer:
        def trace_node_event(
            self,
            _state,
            *,
            node,
            payload,
            logical_turn_idx=None,
            **_kwargs,
        ) -> None:
            traced.append((node, payload, logical_turn_idx))

    monkeypatch.setattr(tnode, "get_tracer", lambda: _Tracer())

    base_state: dict[str, Any] = {
        "turn_idx": 4,
        "formal_turn_idx": 4,
        "max_turns": 6,
        "turn_budget_remaining": 2,
        "current_dimension": "system_design",
        "dimensions": ["system_design"],
        "dimension_status": {"system_design": "active"},
        "evaluation": {"passed": False, "recommended_next": "refine"},
        "qa_summary": "",
        "qa_summary_through_turn": -1,
        "qa_history": [
            {"turn_idx": 0, "dimension": "system_design", "evaluation": {"score": 6}},
            {"turn_idx": 1, "dimension": "system_design", "evaluation": {"score": 7}},
            {"turn_idx": 2, "dimension": "system_design", "evaluation": {"score": 8}},
            {"turn_idx": 3, "dimension": "system_design", "evaluation": {"score": 9}},
        ],
    }

    out = tnode.turn_finalize_node(base_state)  # type: ignore[arg-type]
    assert "qa_summary" not in out
    assert "qa_summary_through_turn" not in out
    finalize_events = [item for item in traced if item[0] == "turn_finalize"]
    assert finalize_events[-1][1]["reason"] == "turn_finalize"
    assert finalize_events[-1][1]["summary_updated"] is False
    assert finalize_events[-1][1]["summary_mode"] == "none"
    assert finalize_events[-1][1]["history_projection_owner"] == "ask_question"
    assert finalize_events[-1][1]["compressed_turns"] == 0
    assert finalize_events[-1][2] == 3

    traced.clear()
    no_new_state = {**base_state, "qa_summary": "already", "qa_summary_through_turn": 1}
    out = tnode.turn_finalize_node(no_new_state)  # type: ignore[arg-type]
    assert "qa_summary" not in out
    assert "qa_summary_through_turn" not in out
    finalize_events = [item for item in traced if item[0] == "turn_finalize"]
    assert finalize_events[-1][1]["reason"] == "turn_finalize"
    assert finalize_events[-1][1]["summary_updated"] is False
    assert finalize_events[-1][1]["history_projection_owner"] == "ask_question"
