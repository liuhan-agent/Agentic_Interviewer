"""Opening self-introduction phase."""
from __future__ import annotations

import secrets
from typing import Any

from app.core.logging import get_logger
from app.core.settings import get_settings
from app.core.tracer import get_tracer
from app.engine.agents.self_intro import parse_self_intro_profile
from app.engine.workflow.state import InterviewState
from app.services.resume_vector_jobs import wait_for_resume_vector_status
from app.services.session_anchor_vectorize import vectorize_self_intro_anchor_cards
from app.services.trace_nodes import trace_node_metadata, trace_status_summary

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
    _trace_self_intro_question_opening(state, question=question)
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
    _trace_self_intro_parse_opening(
        state,
        profile=profile,
        self_intro_vector_status=self_intro_vector_status,
    )
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


def _opening_trace_state(
    state: InterviewState,
    *,
    current_question: dict[str, Any] | None = None,
    current_dimension: str | None = None,
) -> dict[str, Any]:
    trace_state: dict[str, Any] = {
        "session_id": state.get("session_id", ""),
        "trace_id": state.get("trace_id", ""),
        "turn_idx": 0,
        "formal_turn_idx": state.get("formal_turn_idx", 0),
        "current_question": current_question or {},
    }
    if current_dimension:
        trace_state["current_dimension"] = current_dimension
    return trace_state


def _trace_self_intro_question_opening(
    state: InterviewState,
    *,
    question: dict[str, Any],
) -> None:
    payload = {
        **trace_node_metadata("self_intro_question"),
        "phase": "opening",
        "question_type": question.get("question_type"),
        "dimension": question.get("dimension"),
        "rubric_points": list(question.get("rubric_points") or []),
    }
    try:
        get_tracer().trace_node_event(
            _opening_trace_state(
                state,
                current_question=question,
                current_dimension=str(question.get("dimension") or ""),
            ),
            node="self_intro_question",
            payload=payload,
            logical_turn_idx=0,
        )
    except Exception as e:  # pragma: no cover
        log.warning("tracer.trace_node_event self_intro_question failed: %s", e)


def _trace_self_intro_parse_opening(
    state: InterviewState,
    *,
    profile: dict[str, Any],
    self_intro_vector_status: dict[str, Any],
) -> None:
    payload = {
        **trace_node_metadata("self_intro_parse"),
        "phase": "opening",
        "parse_status": profile.get("parse_status"),
        "emphasized_projects_count": len(profile.get("emphasized_projects") or []),
        "emphasized_skills_count": len(profile.get("emphasized_skills") or []),
        "profile_summary": _self_intro_profile_summary(profile),
        "anchor_cards_summary": _self_intro_anchor_cards_summary(profile),
        "self_intro_profile_snapshot": _self_intro_profile_snapshot(profile),
        "self_intro_anchor_cards": _self_intro_anchor_cards(profile),
        "self_intro_communication": _self_intro_communication(profile),
        "self_intro_downstream_usage": _self_intro_downstream_usage(),
        "profile_fields_present": _self_intro_profile_fields_present(profile),
        "self_intro_vector_status": trace_status_summary(
            self_intro_vector_status,
            presence_fields=("self_intro_revision_id",),
        ),
    }
    try:
        get_tracer().trace_node_event(
            _opening_trace_state(state),
            node="self_intro_parse",
            payload=payload,
            logical_turn_idx=0,
        )
    except Exception as e:  # pragma: no cover
        log.warning("tracer.trace_node_event self_intro_parse failed: %s", e)


def _self_intro_profile_summary(profile: dict[str, Any]) -> dict[str, object]:
    communication = profile.get("communication_signal")
    communication_signal = communication if isinstance(communication, dict) else {}
    structure = str(communication_signal.get("structure") or "").strip()
    notes = communication_signal.get("notes")
    return {
        "has_summary": bool(str(profile.get("summary") or "").strip()),
        "preferred_focus_count": len(profile.get("preferred_focus") or []),
        "clarification_targets_count": len(
            profile.get("clarification_targets") or [],
        ),
        "communication_signal_present": bool(communication_signal),
        "communication_structure": structure or "unknown",
        "communication_notes_count": len(notes if isinstance(notes, list) else []),
    }


def _self_intro_anchor_cards_summary(profile: dict[str, Any]) -> dict[str, int]:
    summary = {
        "total": 0,
        "project": 0,
        "responsibility": 0,
        "tech": 0,
        "difficulty": 0,
        "result": 0,
        "claim": 0,
        "other": 0,
    }
    cards = profile.get("anchor_cards") or []
    if not isinstance(cards, list):
        return summary
    for card in cards:
        if not isinstance(card, dict):
            continue
        summary["total"] += 1
        kind = str(card.get("kind") or "").strip().lower()
        if kind in (
            "project",
            "responsibility",
            "tech",
            "difficulty",
            "result",
            "claim",
        ):
            summary[kind] += 1
        else:
            summary["other"] += 1
    return summary


def _self_intro_profile_snapshot(profile: dict[str, Any]) -> dict[str, list[str]]:
    return {
        "emphasized_projects": _self_intro_text_list(
            profile.get("emphasized_projects"),
            limit=6,
        ),
        "emphasized_skills": _self_intro_text_list(
            profile.get("emphasized_skills"),
            limit=8,
        ),
        "preferred_focus": _self_intro_text_list(
            profile.get("preferred_focus"),
            limit=6,
        ),
        "clarification_targets": _self_intro_text_list(
            profile.get("clarification_targets"),
            limit=4,
        ),
    }


def _self_intro_anchor_cards(profile: dict[str, Any]) -> list[dict[str, Any]]:
    cards = profile.get("anchor_cards")
    if not isinstance(cards, list):
        return []
    safe_cards: list[dict[str, Any]] = []
    for card in cards:
        if not isinstance(card, dict):
            continue
        safe_cards.append(
            {
                "kind": _self_intro_text(card.get("kind")),
                "title": _self_intro_text(card.get("title"), limit=120),
                "tech_keywords": _self_intro_text_list(
                    card.get("tech_keywords"),
                    limit=8,
                ),
                "source": _self_intro_text(card.get("source")),
            }
        )
    return safe_cards[:8]


def _self_intro_communication(profile: dict[str, Any]) -> dict[str, Any]:
    communication = profile.get("communication_signal")
    communication_signal = communication if isinstance(communication, dict) else {}
    notes = communication_signal.get("notes")
    return {
        "structure": _self_intro_text(
            communication_signal.get("structure"),
        )
        or "unknown",
        "notes_count": len(notes if isinstance(notes, list) else []),
        "clarification_targets_count": len(
            profile.get("clarification_targets") or [],
        ),
    }


def _self_intro_downstream_usage() -> dict[str, Any]:
    return {
        "anchor_scheduler_signals": [
            "emphasized_projects",
            "emphasized_skills",
            "preferred_focus",
        ],
        "skill_focus_signal": "emphasized_skills",
        "rag_source": "anchor_cards",
        "next_nodes": ["director_sample", "ask_question"],
    }


def _self_intro_text_list(value: Any, *, limit: int = 8) -> list[str]:
    if not isinstance(value, list):
        return []
    items: list[str] = []
    for item in value:
        text = _self_intro_text(item, limit=120)
        if text:
            items.append(text)
    return items[:limit]


def _self_intro_text(value: Any, *, limit: int = 80) -> str:
    text = " ".join(str(value or "").split())
    if not text:
        return ""
    return text[:limit]


def _self_intro_profile_fields_present(profile: dict[str, Any]) -> list[str]:
    ordered_fields = [
        "summary",
        "emphasized_projects",
        "emphasized_skills",
        "preferred_focus",
        "clarification_targets",
        "communication_signal",
        "anchor_cards",
    ]
    return [field for field in ordered_fields if bool(profile.get(field))]


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
