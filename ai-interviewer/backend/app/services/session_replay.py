"""Build user-facing interview replay payloads from persisted traces."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.models.generation_trace import GenerationTrace
from app.models.interview_session import InterviewSession

_SYSTEM_FALLBACK_MARKERS = (
    "evaluator llm unavailable",
    "evaluator llm failed",
    "conservative fallback",
    "评估模型暂时不可用",
    "保守兜底评价",
)


class ReplayNotFound(Exception):  # noqa: N818 - public API name used by router/tests.
    """Raised when the requested interview session does not exist."""


class ReplayNotReady(Exception):  # noqa: N818 - public API name used by router/tests.
    """Raised when a session is not ready for user-facing replay."""


def _iso_datetime(value: Any) -> str | None:
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    else:
        value = value.astimezone(UTC)
    return value.isoformat()


def _list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [
        str(item)
        for item in value
        if str(item or "").strip() and not _is_system_fallback_text(item)
    ]


def _user_text(value: Any) -> str:
    text = str(value or "").strip()
    return "" if _is_system_fallback_text(text) else text


def _int_or_none(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return int(value.strip())
        except ValueError:
            return None
    return None


def _same_nonempty_text(left: Any, right: Any) -> bool:
    left_text = str(left or "").strip()
    right_text = str(right or "").strip()
    return bool(left_text and right_text and left_text == right_text)


def _qa_turn_from_trace(trace: GenerationTrace) -> dict[str, Any]:
    snapshot = trace.state_snapshot if isinstance(trace.state_snapshot, dict) else {}
    history = snapshot.get("qa_history")
    if not isinstance(history, list):
        return {}

    turns = [item for item in history if isinstance(item, dict)]
    if not turns:
        return {}

    for item in reversed(turns):
        if _same_nonempty_text(
            item.get("question"),
            trace.question,
        ) or _same_nonempty_text(item.get("answer"), trace.answer):
            return item
    return turns[-1]


def _is_system_fallback_text(value: Any) -> bool:
    text = str(value or "").strip().lower()
    if not text:
        return False
    return any(marker in text for marker in _SYSTEM_FALLBACK_MARKERS)


def _priority_weaknesses(report: dict[str, Any]) -> list[str]:
    plan = report.get("training_plan") or {}
    out: list[str] = []
    for item in plan.get("priority_weaknesses") or []:
        if isinstance(item, dict):
            label = item.get("focus") or item.get("dimension")
        else:
            label = item
        text = str(label or "").strip()
        if text:
            out.append(text)
    return out


def _turn_payload(trace: GenerationTrace) -> dict[str, Any]:
    qa_turn = _qa_turn_from_trace(trace)
    qa_evaluation = (
        qa_turn.get("evaluation") if isinstance(qa_turn.get("evaluation"), dict) else {}
    )
    evaluation = trace.evaluation if isinstance(trace.evaluation, dict) else {}
    if not evaluation:
        evaluation = qa_evaluation
    formal_turn_idx = _int_or_none(qa_turn.get("turn_idx"))
    return {
        "turn_idx": formal_turn_idx if formal_turn_idx is not None else trace.turn_idx,
        "dimension": trace.dimension or qa_turn.get("dimension"),
        "question": trace.question or qa_turn.get("question"),
        "answer": trace.answer or qa_turn.get("answer"),
        "score": trace.score
        if trace.score is not None
        else evaluation.get("score"),
        "passed": trace.passed
        if trace.passed is not None
        else evaluation.get("passed"),
        "rationale": _user_text(evaluation.get("rationale")),
        "strengths": _list(evaluation.get("strengths")),
        "weaknesses": _list(evaluation.get("weaknesses")),
        "next_step": _user_text(evaluation.get("recommended_next")),
    }


def _timeline_from_report(report: dict[str, Any]) -> list[dict[str, Any]]:
    """Build a replay timeline from final-report evidence when traces are absent."""
    summaries = report.get("dimension_summaries") or {}
    if not isinstance(summaries, dict):
        return []

    timeline: list[dict[str, Any]] = []
    for dimension, summary in summaries.items():
        if not isinstance(summary, dict):
            continue
        evidence_items = summary.get("evidence") or []
        if not isinstance(evidence_items, list):
            continue
        for evidence in evidence_items:
            if not isinstance(evidence, dict):
                continue
            timeline.append(
                {
                    "turn_idx": evidence.get("turn_idx"),
                    "dimension": dimension,
                    "question": evidence.get("question"),
                    "answer": evidence.get("answer")
                    or evidence.get("answer_excerpt"),
                    "score": evidence.get("score"),
                    "passed": evidence.get("passed"),
                    "rationale": _user_text(evidence.get("rationale")),
                    "strengths": _list(evidence.get("strengths")),
                    "weaknesses": _list(evidence.get("weaknesses")),
                    "next_step": _user_text(
                        evidence.get("recommended_next")
                        or evidence.get("recommended_next_plan")
                    ),
                }
            )

    return sorted(
        timeline,
        key=lambda item: (
            item.get("turn_idx") is None,
            int(item.get("turn_idx") or 0),
        ),
    )


def _timeline_from_traces(
    db: Any,
    session_id: str,
    *,
    before_formal_turn_idx: int | None = None,
) -> list[dict[str, Any]]:
    traces = (
        db.query(GenerationTrace)
        .filter(GenerationTrace.session_id == session_id)
        .filter(GenerationTrace.node == "evaluator")
        .order_by(GenerationTrace.turn_idx.asc(), GenerationTrace.id.asc())
        .all()
    )
    by_turn_idx: dict[int, dict[str, Any]] = {}
    unindexed: list[dict[str, Any]] = []
    for trace in traces:
        payload = _turn_payload(trace)
        turn_idx = _int_or_none(payload.get("turn_idx"))
        if (
            before_formal_turn_idx is not None
            and turn_idx is not None
            and turn_idx >= before_formal_turn_idx
        ):
            continue
        if turn_idx is None:
            unindexed.append(payload)
            continue
        payload["turn_idx"] = turn_idx
        by_turn_idx[turn_idx] = payload
    return [by_turn_idx[idx] for idx in sorted(by_turn_idx)] + unindexed


def build_resume_history(
    db: Any,
    session_id: str,
    *,
    before_formal_turn_idx: int | None = None,
) -> list[dict[str, Any]]:
    """Return answered turns for an in-progress session resume payload.

    Replay is intentionally gated to completed sessions, but the active
    interview page still needs the already-evaluated turns when a user resumes
    an interrupted interview. The evaluator trace rows are the same durable
    source replay uses, just without the completed-session guard.
    """
    row = db.get(InterviewSession, session_id)
    if row is None:
        raise ReplayNotFound(session_id)
    return _timeline_from_traces(
        db,
        session_id,
        before_formal_turn_idx=before_formal_turn_idx,
    )


def build_session_replay(db: Any, session_id: str) -> dict[str, Any]:
    row = db.get(InterviewSession, session_id)
    if row is None:
        raise ReplayNotFound(session_id)
    if row.status != "completed":
        raise ReplayNotReady(session_id)

    report = row.final_report or {}
    timeline = _timeline_from_traces(db, session_id)
    if not timeline:
        timeline = _timeline_from_report(report)
    return {
        "session_id": session_id,
        "status": row.status,
        "created_at": _iso_datetime(row.created_at),
        "updated_at": _iso_datetime(row.updated_at),
        "summary": {
            "job_title": row.job_title,
            "job_level": row.job_level,
            "overall_score": report.get("overall_score"),
            "growth_signal": report.get("growth_signal"),
            "overall_verdict": report.get("overall_verdict"),
            "total_turns": report.get("total_turns", len(timeline)),
            "priority_weaknesses": _priority_weaknesses(report),
        },
        "timeline": timeline,
        "training_plan": report.get("training_plan") or {},
    }
