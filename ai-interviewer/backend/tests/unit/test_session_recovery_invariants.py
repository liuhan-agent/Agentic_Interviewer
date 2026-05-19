from __future__ import annotations

import threading
from types import SimpleNamespace
from typing import Any

from app.services.session_manager import (
    SessionHandle,
    SessionManager,
    _extract_last_turn_evaluation,
)


def _manager_with_workflow(values: dict[str, Any], next_nodes: tuple[str, ...]):
    manager = SessionManager.__new__(SessionManager)
    manager._sessions = {}
    manager._lock = threading.Lock()

    class _Workflow:
        def get_state(self, _config: dict[str, Any]) -> SimpleNamespace:
            return SimpleNamespace(values=values, next=next_nodes)

    manager._workflow = _Workflow()
    return manager


def test_recover_waiting_session_rebuilds_handle_invariants() -> None:
    question = {"question": "Q?", "dimension": "system_design"}
    values = {
        "session_id": "sess-recover",
        "trace_id": "trace-recover",
        "candidate": {"name": "Alex"},
        "job_spec": {"title": "Backend Engineer", "level": "senior"},
        "current_question": question,
        "turn_idx": 2,
        "max_turns": 8,
        "mode": "mixed",
    }
    manager = _manager_with_workflow(values, ("wait_answer",))
    persisted: list[tuple[SessionHandle, dict[str, Any], int]] = []

    manager._load_persisted_session_for_retry = lambda _session_id: None  # type: ignore[method-assign]
    manager._persist_interrupt = lambda handle, q, turn: persisted.append(  # type: ignore[method-assign]
        (handle, q, turn)
    )

    handle = manager.recover_waiting_session("sess-recover")

    assert handle is not None
    assert handle.current_question == question
    assert handle.turn_idx == 2
    assert handle.asked_turn == 1
    assert handle.max_turns == 8
    assert handle.question_event.is_set()
    assert handle.done_event.is_set() is False
    assert handle.candidate_name == "Alex"
    assert handle.job_title == "Backend Engineer"
    assert handle.job_level == "senior"
    assert handle.mode == "mixed"
    assert manager._sessions["sess-recover"] is handle
    assert persisted == [(handle, question, 2)]


def test_recover_waiting_session_returns_none_when_checkpoint_not_waiting() -> None:
    manager = _manager_with_workflow(
        {
            "current_question": {"question": "Q?"},
            "turn_idx": 2,
        },
        ("evaluator",),
    )
    manager._load_persisted_session_for_retry = lambda _session_id: None  # type: ignore[method-assign]

    assert manager.recover_waiting_session("sess-not-waiting") is None
    assert manager._sessions == {}


def test_recover_waiting_session_returns_none_without_checkpoint_question() -> None:
    manager = _manager_with_workflow(
        {
            "current_question": {},
            "turn_idx": 2,
        },
        ("wait_answer",),
    )
    manager._load_persisted_session_for_retry = lambda _session_id: None  # type: ignore[method-assign]

    assert manager.recover_waiting_session("sess-no-question") is None
    assert manager._sessions == {}


# -----------------------------------------------------------------------
# _extract_last_turn_evaluation: real-time feedback projection (#9)
# -----------------------------------------------------------------------


def test_extract_last_turn_evaluation_returns_none_for_empty_history() -> None:
    assert _extract_last_turn_evaluation(None) is None
    assert _extract_last_turn_evaluation([]) is None


def test_extract_last_turn_evaluation_projects_minimal_summary() -> None:
    qa_history = [
        {
            "turn_idx": 2,
            "dimension": "system_design",
            "answer_intent": "normal",
            "evaluation": {
                "score": 7.5,
                "passed": True,
                "strengths": ["架构层次清晰", "对取舍解释具体", "命中关键约束"],
                "weaknesses": ["容量估算不够量化", "缓存失效场景没展开"],
                "rubric_coverage": {
                    "system_design": "covered",
                    "trade_off_reasoning": "partial",
                },
                "rationale": "整体回答覆盖了主要架构层次……",
            },
        },
    ]

    summary = _extract_last_turn_evaluation(qa_history)

    assert summary == {
        "turn_idx": 2,
        "dimension": "system_design",
        "score": 7.5,
        "passed": True,
        "strengths": ["架构层次清晰", "对取舍解释具体", "命中关键约束"],
        "weaknesses": ["容量估算不够量化", "缓存失效场景没展开"],
        "rubric_coverage": {
            "system_design": "covered",
            "trade_off_reasoning": "partial",
        },
    }


def test_extract_last_turn_evaluation_surfaces_fallback_notice() -> None:
    qa_history = [
        {
            "turn_idx": 1,
            "dimension": "system_design",
            "answer_intent": "normal",
            "evaluation": {
                "score": 5.0,
                "passed": False,
                "source": "fallback",
                "fallback_reason": "evaluator_llm_timeout",
                "strengths": ["本轮回答已记录到面试 transcript 中。"],
                "weaknesses": [],
                "system_warnings": ["评估模型暂时不可用，已使用保守兜底评价。"],
            },
        },
    ]
    summary = _extract_last_turn_evaluation(qa_history)
    assert summary == {
        "turn_idx": 1,
        "dimension": "system_design",
        "score": None,
        "passed": False,
        "source": "fallback",
        "fallback_reason": "evaluator_llm_timeout",
        "strengths": [],
        "weaknesses": [],
        "system_warnings": ["评估模型暂时不可用，已使用保守兜底评价。"],
        "rubric_coverage": {},
    }


def test_extract_last_turn_evaluation_skips_non_scoring_intents() -> None:
    for intent in ("empty", "clarification", "repeat", "too_short", "skipped"):
        qa_history = [
            {
                "turn_idx": 1,
                "dimension": "system_design",
                "answer_intent": intent,
                "evaluation": {
                    "score": 6.0,
                    "passed": False,
                    "strengths": [],
                    "weaknesses": ["回答太短"],
                },
            },
        ]
        assert _extract_last_turn_evaluation(qa_history) is None, intent


def test_extract_last_turn_evaluation_skips_explicitly_skipped_turn() -> None:
    qa_history = [
        {
            "turn_idx": 1,
            "dimension": "communication",
            "answer_intent": "normal",
            "evaluation": {
                "score": None,
                "passed": False,
                "skipped": True,
                "weaknesses": ["本题已跳过"],
            },
        },
    ]
    assert _extract_last_turn_evaluation(qa_history) is None


def test_extract_last_turn_evaluation_keeps_all_feedback_items() -> None:
    """The polling response carries all feedback items; the UI decides how
    many to preview and can expand without needing a second backend path."""
    qa_history = [
        {
            "turn_idx": 3,
            "dimension": "problem_solving",
            "answer_intent": "normal",
            "evaluation": {
                "score": 6.5,
                "passed": False,
                "strengths": ["s1", "s2", "s3", "s4"],
                "weaknesses": ["w1", "w2", "w3", "w4", "w5"],
            },
        },
    ]
    summary = _extract_last_turn_evaluation(qa_history)
    assert summary is not None
    assert summary["strengths"] == ["s1", "s2", "s3", "s4"]
    assert summary["weaknesses"] == ["w1", "w2", "w3", "w4", "w5"]


def test_recover_waiting_session_rebuilds_last_turn_evaluation_from_checkpoint() -> None:
    """After a process restart, ``recover_waiting_session`` should also
    re-derive the last-turn evaluation summary from the checkpoint's
    qa_history so the in-interview feedback card keeps working."""
    qa_history = [
        {
            "turn_idx": 1,
            "dimension": "technical_depth",
            "answer_intent": "normal",
            "evaluation": {
                "score": 8.0,
                "passed": True,
                "strengths": ["对索引原理理解到位"],
                "weaknesses": ["没有量化压测数据"],
                "rubric_coverage": {"technical_depth": "covered"},
            },
        },
    ]
    values = {
        "session_id": "sess-recover-eval",
        "trace_id": "trace-recover-eval",
        "candidate": {"name": "Alex"},
        "job_spec": {"title": "Backend Engineer", "level": "senior"},
        "current_question": {"question": "Q2?", "dimension": "technical_depth"},
        "turn_idx": 2,
        "max_turns": 8,
        "mode": "mixed",
        "qa_history": qa_history,
    }
    manager = _manager_with_workflow(values, ("wait_answer",))
    manager._load_persisted_session_for_retry = lambda _session_id: None  # type: ignore[method-assign]
    manager._persist_interrupt = lambda *_args, **_kwargs: None  # type: ignore[method-assign]

    handle = manager.recover_waiting_session("sess-recover-eval")

    assert handle is not None
    assert handle.last_turn_evaluation == {
        "turn_idx": 1,
        "dimension": "technical_depth",
        "score": 8.0,
        "passed": True,
        "strengths": ["对索引原理理解到位"],
        "weaknesses": ["没有量化压测数据"],
        "rubric_coverage": {"technical_depth": "covered"},
    }


def test_recover_waiting_session_handles_checkpoint_without_qa_history() -> None:
    """Recovery on the very first turn (no qa_history yet) should leave
    last_turn_evaluation as None rather than crashing."""
    values = {
        "session_id": "sess-fresh",
        "trace_id": "trace-fresh",
        "candidate": {},
        "job_spec": {},
        "current_question": {"question": "Q1?", "dimension": "system_design"},
        "turn_idx": 1,
        "max_turns": 8,
        "mode": "mixed",
    }
    manager = _manager_with_workflow(values, ("wait_answer",))
    manager._load_persisted_session_for_retry = lambda _session_id: None  # type: ignore[method-assign]
    manager._persist_interrupt = lambda *_args, **_kwargs: None  # type: ignore[method-assign]

    handle = manager.recover_waiting_session("sess-fresh")

    assert handle is not None
    assert handle.last_turn_evaluation is None
