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
