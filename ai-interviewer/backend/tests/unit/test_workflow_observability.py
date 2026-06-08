from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from app.engine.context.history_context import build_history_context
from app.engine.workflow import routers
from app.engine.workflow.nodes import evaluator as enode
from app.engine.workflow.nodes import reward_update as rnode
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
    assert by_field["failure_categories"]["after"] == [
        "verifier_high_confidence_partial"
    ]
    assert by_field["passed"]["reason"] == "verifier_high_confidence_partial"
    assert (
        by_field["failure_categories"]["reason"]
        == "verifier_high_confidence_partial"
    )
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
    assert by_field["failure_categories"]["after"] == [
        "verifier_high_confidence_fail"
    ]
    assert by_field["failure_categories"]["reason"] == "verifier_high_confidence_fail"
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
        "pending_qa_turn": {
            "turn_idx": 0,
            "dimension": "technical_depth",
            "question": "How would you migrate this safely?",
            "answer": "I would use a canary rollout.",
            "evaluation": {
                "score": 8.0,
                "passed": True,
                "recommended_next": "next_question",
            },
        },
        "dimension_status": {"technical_depth": "passed"},
        "job_spec": {"level": "senior"},
        "quality_threshold": 7.5,
    }

    out = vnode.verification_node(state)  # type: ignore[arg-type]

    assert out["evaluation"]["passed"] is False
    assert out["pending_qa_turn"]["evaluation"]["passed"] is False
    assert out["pending_qa_turn"]["evaluation"]["recommended_next"] == "refine"
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


def test_verification_trace_ignores_gate_only_metadata_changes(monkeypatch) -> None:
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
            "verdict": "pass",
            "confidence": 0.95,
            "reasons_to_doubt": [],
        },
    )

    state: dict[str, Any] = {
        "current_question": {
            "dimension": "technical_depth",
            "question": "How would you migrate this safely?",
        },
        "current_contract": {
            "acceptance_checks": ["Mentions rollback."],
            "acceptance_check_items": [
                {
                    "check_id": "reviewed:rollback",
                    "text": "Mentions rollback.",
                    "source": "reviewed",
                    "severity": "core",
                }
            ],
        },
        "current_answer": "I would use a canary rollout with rollback.",
        "evaluation": {
            "score": 8.0,
            "passed": True,
            "recommended_next": "advance",
            "recommended_next_plan": None,
            "acceptance_check_results": {
                "Mentions rollback.": {"verdict": "yes", "evidence": ["rollback"]},
            },
        },
        "pending_qa_turn": {
            "turn_idx": 0,
            "dimension": "technical_depth",
            "question": "How would you migrate this safely?",
            "answer": "I would use a canary rollout with rollback.",
            "evaluation": {
                "score": 8.0,
                "passed": True,
                "recommended_next": "advance",
                "recommended_next_plan": None,
            },
        },
        "dimension_status": {"technical_depth": "passed"},
        "job_spec": {"level": "senior"},
        "quality_threshold": 7.5,
    }

    out = vnode.verification_node(state)  # type: ignore[arg-type]

    assert out["evaluation"]["passed"] is True
    assert out["evaluation"]["contract_gate_result"]["status"] == "passed"
    assert traced_payloads[-1]["contract_gate_result"]["status"] == "passed"
    assert traced_payloads[-1]["verdict_changed"] is False
    assert traced_payloads[-1]["verification_changes"] == []
    assert traced_payloads[-1]["verification_effect"] == "no_change"


def test_evaluator_contract_gate_enforce_updates_state_before_routing(
    monkeypatch,
) -> None:
    traced_states: list[dict[str, Any]] = []

    class _Tracer:
        def trace_evaluator(self, state, **_kwargs) -> None:
            traced_states.append(state)

    monkeypatch.setattr(enode, "get_tracer", lambda: _Tracer())
    monkeypatch.setattr(
        enode,
        "get_settings",
        lambda: SimpleNamespace(
            enable_evaluator_prompt_feedback=False,
            contract_gate_mode="shadow",
        ),
    )
    monkeypatch.setattr(enode, "get_raw_answer_for_state", lambda state: None)
    monkeypatch.setattr(enode, "_persist_interview_turn_fact", lambda **_kwargs: None)
    monkeypatch.setattr(enode, "immediate_reward", lambda **_kwargs: 0.23)
    captured: dict[str, Any] = {}

    def fake_evaluate_answer(**kwargs) -> dict[str, Any]:
        captured["scoring_contract"] = kwargs.get("contract")
        return {
            "score": 9.0,
            "passed": True,
            "recommended_next": "advance",
            "recommended_next_plan": None,
            "acceptance_check_results": {
                "Mentions rollback.": {
                    "verdict": "partial",
                    "evidence": ["rollback"],
                }
            },
        }

    monkeypatch.setattr(enode, "evaluate_answer", fake_evaluate_answer)

    state: dict[str, Any] = {
        "runtime_config": {"contract_gate_mode": "enforce"},
        "current_dimension": "technical_depth",
        "current_question": {
            "dimension": "technical_depth",
            "question": "How would you migrate this safely?",
            "rubric_points": [],
        },
        "current_contract": {
            "acceptance_checks": ["Mentions rollback."],
            "acceptance_check_items": [
                {
                    "check_id": "reviewed:rollback",
                    "text": "Mentions rollback.",
                    "source": "reviewed",
                    "severity": "core",
                }
            ],
        },
        "current_answer": "I would mention rollback later.",
        "quality_threshold": 7.5,
        "scores_per_dim": {},
        "score_breakdowns": {},
        "qa_history": [],
        "turn_idx": 0,
        "formal_turn_idx": 0,
        "turn_budget_remaining": 3,
        "max_turns": 5,
        "dimensions": ["technical_depth"],
        "dimension_status": {"technical_depth": "passed"},
        "selected_action": {"id": "ask_deeper"},
    }

    out = enode.evaluator_node(state)  # type: ignore[arg-type]

    evaluation = out["evaluation"]
    assert evaluation["score"] == 9.0
    assert evaluation["passed"] is False
    assert evaluation["recommended_next"] == "refine"
    assert evaluation["recommended_next_plan"] == "deep_probe"
    assert evaluation["contract_gate_result"]["mode"] == "enforce"
    assert evaluation["contract_gate_enforced"] is True
    assert evaluation["contract_gate_failed_check_ids"] == ["reviewed:rollback"]
    assert evaluation["gate_calibration_summary"]["signals"] == [
        "high_score_gate_failed",
        "partial_only_gate_failed",
    ]
    assert evaluation["gate_calibration_summary"]["score_band"] == "high"
    assert evaluation["gate_calibration_summary"]["partial_check_ids"] == [
        "reviewed:rollback"
    ]
    assert evaluation["contract_semantics_summary"]["reviewed_core"]["partial"] == 1
    assert evaluation["contract_semantics_summary"]["hard_gap_count"] == 1
    assert "acceptance_check_items" not in captured["scoring_contract"]
    assert captured["scoring_contract"]["acceptance_check_items_for_prompt"] == [
        {
            "check_id": "reviewed:rollback",
            "text": "Mentions rollback.",
            "source": "reviewed",
            "severity": "core",
        }
    ]
    assert out["dimension_status"]["technical_depth"] == "active"
    assert out["pending_qa_turn"]["evaluation"]["passed"] is False
    assert traced_states[-1]["evaluation"]["passed"] is False
    assert (
        traced_states[-1]["evaluation"]["gate_calibration_summary"][
            "partial_only_gate_failed"
        ]
        is True
    )

    route_state = {**state, **out}
    assert routers.route_after_eval(route_state) == "refine"  # type: ignore[arg-type]


def test_evaluator_builds_soft_gap_training_suggestions_without_route_change(
    monkeypatch,
) -> None:
    monkeypatch.setattr(enode, "get_tracer", lambda: SimpleNamespace(trace_evaluator=lambda *a, **k: None))
    monkeypatch.setattr(
        enode,
        "get_settings",
        lambda: SimpleNamespace(
            enable_evaluator_prompt_feedback=False,
            contract_gate_mode="shadow",
        ),
    )
    monkeypatch.setattr(enode, "get_raw_answer_for_state", lambda state: None)
    monkeypatch.setattr(enode, "_persist_interview_turn_fact", lambda **_kwargs: None)
    monkeypatch.setattr(enode, "immediate_reward", lambda **_kwargs: 0.42)

    def fake_evaluate_answer(**_kwargs) -> dict[str, Any]:
        return {
            "score": 8.2,
            "passed": True,
            "recommended_next": "advance",
            "recommended_next_plan": None,
            "acceptance_check_results": {
                "Mentions rollback.": {"verdict": "yes", "evidence": ["rollback"]},
                "Explains idempotent compensation.": {
                    "verdict": "partial",
                    "evidence": ["retry"],
                },
                "Connects to the payment migration project.": {
                    "verdict": "no",
                    "evidence": [],
                },
            },
        }

    monkeypatch.setattr(enode, "evaluate_answer", fake_evaluate_answer)

    state: dict[str, Any] = {
        "current_dimension": "technical_depth",
        "current_question": {
            "dimension": "technical_depth",
            "question": "How would you migrate this safely?",
            "rubric_points": [],
        },
        "current_contract": {
            "acceptance_checks": [
                "Mentions rollback.",
                "Explains idempotent compensation.",
                "Connects to the payment migration project.",
            ],
            "acceptance_check_items": [
                {
                    "check_id": "reviewed:rollback",
                    "text": "Mentions rollback.",
                    "source": "reviewed",
                    "severity": "core",
                },
                {
                    "check_id": "reviewed:support:idempotency",
                    "text": "Explains idempotent compensation.",
                    "source": "reviewed",
                    "severity": "supporting",
                },
                {
                    "check_id": "adaptive:payment-migration",
                    "text": "Connects to the payment migration project.",
                    "source": "adaptive_context",
                    "severity": "supporting",
                },
            ],
        },
        "current_answer": "I would use rollback and retries.",
        "quality_threshold": 7.5,
        "scores_per_dim": {},
        "score_breakdowns": {},
        "qa_history": [],
        "turn_idx": 0,
        "formal_turn_idx": 0,
        "turn_budget_remaining": 3,
        "max_turns": 5,
        "dimensions": ["technical_depth"],
        "dimension_status": {"technical_depth": "active"},
        "selected_action": {"id": "ask_deeper"},
    }

    out = enode.evaluator_node(state)  # type: ignore[arg-type]

    evaluation = out["evaluation"]
    assert evaluation["passed"] is False
    assert evaluation["recommended_next"] == "refine"
    suggestions = evaluation["soft_gap_training_suggestions"]
    assert suggestions["counts"] == {"quality": 1, "context": 1, "total": 2}
    assert suggestions["quality_suggestions"][0]["check_id"] == (
        "reviewed:support:idempotency"
    )
    assert suggestions["context_suggestions"][0]["check_id"] == (
        "adaptive:payment-migration"
    )
    hints = evaluation["soft_followup_hints"]
    assert hints["mode"] == "shadow"
    assert hints["applied"] is False
    assert hints["counts"] == {"quality": 1, "context": 1, "total": 2}
    assert hints["quality_hints"][0]["intent"] == "probe_quality_gap"
    assert hints["context_hints"][0]["intent"] == "probe_context_gap"
    assert out["dimension_status"]["technical_depth"] == "active"


def test_verification_contract_gate_enforce_overrides_verifier_pass(
    monkeypatch,
) -> None:
    traced_payloads: list[dict[str, Any]] = []

    class _Tracer:
        def trace_node_event(self, _state, *, node, payload, **_kwargs) -> None:
            if node == "verification":
                traced_payloads.append(payload)

    monkeypatch.setattr(vnode, "get_tracer", lambda: _Tracer())
    monkeypatch.setattr(
        vnode,
        "get_settings",
        lambda: SimpleNamespace(
            enable_verifier_drift_monitor=False,
            enable_verifier_drift_persistence=False,
            verifier_min_override_confidence=0.6,
            contract_gate_mode="shadow",
        ),
    )
    monkeypatch.setattr(vnode, "should_trigger", lambda **_kwargs: True)
    monkeypatch.setattr(
        vnode,
        "verify_answer",
        lambda **_kwargs: {
            "verifier_available": True,
            "verdict": "pass",
            "confidence": 0.95,
            "reasons_to_doubt": [],
        },
    )

    state: dict[str, Any] = {
        "runtime_config": {"contract_gate_mode": "enforce"},
        "current_question": {
            "dimension": "technical_depth",
            "question": "How would you migrate this safely?",
        },
        "current_contract": {
            "acceptance_checks": ["Mentions rollback."],
            "acceptance_check_items": [
                {
                    "check_id": "reviewed:rollback",
                    "text": "Mentions rollback.",
                    "source": "reviewed",
                    "severity": "core",
                }
            ],
        },
        "current_answer": "I would use a canary rollout.",
        "evaluation": {
            "score": 8.0,
            "passed": True,
            "recommended_next": "advance",
            "recommended_next_plan": None,
            "acceptance_check_results": {
                "Mentions rollback.": {"verdict": "no", "evidence": []},
            },
        },
        "pending_qa_turn": {
            "turn_idx": 0,
            "dimension": "technical_depth",
            "question": "How would you migrate this safely?",
            "answer": "I would use a canary rollout.",
            "evaluation": {
                "score": 8.0,
                "passed": True,
                "recommended_next": "advance",
                "recommended_next_plan": None,
            },
        },
        "dimension_status": {"technical_depth": "passed"},
        "job_spec": {"level": "senior"},
        "quality_threshold": 7.5,
    }

    out = vnode.verification_node(state)  # type: ignore[arg-type]

    evaluation = out["evaluation"]
    assert evaluation["passed"] is False
    assert evaluation["recommended_next"] == "refine"
    assert evaluation["recommended_next_plan"] == "deep_probe"
    assert evaluation["contract_gate_result"]["mode"] == "enforce"
    assert evaluation["contract_gate_enforced"] is True
    assert evaluation["gate_calibration_summary"]["signals"] == [
        "high_score_gate_failed",
        "hard_failure_gate_failed",
    ]
    assert evaluation["gate_calibration_summary"]["no_check_ids"] == [
        "reviewed:rollback"
    ]
    assert evaluation["contract_semantics_summary"]["reviewed_core"]["no"] == 1
    assert evaluation["contract_semantics_summary"]["hard_gap_count"] == 1
    assert out["dimension_status"]["technical_depth"] == "active"
    assert out["pending_qa_turn"]["evaluation"]["passed"] is False
    assert traced_payloads[-1]["updated_passed"] is False
    assert traced_payloads[-1]["verdict_changed"] is True
    by_field = {
        change["field"]: change
        for change in traced_payloads[-1]["verification_changes"]
    }
    assert by_field["passed"]["reason"] == "contract_gate_reviewed_core_failed"
    assert traced_payloads[-1]["verification_effect"] == "overruled_to_refine"
    assert traced_payloads[-1]["gate_calibration_summary"]["hard_failure_gate_failed"] is True


def test_verification_contract_gate_enforce_keeps_existing_forced_refine(
    monkeypatch,
) -> None:
    monkeypatch.setattr(vnode, "get_tracer", lambda: SimpleNamespace(trace_node_event=lambda *a, **k: None))
    monkeypatch.setattr(
        vnode,
        "get_settings",
        lambda: SimpleNamespace(
            enable_verifier_drift_monitor=False,
            enable_verifier_drift_persistence=False,
            verifier_min_override_confidence=0.6,
            contract_gate_mode="shadow",
        ),
    )
    monkeypatch.setattr(vnode, "should_trigger", lambda **_kwargs: True)
    monkeypatch.setattr(
        vnode,
        "verify_answer",
        lambda **_kwargs: {
            "verifier_available": True,
            "verdict": "fail",
            "confidence": 0.95,
            "reasons_to_doubt": ["missing metrics"],
        },
    )

    state: dict[str, Any] = {
        "runtime_config": {"contract_gate_mode": "enforce"},
        "current_question": {
            "dimension": "technical_depth",
            "question": "How would you migrate this safely?",
        },
        "current_contract": {
            "acceptance_checks": ["Mentions rollback."],
            "acceptance_check_items": [
                {
                    "check_id": "reviewed:rollback",
                    "text": "Mentions rollback.",
                    "source": "reviewed",
                    "severity": "core",
                }
            ],
        },
        "current_answer": "I would use a canary rollout.",
        "evaluation": {
            "score": 8.0,
            "passed": True,
            "recommended_next": "advance",
            "recommended_next_plan": None,
            "acceptance_check_results": {
                "Mentions rollback.": {"verdict": "no", "evidence": []},
            },
        },
        "dimension_status": {"technical_depth": "passed"},
        "job_spec": {"level": "senior"},
        "quality_threshold": 7.5,
    }

    out = vnode.verification_node(state)  # type: ignore[arg-type]

    evaluation = out["evaluation"]
    assert evaluation["passed"] is False
    assert evaluation["verifier_forced_refine"] is True
    assert evaluation["contract_gate_enforced"] is True
    assert "missing metrics" in evaluation["weaknesses"]
    assert "contract_gate_reviewed_core_failed" in evaluation["failure_categories"]


def test_reward_update_uses_gate_enforced_evaluation(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    class _Bandit:
        def update(self, context_key, action_id, reward) -> None:
            captured.setdefault("bandit_updates", []).append(
                (context_key, action_id, reward)
            )

    class _Tracer:
        def trace_node_event(self, _state, *, node, payload, **_kwargs) -> None:
            if node == "reward_update":
                captured["payload"] = payload

    monkeypatch.setattr(rnode, "get_bandit", lambda: _Bandit())
    monkeypatch.setattr(rnode, "get_tracer", lambda: _Tracer())
    monkeypatch.setattr(rnode, "_record_strategy_learning_reward", lambda **_kwargs: None)
    monkeypatch.setattr(rnode, "_record_strategy_memory_usage", lambda **_kwargs: {})
    monkeypatch.setattr(rnode, "_record_skill_usage", lambda **_kwargs: {})
    monkeypatch.setattr(rnode, "_backfill_question_usage_result", lambda **_kwargs: {})

    def fake_reward(*, evaluation, contract):
        captured["reward_passed"] = evaluation.get("passed")
        return 0.12 if not evaluation.get("passed") else 0.99

    monkeypatch.setattr(rnode, "immediate_reward", fake_reward)

    out = rnode.reward_update_node(
        {
            "turn_idx": 1,
            "formal_turn_idx": 1,
            "selected_action": {"id": "ask_deeper"},
            "policy_context_keys": ["ctx"],
            "current_question": {"dimension": "technical_depth"},
            "current_contract": {"acceptance_checks": ["Mentions rollback."]},
            "evaluation": {
                "score": 9.0,
                "passed": False,
                "recommended_next": "refine",
                "contract_gate_enforced": True,
            },
        }  # type: ignore[arg-type]
    )

    assert captured["reward_passed"] is False
    assert out["messages"][0]["immediate_reward"] == 0.12
    assert captured["payload"]["reward_summary"]["passed"] is False


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


def test_turn_finalize_appends_pending_qa_turn_before_route_decision(
    monkeypatch,
) -> None:
    traced: list[tuple[str, dict[str, Any], dict[str, Any], int | None]] = []

    class _Tracer:
        def trace_node_event(
            self,
            state,
            *,
            node,
            payload,
            logical_turn_idx=None,
            **_kwargs,
        ) -> None:
            traced.append((node, state, payload, logical_turn_idx))

    monkeypatch.setattr(tnode, "get_tracer", lambda: _Tracer())

    pending_turn = {
        "turn_idx": 1,
        "dimension": "system_design",
        "question": "Q1",
        "answer": "A1",
        "evaluation": {"passed": False, "recommended_next": "refine"},
    }
    state: dict[str, Any] = {
        "turn_idx": 2,
        "formal_turn_idx": 2,
        "max_turns": 6,
        "turn_budget_remaining": 4,
        "current_dimension": "system_design",
        "dimensions": ["system_design", "communication"],
        "dimension_status": {"system_design": "active", "communication": "pending"},
        "evaluation": {"passed": False, "recommended_next": "refine"},
        "qa_history": [
            {
                "turn_idx": 0,
                "dimension": "system_design",
                "question": "Q0",
                "evaluation": {"passed": False},
            }
        ],
        "pending_qa_turn": pending_turn,
    }

    out = tnode.turn_finalize_node(state)  # type: ignore[arg-type]

    assert out["qa_history"] == [pending_turn]
    assert out["pending_qa_turn"] is None

    finalize_events = [item for item in traced if item[0] == "turn_finalize"]
    assert finalize_events[-1][2]["qa_history_count"] == 2
    assert len(finalize_events[-1][1]["qa_history"]) == 2

    route_events = [item for item in traced if item[0] == "route_decision"]
    assert route_events[-1][2]["decision"] == "next_question"
    assert route_events[-1][2]["decision_reason"] == "coverage_advance"
    assert route_events[-1][2]["decision_inputs"]["current_dimension_attempts"] == 2


def test_finalized_pending_turn_feeds_next_history_context_current_gaps(
    monkeypatch,
) -> None:
    traced: list[tuple[str, dict[str, Any], dict[str, Any]]] = []

    class _Tracer:
        def trace_node_event(
            self,
            state,
            *,
            node,
            payload,
            **_kwargs,
        ) -> None:
            traced.append((node, state, payload))

    monkeypatch.setattr(tnode, "get_tracer", lambda: _Tracer())

    final_gap = "未说明如何回滚到旧方案或快速止损。"
    pending_turn = {
        "turn_idx": 0,
        "dimension": "coding_quality",
        "question": "Q0",
        "answer": "A0",
        "evaluation": {
            "score": 9.0,
            "passed": False,
            "weaknesses": [final_gap, "回滚措施描述不够具体"],
            "recommended_next": "refine",
        },
    }
    state: dict[str, Any] = {
        "turn_idx": 1,
        "formal_turn_idx": 1,
        "max_turns": 6,
        "turn_budget_remaining": 5,
        "current_dimension": "coding_quality",
        "dimensions": ["coding_quality", "system_design"],
        "dimension_status": {"coding_quality": "active", "system_design": "pending"},
        "evaluation": pending_turn["evaluation"],
        "qa_history": [],
        "pending_qa_turn": pending_turn,
    }

    out = tnode.turn_finalize_node(state)  # type: ignore[arg-type]

    finalized_history = list(state["qa_history"]) + list(out.get("qa_history") or [])
    history_context = build_history_context(
        qa_history=finalized_history,
        current_dimension="coding_quality",
    )

    assert out["pending_qa_turn"] is None
    assert history_context["prompt_slots"][2]["prompt_label"] == "CURRENT_GAPS"
    assert history_context["prompt_slots"][2]["value"] == [final_gap]
    assert history_context["stats"]["current_gaps_dedupe_merge_count"] == 1

    finalize_events = [item for item in traced if item[0] == "turn_finalize"]
    assert finalize_events[-1][2]["qa_history_count"] == 1
    assert finalize_events[-1][1]["pending_qa_turn"] is None

    route_events = [item for item in traced if item[0] == "route_decision"]
    assert route_events[-1][2]["decision_inputs"]["current_dimension_attempts"] == 1
    assert route_events[-1][2]["decision_inputs"]["passed"] is False
    assert route_events[-1][2]["decision_inputs"]["recommended_next"] == "refine"


def test_turn_finalize_does_not_duplicate_existing_pending_qa_turn(
    monkeypatch,
) -> None:
    traced: list[tuple[str, dict[str, Any], dict[str, Any]]] = []

    class _Tracer:
        def trace_node_event(
            self,
            state,
            *,
            node,
            payload,
            **_kwargs,
        ) -> None:
            traced.append((node, state, payload))

    monkeypatch.setattr(tnode, "get_tracer", lambda: _Tracer())

    pending_turn = {
        "turn_idx": 1,
        "dimension": "system_design",
        "question": "Q1",
        "answer": "A1",
        "evaluation": {"passed": False, "recommended_next": "refine"},
    }
    state: dict[str, Any] = {
        "turn_idx": 2,
        "formal_turn_idx": 2,
        "max_turns": 6,
        "turn_budget_remaining": 4,
        "current_dimension": "system_design",
        "dimensions": ["system_design"],
        "dimension_status": {"system_design": "active"},
        "evaluation": {"passed": False, "recommended_next": "refine"},
        "qa_history": [pending_turn],
        "pending_qa_turn": dict(pending_turn),
    }

    out = tnode.turn_finalize_node(state)  # type: ignore[arg-type]

    assert "qa_history" not in out
    assert out["pending_qa_turn"] is None
    finalize_events = [item for item in traced if item[0] == "turn_finalize"]
    assert finalize_events[-1][2]["qa_history_count"] == 1
    assert len(finalize_events[-1][1]["qa_history"]) == 1


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
