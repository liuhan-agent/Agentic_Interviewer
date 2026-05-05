from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from app.engine.workflow.nodes import compress_context as cnode
from app.engine.workflow.nodes import verification as vnode


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
        "job_spec": {"level": "senior"},
        "quality_threshold": 7.5,
    }

    out = vnode.verification_node(state)  # type: ignore[arg-type]

    assert out["evaluation"]["passed"] is False
    assert traced_payloads[-1]["evaluator_passed"] is True
    assert traced_payloads[-1]["updated_passed"] is False
    assert traced_payloads[-1]["verdict_changed"] is True
    assert traced_payloads[-1]["verifier_abstained"] is False


def test_compress_context_traces_route_decision_after_eval(monkeypatch) -> None:
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

    monkeypatch.setattr(cnode, "get_tracer", lambda: _Tracer())

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

    cnode.compress_context_node(state)  # type: ignore[arg-type]

    route_events = [item for item in traced if item[0] == "route_decision"]
    assert route_events
    _node, payload, logical_turn_idx = route_events[-1]
    assert payload["router"] == "route_after_eval"
    assert payload["decision"] == "refine"
    assert payload["recommended_next"] == "refine"
    assert payload["passed"] is False
    assert payload["dimension"] == "system_design"
    assert logical_turn_idx == 1
