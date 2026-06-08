from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from app.engine.contracts.evaluation_quality import (
    build_evaluation_quality_warning,
)
from app.engine.workflow.nodes import evaluator as enode


def _reviewed_core_contract() -> dict[str, Any]:
    return {
        "acceptance_checks": ["Explains rollback."],
        "acceptance_check_items": [
            {
                "check_id": "reviewed:rollback",
                "text": "Explains rollback.",
                "source": "reviewed",
                "severity": "core",
            }
        ],
    }


def _state(*, contract: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "runtime_config": {"contract_gate_mode": "enforce"},
        "current_dimension": "technical_depth",
        "current_question": {
            "dimension": "technical_depth",
            "question": "How would you migrate safely?",
            "rubric_points": [],
        },
        "current_contract": contract if contract is not None else _reviewed_core_contract(),
        "current_answer": "I would use an idempotent retry and rollback plan.",
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


def _patch_evaluator_node(monkeypatch, answers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

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

    def fake_evaluate_answer(**kwargs) -> dict[str, Any]:
        calls.append(kwargs)
        idx = min(len(calls) - 1, len(answers) - 1)
        return dict(answers[idx])

    monkeypatch.setattr(enode, "evaluate_answer", fake_evaluate_answer)
    return calls


def _low_quality_partial(*, score: float = 9.0) -> dict[str, Any]:
    return {
        "score": score,
        "passed": True,
        "recommended_next": "advance",
        "recommended_next_plan": None,
        "acceptance_check_results": {
            "Explains rollback.": {"verdict": "partial", "evidence": []},
        },
        "rationale": "",
    }


def _good_yes() -> dict[str, Any]:
    return {
        "score": 8.8,
        "passed": True,
        "recommended_next": "advance",
        "recommended_next_plan": None,
        "acceptance_check_results": {
            "Explains rollback.": {
                "verdict": "yes",
                "evidence": ["rollback plan"],
            },
        },
        "rationale": "The answer gives concrete rollback evidence.",
    }


def test_quality_guard_detects_empty_evidence_all_reviewed_core_partial() -> None:
    evaluation = {
        "acceptance_check_result_items": [
            {
                "check_id": "reviewed:rollback",
                "text": "Explains rollback.",
                "source": "reviewed",
                "severity": "core",
                "verdict": "partial",
                "evidence": [],
                "result_present": True,
            }
        ],
        "rationale": "",
    }

    warning = build_evaluation_quality_warning(
        evaluation,
        contract=_reviewed_core_contract(),
        answer="non-empty answer",
    )

    assert warning == {
        "evaluation_quality_warning": True,
        "evaluation_quality_warning_reason": (
            "empty_evidence_all_reviewed_core_partial"
        ),
        "evaluation_quality_warning_check_ids": ["reviewed:rollback"],
    }


def test_quality_guard_treats_evidence_spans_as_evidence() -> None:
    evaluation = {
        "acceptance_check_result_items": [
            {
                "check_id": "reviewed:rollback",
                "text": "Explains rollback.",
                "source": "reviewed",
                "severity": "core",
                "verdict": "partial",
                "evidence": [],
                "evidence_spans": [{"quote": "rollback"}],
                "result_present": True,
            }
        ],
        "rationale": "",
    }

    assert (
        build_evaluation_quality_warning(
            evaluation,
            contract=_reviewed_core_contract(),
            answer="non-empty answer",
        )
        is None
    )


def test_evaluator_quality_guard_retries_once_and_uses_second_result(
    monkeypatch,
) -> None:
    calls = _patch_evaluator_node(
        monkeypatch,
        [_low_quality_partial(), _good_yes()],
    )

    out = enode.evaluator_node(_state())  # type: ignore[arg-type]

    evaluation = out["evaluation"]
    assert len(calls) == 2
    assert evaluation["score"] == 8.8
    assert evaluation["passed"] is True
    assert evaluation["evaluation_retry_applied"] is True
    assert evaluation["evaluation_retry_reason"] == "quality_guard"
    assert evaluation.get("evaluation_quality_warning") is not True
    assert evaluation["acceptance_check_result_items"][0]["verdict"] == "yes"
    assert evaluation["contract_gate_result"]["status"] == "passed"
    assert "contract_gate_enforced" not in evaluation
    assert out["dimension_status"]["technical_depth"] == "passed"
    assert out["pending_qa_turn"]["evaluation"]["score"] == 8.8


def test_evaluator_quality_guard_marks_second_bad_result_unscorable(
    monkeypatch,
) -> None:
    calls = _patch_evaluator_node(
        monkeypatch,
        [_low_quality_partial(score=9.0), _low_quality_partial(score=8.2)],
    )

    out = enode.evaluator_node(_state())  # type: ignore[arg-type]

    evaluation = out["evaluation"]
    assert len(calls) == 2
    assert evaluation["score"] == 8.2
    assert evaluation["evaluation_retry_applied"] is True
    assert evaluation["evaluation_retry_reason"] == "quality_guard"
    assert evaluation["evaluation_quality_warning"] is True
    assert evaluation["evaluation_quality_warning_reason"] == (
        "empty_evidence_all_reviewed_core_partial"
    )
    assert evaluation["evaluation_quality_warning_check_ids"] == [
        "reviewed:rollback"
    ]
    assert evaluation["evaluation_quality_invalid"] is True
    assert evaluation["evaluation_quality_invalid_reason"] == (
        "quality_guard_retry_exhausted"
    )
    assert evaluation["source"] == "fallback"
    assert evaluation["fallback_reason"] == "evaluator_quality_guard_failed"
    assert evaluation["passed"] is False
    assert evaluation["recommended_next"] == "next_question"
    assert evaluation["contract_gate_result"]["status"] == "not_applicable"
    assert evaluation["contract_gate_result"]["warnings"] == [
        "evaluation_quality_invalid"
    ]
    assert "contract_gate_enforced" not in evaluation
    assert out["dimension_status"]["technical_depth"] == "active"


def test_evaluator_quality_guard_does_not_retry_normal_partial_with_evidence(
    monkeypatch,
) -> None:
    calls = _patch_evaluator_node(
        monkeypatch,
        [
            {
                **_low_quality_partial(),
                "acceptance_check_results": {
                    "Explains rollback.": {
                        "verdict": "partial",
                        "evidence": ["rollback later"],
                    },
                },
            }
        ],
    )

    out = enode.evaluator_node(_state())  # type: ignore[arg-type]

    evaluation = out["evaluation"]
    assert len(calls) == 1
    assert evaluation.get("evaluation_retry_applied") is not True
    assert evaluation.get("evaluation_quality_warning") is not True
    assert evaluation["contract_gate_result"]["status"] == "failed"


def test_evaluator_quality_guard_does_not_retry_without_reviewed_core(
    monkeypatch,
) -> None:
    calls = _patch_evaluator_node(
        monkeypatch,
        [_low_quality_partial()],
    )
    contract = {
        "acceptance_checks": ["Explains rollback."],
        "acceptance_check_items": [
            {
                "check_id": "adaptive:rollback",
                "text": "Explains rollback.",
                "source": "adaptive_context",
                "severity": "supporting",
            }
        ],
    }

    out = enode.evaluator_node(_state(contract=contract))  # type: ignore[arg-type]

    evaluation = out["evaluation"]
    assert len(calls) == 1
    assert evaluation.get("evaluation_retry_applied") is not True
    assert evaluation.get("evaluation_quality_warning") is not True
    assert evaluation["contract_gate_result"]["status"] == "not_applicable"
