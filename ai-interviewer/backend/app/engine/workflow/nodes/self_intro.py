"""Opening self-introduction phase."""
from __future__ import annotations

import secrets
from typing import Any

from app.core.logging import get_logger
from app.core.settings import get_settings
from app.engine.agents.self_intro import parse_self_intro_profile
from app.engine.workflow.state import InterviewState
from app.services.resume_vector_jobs import wait_for_resume_vector_status
from app.services.session_anchor_vectorize import vectorize_self_intro_anchor_cards

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
    self_intro_vector_status = _vectorize_self_intro_for_node(
        session_id=str(state.get("session_id") or ""),
        turn_idx=int(turn_idx or 0),
        sanitized_answer=sanitised_answer,
        profile=profile,
    )
    candidate = dict(state.get("candidate") or {})
    resume_vector_status = _wait_resume_vector_for_formal_questions(
        session_id=str(state.get("session_id") or ""),
        candidate=candidate,
    )
    if resume_vector_status:
        candidate["resume_vector_status"] = resume_vector_status
    clear_raw_answer_for_state(state)
    return {
        "intro_completed": True,
        "candidate": candidate,
        "self_intro_answer": sanitised_answer,
        "self_intro_profile": profile,
        "self_intro_vector_status": self_intro_vector_status,
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


def _vectorize_self_intro_for_node(
    *,
    session_id: str,
    turn_idx: int,
    sanitized_answer: str,
    profile: dict[str, Any],
) -> dict[str, Any]:
    revision_id = secrets.token_urlsafe(18)
    if not session_id:
        return {
            "status": "skipped",
            "source_type": "self_intro",
            "self_intro_revision_id": revision_id,
            "skipped_reason": "no_session_id",
        }
    try:
        return vectorize_self_intro_anchor_cards(
            session_id=session_id,
            self_intro_revision_id=revision_id,
            turn_idx=turn_idx,
            sanitized_answer=sanitized_answer,
            anchor_cards=profile.get("anchor_cards") or [],
            profile=profile,
        )
    except Exception as exc:  # pragma: no cover - workflow must degrade
        log.warning("self_intro vectorization failed: %s", exc)
        return {
            "status": "failed",
            "source_type": "self_intro",
            "self_intro_revision_id": revision_id,
            "error": str(exc) or exc.__class__.__name__,
        }


def _wait_resume_vector_for_formal_questions(
    *,
    session_id: str,
    candidate: dict[str, Any],
) -> dict[str, Any] | None:
    status = candidate.get("resume_vector_status") or {}
    if not isinstance(status, dict):
        return None
    if status.get("status") not in {"pending_background", "pending_node"}:
        return None
    source_id = (
        candidate.get("resume_source_id")
        or status.get("resume_source_id")
        or status.get("source_artifact_id")
    )
    if not source_id:
        return None
    timeout_ms = int(get_settings().session_anchor_resume_ready_wait_ms or 12000)
    return wait_for_resume_vector_status(
        session_id=session_id,
        resume_source_id=str(source_id),
        parsed=candidate.get("resume_parsed")
        if isinstance(candidate.get("resume_parsed"), dict)
        else None,
        embedding_override=_runtime_embedding_override(),
        timeout_ms=timeout_ms,
    )


def _runtime_embedding_override() -> dict[str, Any] | None:
    try:
        from app.services.session_manager import get_llm_override

        llm_config = get_llm_override()
    except Exception:
        return None
    if not isinstance(llm_config, dict):
        return None
    override = llm_config.get("embedding_override")
    return override if isinstance(override, dict) else None
