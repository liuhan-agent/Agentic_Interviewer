from __future__ import annotations

from typing import Any

from app.services.interview_runtime import terminal_error_payload


def build_question_poll_payload(
    *,
    session_id: str,
    question: dict[str, Any] | None,
    done: bool,
    cancelled: bool,
    final_status: str | None,
    final_report: dict[str, Any] | None,
    error: str | None,
    error_kind: str | None,
    retryable: bool,
    turn_idx: int,
    max_turns: int | None,
    previous_turn_evaluation: dict[str, Any] | None,
    server_latency_ms: int | None,
) -> dict[str, Any]:
    """Project live session state into the poll-question API payload."""
    if question is None and done:
        if cancelled or final_status == "cancelled":
            return {
                "session_id": session_id,
                "status": "cancelled",
                "question": None,
                "max_turns": max_turns,
                "previous_turn_evaluation": previous_turn_evaluation,
                "server_latency_ms": server_latency_ms,
            }
        if error:
            payload = terminal_error_payload(
                session_id=session_id,
                error=error,
                error_kind=error_kind,
                retryable=retryable,
            )
            payload["previous_turn_evaluation"] = previous_turn_evaluation
            payload["server_latency_ms"] = server_latency_ms
            return payload
        return {
            "session_id": session_id,
            "status": "completed",
            "question": None,
            "final_report": final_report,
            "max_turns": max_turns,
            "previous_turn_evaluation": previous_turn_evaluation,
            "server_latency_ms": server_latency_ms,
        }

    return {
        "session_id": session_id,
        "status": "waiting_for_answer" if question else "pending",
        "turn_idx": turn_idx,
        "question": question,
        "max_turns": max_turns,
        "previous_turn_evaluation": previous_turn_evaluation,
        "server_latency_ms": server_latency_ms,
    }
