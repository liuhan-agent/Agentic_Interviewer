from __future__ import annotations

from typing import Any

from app.services.interview_question_response import build_question_poll_payload


def _base_payload(**overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "session_id": "sess-question",
        "question": {"question": "Q?", "dimension": "system_design"},
        "done": False,
        "cancelled": False,
        "final_status": None,
        "final_report": None,
        "error": None,
        "error_kind": None,
        "retryable": False,
        "turn_idx": 3,
        "max_turns": 8,
        "previous_turn_evaluation": None,
        "server_latency_ms": None,
    }
    values.update(overrides)
    return build_question_poll_payload(**values)


def test_waiting_payload_preserves_live_question_fields() -> None:
    previous = {"score": 7.5, "passed": True}

    payload = _base_payload(
        previous_turn_evaluation=previous,
        server_latency_ms=456,
    )

    assert payload == {
        "session_id": "sess-question",
        "status": "waiting_for_answer",
        "turn_idx": 3,
        "question": {"question": "Q?", "dimension": "system_design"},
        "max_turns": 8,
        "previous_turn_evaluation": previous,
        "server_latency_ms": 456,
    }


def test_pending_payload_when_no_question_and_not_done() -> None:
    payload = _base_payload(question=None)

    assert payload == {
        "session_id": "sess-question",
        "status": "pending",
        "turn_idx": 3,
        "question": None,
        "max_turns": 8,
        "previous_turn_evaluation": None,
        "server_latency_ms": None,
    }


def test_completed_payload_includes_final_report() -> None:
    payload = _base_payload(
        question=None,
        done=True,
        final_report={"overall_score": 8.2},
        previous_turn_evaluation={"score": 8.2},
        server_latency_ms=12,
    )

    assert payload == {
        "session_id": "sess-question",
        "status": "completed",
        "question": None,
        "final_report": {"overall_score": 8.2},
        "max_turns": 8,
        "previous_turn_evaluation": {"score": 8.2},
        "server_latency_ms": 12,
    }


def test_cancelled_payload_omits_final_report() -> None:
    payload = _base_payload(
        question=None,
        done=True,
        cancelled=False,
        final_status="cancelled",
        final_report={"overall_score": 8.2},
    )

    assert payload == {
        "session_id": "sess-question",
        "status": "cancelled",
        "question": None,
        "max_turns": 8,
        "previous_turn_evaluation": None,
        "server_latency_ms": None,
    }
    assert "final_report" not in payload


def test_error_payload_uses_terminal_error_shape_and_retryable_flag() -> None:
    payload = _base_payload(
        question=None,
        done=True,
        error="question generation failed",
        error_kind="question_generation_failed",
        retryable=True,
        previous_turn_evaluation={"score": 6.5},
        server_latency_ms=789,
    )

    assert payload == {
        "session_id": "sess-question",
        "status": "error",
        "question": None,
        "error": "question generation failed",
        "error_kind": "question_generation_failed",
        "retryable": True,
        "previous_turn_evaluation": {"score": 6.5},
        "server_latency_ms": 789,
    }
