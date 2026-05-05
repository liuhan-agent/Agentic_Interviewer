"""Opening self-introduction phase."""
from __future__ import annotations

from typing import Any

from app.core.logging import get_logger
from app.engine.agents.self_intro import parse_self_intro_profile
from app.engine.workflow.state import InterviewState

from .wait_answer import clear_raw_answer_for_state, get_raw_answer_for_state

log = get_logger(__name__)

SELF_INTRO_QUESTION = (
    "你好，欢迎开始这场面试。请先用 1-2 分钟做一个自我介绍，"
    "重点包括你的背景、最有代表性的项目，以及你希望我重点了解的能力方向。"
)


def self_intro_question_node(state: InterviewState) -> dict[str, Any]:
    if state.get("intro_completed"):
        return {}
    question = {
        "question": SELF_INTRO_QUESTION,
        "question_type": "self_intro",
        "dimension": "communication",
        "rubric_points": ["structure", "focus"],
    }
    return {
        "current_question": question,
        "current_dimension": "communication",
        "intro_completed": False,
        "messages": [
            {
                "role": "assistant",
                "turn_idx": state.get("turn_idx", 0),
                "kind": "question",
                "question_type": "self_intro",
                "content": SELF_INTRO_QUESTION,
            }
        ],
    }


def self_intro_parse_node(state: InterviewState) -> dict[str, Any]:
    sanitised_answer = state.get("current_answer", "") or ""
    raw_answer = get_raw_answer_for_state(state) or sanitised_answer
    profile = parse_self_intro_profile(
        answer=raw_answer,
        candidate=state.get("candidate", {}) or {},
        job_spec=state.get("job_spec", {}) or {},
    )
    turn_idx = state.get("turn_idx", 0)
    log.info(
        "self_intro_parse turn=%d projects=%d skills=%d status=%s",
        turn_idx,
        len(profile.get("emphasized_projects") or []),
        len(profile.get("emphasized_skills") or []),
        profile.get("parse_status"),
    )
    clear_raw_answer_for_state(state)
    return {
        "intro_completed": True,
        "self_intro_answer": sanitised_answer,
        "self_intro_profile": profile,
        "turn_idx": turn_idx + 1,
        "formal_turn_idx": state.get("formal_turn_idx", 0),
        "current_answer": "",
        "current_answer_raw": "",
        "current_answer_raw_ref": "",
        "current_question": {},
        "messages": [
            {
                "role": "system",
                "turn_idx": turn_idx,
                "kind": "self_intro_profile",
                "content": profile,
            }
        ],
    }
