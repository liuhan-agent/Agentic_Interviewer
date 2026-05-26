"""Tests for per-session trace summary independent of node pagination."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any


class _SessionRow:
    session_id = "sess-long"
    trace_id = "trace-long"
    status = "completed"
    final_report = {"overall_score": 8.2, "overall_verdict": "hire"}


class _TraceRow:
    def __init__(self, idx: int, node: str) -> None:
        self.id = idx + 1
        self.trace_id = "trace-long"
        self.session_id = "sess-long"
        self.turn_idx = idx
        self.node = node
        self.dimension = "system_design"
        self.action_id = "deep_probe"
        self.policy_id = "policy"
        self.context_key = "senior:system_design"
        self.policy_context_keys = ["senior:system_design"]
        self.score = 8.0 if node == "evaluator" else None
        self.passed = True if node == "evaluator" else None
        self.immediate_reward = 0.8 if node == "reward_update" else None
        self.immediate_reward_applied = node == "reward_update"
        self.question = "Q"
        self.answer = "A"
        self.evaluation = {"score": 8.0, "passed": True} if node == "evaluator" else None
        self.state_snapshot = {"payload": {"node": node}}
        self.langsmith_run_id = None
        self.created_at = datetime.now(UTC)


class _FakeQuery:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows
        self._offset = 0
        self._limit: int | None = None

    def filter(self, *_args: Any, **_kwargs: Any) -> "_FakeQuery":
        return self

    def group_by(self, *_args: Any) -> "_FakeQuery":
        return self

    def order_by(self, *_args: Any) -> "_FakeQuery":
        return self

    def offset(self, n: int) -> "_FakeQuery":
        self._offset = n
        return self

    def limit(self, n: int) -> "_FakeQuery":
        self._limit = n
        return self

    def all(self) -> list[Any]:
        if self._limit is None:
            return list(self._rows[self._offset :])
        return list(self._rows[self._offset : self._offset + self._limit])


class _FakeSession:
    def __init__(self, traces: list[_TraceRow]) -> None:
        self._traces = traces

    def get(self, *_args: Any) -> _SessionRow:
        return _SessionRow()

    def query(self, *args: Any) -> _FakeQuery:
        if len(args) > 1:
            counts: dict[str, int] = {}
            for trace in self._traces:
                counts[trace.node] = counts.get(trace.node, 0) + 1
            return _FakeQuery([(node, count) for node, count in counts.items()])
        return _FakeQuery(self._traces)


def test_trace_summary_uses_all_nodes_even_when_response_is_paginated(
    monkeypatch,
) -> None:
    from app.api.v1 import admin as admin_mod

    traces = [_TraceRow(i, "evaluator") for i in range(120)]
    traces.append(_TraceRow(120, "final_report"))

    @contextmanager
    def _fake_get_session():
        yield _FakeSession(traces)

    monkeypatch.setattr("app.models.get_session", _fake_get_session)

    payload = admin_mod._interview_session_trace_payload(
        session_id="sess-long",
        limit=100,
    )

    assert len(payload["nodes"]) == 100
    assert payload["node_count_total"] == 121
    assert payload["nodes_offset"] == 0
    assert payload["nodes_limit"] == 100
    assert payload["nodes_has_more"] is True
    assert payload["trace_count"] == 121
    assert payload["final_report_trace_count"] == 1
    assert payload["trace_health"] == "complete"


def test_trace_node_payload_hides_legacy_ask_question_answer_and_evaluation() -> None:
    from app.api.v1 import admin as admin_mod

    trace = _TraceRow(0, "ask_question")
    trace.answer = "stale answer from previous turn"
    trace.evaluation = {"score": 8.0, "passed": True}

    payload = admin_mod._trace_node_payload(trace)

    assert payload["node"] == "ask_question"
    assert payload["question"] == "Q"
    assert payload["answer_excerpt"] is None
    assert payload["evaluation"] is None


def test_trace_node_payload_enriches_legacy_skill_refs_from_lookup() -> None:
    from app.api.v1 import admin as admin_mod

    trace = _TraceRow(0, "ask_question")
    trace.state_snapshot = {
        "payload": {
            "selection_artifacts": {
                "skills": {
                    "refs": [
                        {
                            "id": "tech_debug_root_cause_probe",
                            "filename": "tech_debug_root_cause_probe.md",
                            "name": "Debug Root Cause Probe",
                            "description": "Keep debugging answers anchored.",
                            "display_name_zh": "",
                            "display_description_zh": "",
                        }
                    ]
                }
            }
        }
    }

    payload = admin_mod._trace_node_payload(
        trace,
        skill_display_lookup={
            "tech_debug_root_cause_probe": {
                "display_name_zh": "调试根因追问卡",
                "display_description_zh": "引导调试回答锚定证据和根因。",
            }
        },
    )

    ref = payload["payload"]["selection_artifacts"]["skills"]["refs"][0]
    assert ref["name"] == "Debug Root Cause Probe"
    assert ref["description"] == "Keep debugging answers anchored."
    assert ref["display_name_zh"] == "调试根因追问卡"
    assert ref["display_description_zh"] == "引导调试回答锚定证据和根因。"


def test_trace_node_payload_keeps_evaluator_answer_and_evaluation() -> None:
    from app.api.v1 import admin as admin_mod

    trace = _TraceRow(0, "evaluator")

    payload = admin_mod._trace_node_payload(trace)

    assert payload["node"] == "evaluator"
    assert payload["answer_excerpt"] == "A"
    assert payload["evaluation"] == {"score": 8.0, "passed": True}
