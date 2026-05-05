"""Record a candidate-initiated skip without scoring the answer."""
from __future__ import annotations

from typing import Any

from app.core.logging import get_logger
from app.engine.workflow.state import InterviewState

log = get_logger(__name__)


def _next_dimension(
    dimensions: list[str],
    status: dict[str, str],
    current: str | None,
) -> tuple[str | None, dict[str, str]]:
    if not dimensions:
        return current, status
    next_status = dict(status)
    if current and next_status.get(current) == "active":
        next_status[current] = "pending"
    for dim in dimensions:
        if dim != current and next_status.get(dim) in {None, "pending"}:
            next_status[dim] = "active"
            return dim, next_status
    return current, next_status


def skip_question_node(state: InterviewState) -> dict[str, Any]:
    turn_idx = int(state.get("turn_idx", 0))
    formal_turn_idx = int(state.get("formal_turn_idx", turn_idx))
    budget = max(0, int(state.get("turn_budget_remaining", 0)) - 1)
    question = state.get("current_question") or {}
    dimension = str(
        question.get("dimension") or state.get("current_dimension") or "unknown"
    )
    is_self_intro = question.get("question_type") == "self_intro"
    next_formal_turn_idx = formal_turn_idx if is_self_intro else formal_turn_idx + 1
    skip_reason = state.get("skip_reason")
    dimensions = list(state.get("dimensions") or [])
    next_dimension, next_status = _next_dimension(
        dimensions,
        dict(state.get("dimension_status") or {}),
        None if is_self_intro else dimension,
    )

    qa_entry = {
        "turn_idx": formal_turn_idx,
        "dimension": dimension,
        "question": question.get("question", ""),
        "answer": "",
        "answer_intent": "skipped",
        "skip_reason": skip_reason,
        "evaluation": {
            "score": None,
            "passed": False,
            "strengths": [],
            "weaknesses": ["本题已跳过"],
            "rationale": "候选人选择先跳过本题，本轮不纳入评分。",
            "skipped": True,
        },
        "current_question": question,
    }

    log.info(
        "skip_question turn=%d formal=%d dimension=%s",
        turn_idx,
        formal_turn_idx,
        dimension,
    )
    return {
        "qa_history": [qa_entry],
        "messages": [
            {
                "role": "user",
                "turn_idx": turn_idx,
                "kind": "skip",
                "content": "跳过本题",
            },
        ],
        "current_answer": "",
        "current_answer_intent": "skipped",
        "current_question": {},
        "skip_reason": None,
        "turn_idx": turn_idx + 1,
        "formal_turn_idx": next_formal_turn_idx,
        "turn_budget_remaining": budget,
        "current_dimension": next_dimension or dimension,
        "dimension_status": next_status,
    }
