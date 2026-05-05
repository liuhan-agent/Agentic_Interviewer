"""Build user-facing interview replay payloads from persisted traces."""
from __future__ import annotations

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
    evaluation = trace.evaluation or {}
    return {
        "turn_idx": trace.turn_idx,
        "dimension": trace.dimension,
        "question": trace.question,
        "answer": trace.answer,
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


def build_session_replay(db: Any, session_id: str) -> dict[str, Any]:
    row = db.get(InterviewSession, session_id)
    if row is None:
        raise ReplayNotFound(session_id)
    if row.status != "completed":
        raise ReplayNotReady(session_id)

    report = row.final_report or {}
    traces = (
        db.query(GenerationTrace)
        .filter(GenerationTrace.session_id == session_id)
        .filter(GenerationTrace.node == "evaluator")
        .order_by(GenerationTrace.turn_idx.asc(), GenerationTrace.id.asc())
        .all()
    )
    timeline = [_turn_payload(trace) for trace in traces]
    if not timeline:
        timeline = _timeline_from_report(report)
    return {
        "session_id": session_id,
        "status": row.status,
        "summary": {
            "job_title": row.job_title,
            "job_level": row.job_level,
            "overall_score": report.get("overall_score"),
            "overall_verdict": report.get("overall_verdict"),
            "total_turns": report.get("total_turns", len(timeline)),
            "priority_weaknesses": _priority_weaknesses(report),
        },
        "timeline": timeline,
        "training_plan": report.get("training_plan") or {},
    }
