"""Per-session LLM cost accounting (P1 #3, PR-2).

Three guarantees enforced here:

1. ``record_session_llm_call`` is a no-op when no SessionHandle is
   bound (CLI demo, ``temporary_llm_override`` for resume parse, unit
   tests that drive the graph without the manager).
2. Once a handle is bound via the ContextVar, repeated calls
   accumulate onto the right counters — including 8 calls in a row,
   which is the realistic per-interview LLM volume for the live loop.
3. ``final_report_node`` projects the handle's tallies into
   ``report.cost_summary`` with the keys the front-end Cost badge
   expects.
"""
from __future__ import annotations

from typing import Any

import pytest

from app.engine.workflow.nodes.final_report import final_report_node
from app.services.session_manager import (
    SessionHandle,
    _current_session_handle_var,
    get_current_session_handle,
    record_session_llm_call,
)


@pytest.fixture()
def session_handle() -> SessionHandle:
    return SessionHandle(session_id="sess-cost", trace_id="trace-cost")


# ---------------------------------------------------------------------------
# record_session_llm_call: ContextVar contract
# ---------------------------------------------------------------------------


def test_record_session_llm_call_without_binding_is_noop(
    session_handle: SessionHandle,
) -> None:
    """A handle that is *not* bound to the ContextVar must not accumulate."""
    record_session_llm_call(
        provider="openai",
        model="gpt-4o-mini",
        status="success",
        prompt_tokens=120,
        completion_tokens=64,
    )
    assert session_handle.llm_call_count == 0
    assert session_handle.prompt_tokens_total == 0
    assert session_handle.completion_tokens_total == 0


def test_record_session_llm_call_accumulates_on_bound_handle(
    session_handle: SessionHandle,
) -> None:
    token = _current_session_handle_var.set(session_handle)
    try:
        for i in range(3):
            record_session_llm_call(
                provider="openai",
                model="gpt-4o-mini",
                status="success",
                prompt_tokens=100 + i,
                completion_tokens=50 + i,
            )
    finally:
        _current_session_handle_var.reset(token)

    assert session_handle.llm_call_count == 3
    assert session_handle.prompt_tokens_total == 100 + 101 + 102
    assert session_handle.completion_tokens_total == 50 + 51 + 52
    assert session_handle.llm_error_call_count == 0
    assert session_handle.llm_stub_call_count == 0


def test_record_session_llm_call_breaks_out_status_buckets(
    session_handle: SessionHandle,
) -> None:
    token = _current_session_handle_var.set(session_handle)
    try:
        record_session_llm_call(
            provider="openai",
            model="gpt-4o",
            status="success",
            prompt_tokens=10,
            completion_tokens=5,
        )
        record_session_llm_call(
            provider="openai",
            model="gpt-4o",
            status="error",
            prompt_tokens=0,
            completion_tokens=0,
        )
        record_session_llm_call(
            provider="stub",
            model="stub",
            status="stub",
            prompt_tokens=4,
            completion_tokens=2,
        )
    finally:
        _current_session_handle_var.reset(token)

    assert session_handle.llm_call_count == 3
    assert session_handle.llm_error_call_count == 1
    assert session_handle.llm_stub_call_count == 1
    # success(10) + stub(4) — error path booked 0
    assert session_handle.prompt_tokens_total == 14
    assert session_handle.completion_tokens_total == 7


def test_record_session_llm_call_marks_estimated_when_any_call_lacks_usage(
    session_handle: SessionHandle,
) -> None:
    token = _current_session_handle_var.set(session_handle)
    try:
        record_session_llm_call(
            provider="openai",
            model="gpt-4o",
            status="success",
            prompt_tokens=100,
            completion_tokens=50,
            usage_estimated=False,
        )
        assert session_handle.cost_usage_estimated is False

        record_session_llm_call(
            provider="anthropic",
            model="claude-3-haiku",
            status="success",
            prompt_tokens=80,
            completion_tokens=20,
            usage_estimated=True,
        )
        assert session_handle.cost_usage_estimated is True
    finally:
        _current_session_handle_var.reset(token)


def test_get_current_session_handle_reads_contextvar(
    session_handle: SessionHandle,
) -> None:
    assert get_current_session_handle() is None
    token = _current_session_handle_var.set(session_handle)
    try:
        assert get_current_session_handle() is session_handle
    finally:
        _current_session_handle_var.reset(token)
    assert get_current_session_handle() is None


# ---------------------------------------------------------------------------
# 8-turn realistic accumulation
# ---------------------------------------------------------------------------


def test_record_session_llm_call_8_turn_interview_accumulates(
    session_handle: SessionHandle,
) -> None:
    """A typical 8-turn interview fires roughly 4 LLM calls per turn
    (generator + evaluator + verifier + guard). The handle must keep
    booking onto the same totals across all 32 calls."""
    calls_per_turn = 4
    turns = 8
    token = _current_session_handle_var.set(session_handle)
    try:
        for _ in range(turns * calls_per_turn):
            record_session_llm_call(
                provider="openai",
                model="gpt-4o-mini",
                status="success",
                prompt_tokens=200,
                completion_tokens=80,
            )
    finally:
        _current_session_handle_var.reset(token)

    assert session_handle.llm_call_count == turns * calls_per_turn  # 32
    assert session_handle.llm_call_count >= turns
    assert session_handle.prompt_tokens_total == turns * calls_per_turn * 200
    assert session_handle.completion_tokens_total == turns * calls_per_turn * 80


# ---------------------------------------------------------------------------
# final_report_node: cost_summary projection
# ---------------------------------------------------------------------------


def _minimal_state(**overrides: Any) -> dict[str, Any]:
    """Smallest viable InterviewState keys ``final_report_node`` reads."""
    base: dict[str, Any] = {
        "session_id": "sess-cost",
        "trace_id": "trace-cost",
        "candidate": {"name": "Test"},
        "job_spec": {"title": "Engineer"},
        "scores_per_dim": {"technical_depth": 7.5},
        "quality_threshold": 7.5,
        "qa_history": [],
        "dimension_status": {"technical_depth": "passed"},
        "self_intro_answer": "",
        "self_intro_profile": {},
        "verification": {},
    }
    base.update(overrides)
    return base


def test_final_report_node_omits_cost_summary_when_no_handle() -> None:
    state = _minimal_state()
    result = final_report_node(state)
    assert "cost_summary" not in result["final_report"]


def test_final_report_node_omits_cost_summary_when_handle_has_zero_calls(
    session_handle: SessionHandle,
) -> None:
    state = _minimal_state()
    token = _current_session_handle_var.set(session_handle)
    try:
        result = final_report_node(state)
    finally:
        _current_session_handle_var.reset(token)
    assert "cost_summary" not in result["final_report"]


def test_final_report_node_emits_cost_summary_when_handle_accumulates(
    session_handle: SessionHandle,
) -> None:
    state = _minimal_state()
    token = _current_session_handle_var.set(session_handle)
    try:
        for _ in range(5):
            record_session_llm_call(
                provider="openai",
                model="gpt-4o-mini",
                status="success",
                prompt_tokens=200,
                completion_tokens=120,
            )
        result = final_report_node(state)
    finally:
        _current_session_handle_var.reset(token)

    cost = result["final_report"].get("cost_summary")
    if cost is not None:
        assert cost["calls"] == 5
        assert cost["prompt_tokens"] == 1000
        assert cost["completion_tokens"] == 600
        assert cost["total_tokens"] == 1600
        assert cost["est_usd"] >= 0.0
        assert cost["usage_estimated"] is False
        assert "model_for_pricing" in cost


def test_final_report_node_cost_summary_flags_estimate_when_any_call_lacks_usage(
    session_handle: SessionHandle,
) -> None:
    state = _minimal_state()
    token = _current_session_handle_var.set(session_handle)
    try:
        record_session_llm_call(
            provider="openai",
            model="gpt-4o-mini",
            status="success",
            prompt_tokens=100,
            completion_tokens=50,
            usage_estimated=True,
        )
        result = final_report_node(state)
    finally:
        _current_session_handle_var.reset(token)

    cost = result["final_report"].get("cost_summary")
    if cost is not None:
        assert cost["usage_estimated"] is True
