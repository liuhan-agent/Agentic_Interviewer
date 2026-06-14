"""Verify that ``final_report_node`` mirrors itself into ``generation_traces``.

Before this change the ``final_report`` step only updated the
``interview_sessions`` row (via :meth:`Tracer.trace_final_report`) and
did *not* write a ``generation_traces`` row, so the
``final_report_trace_count`` metric exposed by
``/admin/interview-sessions/{id}/traces`` was structurally always 0.

The fix adds an extra ``Tracer.trace_node_event(node="final_report")``
call right after the legacy ``trace_final_report`` so the panel can
finally surface a real "final_report" entry alongside the per-turn
nodes — useful for both debugging (did this session actually reach
the final node?) and for the trace-health classifier.

We capture the calls via a fake tracer rather than touching the real
SQL layer; that mirrors the pattern used by existing
``test_final_report_evidence`` / ``test_closed_loop_report`` cases.
"""
from __future__ import annotations

from typing import Any

import pytest

from app.engine.workflow.nodes import final_report as fr


class _RecordingTracer:
    """Captures every tracer call so a test can assert what fired.

    Both legacy ``trace_final_report`` and the new ``trace_node_event``
    must be called for a regular completion. Failures (returning
    nothing or raising) propagate to the caller — the production code
    wraps each call in a try/except, so a test that wants to observe
    the calls needs the fake to actually behave.
    """

    def __init__(self) -> None:
        self.final_report_calls: list[dict[str, Any]] = []
        self.node_events: list[dict[str, Any]] = []

    def trace_final_report(self, state: dict[str, Any]) -> None:
        self.final_report_calls.append({"status": state.get("status")})

    def trace_node_event(
        self,
        state: dict[str, Any],
        *,
        node: str,
        payload: dict[str, Any] | None = None,
        **_kwargs: Any,
    ) -> None:
        self.node_events.append(
            {
                "node": node,
                "payload": dict(payload or {}),
                "session_id": state.get("session_id"),
                "status": state.get("status"),
            }
        )


def _state_for_completed_session() -> dict[str, Any]:
    """Smallest state dict that produces a successful report payload.

    Mirrors what ``test_closed_loop_report`` already does, trimmed to
    only the fields ``final_report_node`` actually reads.
    """
    return {
        "session_id": "sess-final-report-1",
        "trace_id": "trace-final-report-1",
        "candidate": {"name": "Alex"},
        "job_spec": {"title": "Senior Backend Engineer"},
        "quality_threshold": 7.0,
        "scores_per_dim": {"system_design": 7.4},
        "dimension_status": {"system_design": "passed"},
        "qa_history": [
            {
                "turn_idx": 0,
                "dimension": "system_design",
                "question": "Design a rate limiter.",
                "answer": "I would use a token bucket with Redis.",
                "selected_action": "plan_adaptive",
                "evaluation": {
                    "score": 7.4,
                    "passed": True,
                    "strengths": ["clear trade-off"],
                    "weaknesses": [],
                    "rubric_coverage": {},
                    "acceptance_check_results": {},
                    "rationale": "Solid answer.",
                },
            }
        ],
    }


@pytest.fixture
def fake_tracer(monkeypatch: pytest.MonkeyPatch) -> _RecordingTracer:
    tracer = _RecordingTracer()
    monkeypatch.setattr(fr, "get_tracer", lambda: tracer)
    return tracer


def test_completed_session_emits_final_report_node_event(
    fake_tracer: _RecordingTracer,
) -> None:
    state = _state_for_completed_session()

    fr.final_report_node(state)  # type: ignore[arg-type]

    assert len(fake_tracer.final_report_calls) == 1, (
        "legacy session-level trace must still fire so the "
        "interview_sessions row keeps its status update."
    )
    assert len(fake_tracer.node_events) == 1, (
        "final_report_node must emit exactly one trace_node_event so "
        "generation_traces gets a 'final_report' row per session."
    )
    event = fake_tracer.node_events[0]
    assert event["node"] == "final_report"
    assert event["session_id"] == "sess-final-report-1"
    assert event["status"] == "completed"
    payload = event["payload"]
    assert "verdict" in payload
    assert "overall_score" in payload
    assert payload["final_status"] == "completed"
    assert payload["report_status"] == "completed"
    assert payload["dimension_count"] == 1
    assert payload["training_plan_queued"] is True
    assert payload["experience_extractor_queued"] is True
    assert payload["fallback_count"] == 0
    assert payload["evaluator_turn_count"] == 1
    assert payload["missing_sections"] == []
    assert payload["report_summary"]["overall_score"] == payload["overall_score"]
    assert payload["report_summary"]["growth_signal"] == payload["conclusion"]
    assert payload["scoring_credibility"]["credibility_summary"]
    assert payload["scoring_credibility"]["contract_summary"]
    assert payload["scoring_credibility"]["evidence_summary"]
    assert payload["dimension_results"] == [
        {
            "dimension": "system_design",
            "score": 7.4,
            "score_status": "scored",
            "passed": True,
            "coverage_status": "passed",
            "turn_count": 1,
        }
    ]
    assert payload["dimension_evidence"][0]["dimension"] == "system_design"
    assert payload["dimension_evidence"][0]["strength_count"] == 1
    assert payload["dimension_evidence"][0]["weakness_count"] == 0
    assert payload["closing_chain"] == {
        "training_plan_queued": True,
        "experience_extractor_queued": True,
    }
    assert payload["workflow_artifacts"]["latest_ask_plan"] is None
    assert payload["workflow_artifacts"]["target_skill_coverage"] == {}


def test_final_report_trace_dimension_evidence_carries_contract_gate_items(
    fake_tracer: _RecordingTracer,
) -> None:
    state = _state_for_completed_session()
    state["qa_history"][0]["evaluation"].update(
        {
            "passed": False,
            "acceptance_check_result_items": [
                {
                    "check_id": "reviewed:rate_limit:core_algorithm:v1",
                    "text": "Explains the rate-limit algorithm.",
                    "source": "reviewed",
                    "severity": "core",
                    "verdict": "partial",
                    "evidence": ["token bucket"],
                    "result_present": True,
                }
            ],
            "contract_gate_result": {
                "gate_id": "reviewed_core_acceptance",
                "mode": "enforce",
                "status": "failed",
                "failed_count": 1,
                "failed_items": [
                    {
                        "check_id": "reviewed:rate_limit:core_algorithm:v1",
                        "text": "Explains the rate-limit algorithm.",
                        "source": "reviewed",
                        "severity": "core",
                        "verdict": "partial",
                        "result_present": True,
                        "reason": "partial",
                    }
                ],
            },
            "contract_gate_enforced": True,
            "contract_gate_enforcement_reason": "reviewed_core_failed",
            "gate_calibration_summary": {
                "present": True,
                "mode": "audit",
                "source": "contract_gate_result",
                "score": 7.4,
                "score_band": "standard",
                "passed": False,
                "gate_mode": "enforce",
                "gate_status": "failed",
                "gate_enforced": True,
                "high_score_gate_failed": False,
                "standard_score_gate_failed": True,
                "partial_only_gate_failed": True,
                "hard_failure_gate_failed": False,
                "signals": ["partial_only_gate_failed"],
                "reviewed_core": {
                    "eligible": 1,
                    "yes": 0,
                    "partial": 1,
                    "no": 0,
                    "missing": 0,
                    "failed": 1,
                },
                "failed_check_ids": ["reviewed:rate_limit:core_algorithm:v1"],
                "partial_check_ids": ["reviewed:rate_limit:core_algorithm:v1"],
                "no_check_ids": [],
                "missing_check_ids": [],
                "failed_items": [
                    {
                        "check_id": "reviewed:rate_limit:core_algorithm:v1",
                        "text": "Explains the rate-limit algorithm.",
                        "verdict": "partial",
                        "reason": "partial",
                    }
                ],
            },
            "contract_semantics_summary": {
                "reviewed_core": {
                    "total": 1,
                    "yes": 0,
                    "partial": 1,
                    "no": 0,
                    "missing": 0,
                    "failed_items": [
                        {
                            "check_id": "reviewed:rate_limit:core_algorithm:v1",
                            "text": "Explains the rate-limit algorithm.",
                            "source": "reviewed",
                            "severity": "core",
                            "verdict": "partial",
                            "reason": "partial",
                        }
                    ],
                },
                "reviewed_supporting": {
                    "total": 0,
                    "yes": 0,
                    "partial": 0,
                    "no": 0,
                    "missing": 0,
                    "gap_items": [],
                },
                "adaptive_context": {
                    "total": 0,
                    "yes": 0,
                    "partial": 0,
                    "no": 0,
                    "missing": 0,
                    "gap_items": [],
                },
                "evaluator_extra": {"total": 0, "items": []},
                "hard_gap_count": 1,
                "soft_quality_gap_count": 0,
                "context_gap_count": 0,
            },
            "soft_gap_training_suggestions": {
                "present": True,
                "source": "contract_semantics_summary",
                "quality_suggestions": [
                    {
                        "suggestion_id": "soft_gap:quality",
                        "source": "reviewed_supporting",
                        "check_id": "reviewed:support:observability",
                        "title": "Quality gap: adds observability detail",
                        "description": "Improve observability detail.",
                    }
                ],
                "context_suggestions": [
                    {
                        "suggestion_id": "soft_gap:context",
                        "source": "adaptive_context",
                        "check_id": "adaptive:project-scale",
                        "title": "Context gap: connects project scale",
                        "description": "Connect the answer to project scale.",
                    }
                ],
                "counts": {"quality": 1, "context": 1, "total": 2},
            },
            "soft_followup_hints": {
                "present": True,
                "mode": "shadow",
                "applied": False,
                "source": "soft_gap_training_suggestions",
                "quality_hints": [
                    {
                        "hint_id": "soft_followup:quality",
                        "source": "reviewed_supporting",
                        "intent": "probe_quality_gap",
                        "check_id": "reviewed:support:observability",
                        "focus": "Probe quality gap.",
                    }
                ],
                "context_hints": [
                    {
                        "hint_id": "soft_followup:context",
                        "source": "adaptive_context",
                        "intent": "probe_context_gap",
                        "check_id": "adaptive:project-scale",
                        "focus": "Probe context gap.",
                    }
                ],
                "priority_order": [
                    "soft_followup:quality",
                    "soft_followup:context",
                ],
                "counts": {"quality": 1, "context": 1, "total": 2},
            },
        }
    )

    fr.final_report_node(state)  # type: ignore[arg-type]

    evidence = fake_tracer.node_events[0]["payload"]["dimension_evidence"][0]
    assert evidence["contract_gate_results"][0]["status"] == "failed"
    assert evidence["contract_gate_results"][0]["mode"] == "enforce"
    assert evidence["contract_gate_results"][0]["enforced"] is True
    assert evidence["contract_gate_results"][0]["failed_check_ids"] == [
        "reviewed:rate_limit:core_algorithm:v1"
    ]
    assert evidence["gate_calibration_summaries"][0]["turn_idx"] == 0
    assert evidence["gate_calibration_summaries"][0]["mode"] == "audit"
    assert evidence["gate_calibration_summaries"][0]["partial_only_gate_failed"] is True
    assert evidence["gate_calibration_summaries"][0]["failed_check_ids"] == [
        "reviewed:rate_limit:core_algorithm:v1"
    ]
    assert evidence["acceptance_check_result_items"][0] == {
        "turn_idx": 0,
        "check_id": "reviewed:rate_limit:core_algorithm:v1",
        "text": "Explains the rate-limit algorithm.",
        "source": "reviewed",
        "severity": "core",
        "verdict": "partial",
        "evidence": ["token bucket"],
        "result_present": True,
    }
    assert evidence["contract_semantics_summaries"][0]["turn_idx"] == 0
    assert evidence["contract_semantics_summaries"][0]["hard_gap_count"] == 1
    assert evidence["soft_gap_training_suggestions"][0]["turn_idx"] == 0
    assert evidence["soft_gap_training_suggestions"][0]["counts"]["total"] == 2
    assert evidence["soft_followup_hints"][0]["turn_idx"] == 0
    assert evidence["soft_followup_hints"][0]["mode"] == "shadow"
    assert evidence["soft_followup_hints"][0]["applied"] is False
    assert evidence["soft_followup_hints"][0]["counts"]["total"] == 2


def test_final_report_trace_dimension_evidence_carries_score_audit(
    fake_tracer: _RecordingTracer,
) -> None:
    state = _state_for_completed_session()
    state["qa_history"][0]["evaluation"].update(
        {
            "score": 8.05,
            "llm_score": 8.5,
            "contract_score": 7.86,
            "final_score": 8.05,
            "score_source": "hybrid",
            "evaluator_score_mode": "hybrid",
            "requested_evaluator_score_mode": "hybrid",
            "score_formula": "0.7*contract_score+0.3*llm_score",
            "score_mode_warnings": [],
            "contract_score_mode": "shadow",
            "contract_score_breakdown": {
                "available": True,
                "structured_source": "reviewed",
            },
        }
    )

    fr.final_report_node(state)  # type: ignore[arg-type]

    evidence = fake_tracer.node_events[0]["payload"]["dimension_evidence"][0]
    assert evidence["score_audits"] == [
        {
            "turn_idx": 0,
            "llm_score": 8.5,
            "contract_score": 7.86,
            "final_score": 8.05,
            "score_source": "hybrid",
            "evaluator_score_mode": "hybrid",
            "requested_evaluator_score_mode": "hybrid",
            "score_formula": "0.7*contract_score+0.3*llm_score",
            "score_mode_warnings": [],
            "contract_score_mode": "shadow",
            "contract_score_breakdown": {
                "available": True,
                "structured_source": "reviewed",
            },
        }
    ]


def test_final_report_trace_dimension_evidence_carries_pass_shadow(
    fake_tracer: _RecordingTracer,
) -> None:
    state = _state_for_completed_session()
    state["qa_history"][0]["evaluation"].update(
        {
            "contract_pass_shadow": {
                "available": True,
                "score": 5.71,
                "quality_threshold": 7.5,
                "passed": False,
                "recommended_next": "refine",
                "recommended_next_plan": "deep_probe",
                "reason": "contract_score_below_threshold",
                "legacy_passed": True,
                "legacy_recommended_next": "advance",
                "legacy_recommended_next_plan": None,
                "pass_diff": True,
                "routing_signal_diff": True,
            },
            "contract_passed_shadow": False,
            "contract_recommended_next_shadow": "refine",
            "contract_recommended_next_plan_shadow": "deep_probe",
            "contract_pass_shadow_reason": "contract_score_below_threshold",
            "contract_pass_shadow_diff": True,
            "contract_routing_signal_shadow_diff": True,
        }
    )

    fr.final_report_node(state)  # type: ignore[arg-type]

    evidence = fake_tracer.node_events[0]["payload"]["dimension_evidence"][0]
    assert evidence["pass_shadows"] == [
        {
            "turn_idx": 0,
            "available": True,
            "score": 5.71,
            "quality_threshold": 7.5,
            "passed": False,
            "recommended_next": "refine",
            "recommended_next_plan": "deep_probe",
            "reason": "contract_score_below_threshold",
            "legacy_passed": True,
            "legacy_recommended_next": "advance",
            "legacy_recommended_next_plan": None,
            "pass_diff": True,
            "routing_signal_diff": True,
        }
    ]


def test_cancelled_session_marks_final_status_in_payload(
    fake_tracer: _RecordingTracer,
) -> None:
    """An interview cancelled mid-flight must still emit the row but
    with ``final_status='cancelled'`` so analytics can tell the two
    apart in the audit trail."""
    state = _state_for_completed_session()
    state["status"] = "cancelled"

    fr.final_report_node(state)  # type: ignore[arg-type]

    assert len(fake_tracer.node_events) == 1
    event = fake_tracer.node_events[0]
    assert event["node"] == "final_report"
    assert event["payload"]["final_status"] == "cancelled"
    assert event["payload"]["report_status"] == "cancelled"
    assert event["payload"]["training_plan_queued"] is False
    assert event["payload"]["experience_extractor_queued"] is False
    assert event["status"] == "cancelled"


def test_tracer_failures_do_not_break_node(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The new call is wrapped in try/except just like every other
    tracer call in this module: a DB outage on the trace path must
    never fail the running interview."""

    class _BoomTracer:
        def trace_final_report(self, _state: dict[str, Any]) -> None:
            raise RuntimeError("session-level boom")

        def trace_node_event(self, *_args: Any, **_kwargs: Any) -> None:
            raise RuntimeError("node-level boom")

    monkeypatch.setattr(fr, "get_tracer", lambda: _BoomTracer())

    out = fr.final_report_node(_state_for_completed_session())  # type: ignore[arg-type]

    assert out["status"] == "completed"
    assert "final_report" in out
