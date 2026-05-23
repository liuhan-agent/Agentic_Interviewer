"""Build user-facing interview replay payloads from persisted traces."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.engine.workflow.followup_reason import sanitize_replay_followup_reason
from app.engine.workflow.replay_basis import (
    build_replay_context_basis,
    sanitize_replay_question_basis,
)
from app.models.generation_trace import GenerationTrace
from app.models.interview_session import InterviewSession

_SYSTEM_FALLBACK_MARKERS = (
    "evaluator llm unavailable",
    "evaluator llm failed",
    "conservative fallback",
    "评估模型暂时不可用",
    "保守兜底评价",
)


_INTERNAL_NEXT_DECISIONS = {"refine", "advance", "skip"}
_INTERNAL_NEXT_PLANS = {"simple", "adaptive", "deep_probe"}
_REFINE_NEXT_STEP_COPY = {
    "simple": "继续补充本题的基础信息和关键细节。",
    "adaptive": "围绕本题薄弱点，补充更具体的过程、证据和结果。",
    "deep_probe": "进一步深挖本题中的关键决策、指标、取舍或边界情况。",
}


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


def _next_step_text(recommended_next: Any, recommended_next_plan: Any = None) -> str:
    next_text = str(recommended_next or "").strip()
    decision = next_text.lower()
    plan_text = str(recommended_next_plan or "").strip()
    plan = plan_text.lower()

    if decision == "refine":
        return _REFINE_NEXT_STEP_COPY.get(
            plan,
            "围绕本题薄弱点继续补充细节。",
        )
    if decision in _INTERNAL_NEXT_DECISIONS:
        return ""
    if decision in _INTERNAL_NEXT_PLANS:
        return ""
    if next_text:
        return _user_text(next_text)
    if plan in _INTERNAL_NEXT_PLANS:
        return ""
    return _user_text(plan_text)


def _resume_anchor_display_fields(turn: dict[str, Any]) -> dict[str, str]:
    anchor = turn.get("resume_anchor") if isinstance(turn.get("resume_anchor"), dict) else {}
    anchor_key = str(
        anchor.get("anchor_key") or turn.get("resume_anchor_key") or ""
    ).strip()
    anchor_label = str(
        anchor.get("label")
        or anchor.get("project_name")
        or turn.get("resume_anchor_label")
        or ""
    ).strip()
    project_id = str(
        anchor.get("project_id") or turn.get("resume_project_id") or ""
    ).strip()
    out: dict[str, str] = {}
    if anchor_key:
        out["resume_anchor_key"] = anchor_key
    if anchor_label:
        out["resume_anchor_label"] = anchor_label
    if project_id:
        out["resume_project_id"] = project_id
    return out


def _anchor_followup_display_fields(turn: dict[str, Any]) -> dict[str, dict[str, int]]:
    artifacts = (
        turn.get("selection_artifacts")
        if isinstance(turn.get("selection_artifacts"), dict)
        else {}
    )
    scheduler = (
        artifacts.get("anchor_scheduler")
        if isinstance(artifacts.get("anchor_scheduler"), dict)
        else {}
    )
    attempt = _int_or_none(scheduler.get("anchor_attempt"))
    max_attempts = _int_or_none(scheduler.get("max_anchor_attempts"))
    if attempt is None or max_attempts is None:
        return {}
    if attempt < 1 or max_attempts < 2:
        return {}
    return {
        "anchor_followup": {
            "attempt": min(attempt, max_attempts),
            "max_attempts": max_attempts,
        }
    }


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


def _priority_items(report: dict[str, Any]) -> list[dict[str, Any]]:
    plan = report.get("training_plan") or {}
    out: list[dict[str, Any]] = []
    for item in plan.get("priority_weaknesses") or []:
        dimension: str | None = None
        category = "weakness"
        if isinstance(item, dict):
            focus = _user_text(item.get("focus"))
            raw_dimension = str(item.get("dimension") or "").strip()
            dimension = raw_dimension or None
            if str(item.get("category") or "").strip() == "coverage_limited":
                category = "coverage_limited"
        else:
            focus = _user_text(item)
        if not focus:
            continue

        label = "补充证据" if category == "coverage_limited" else "薄弱点"
        display_text = focus
        if category == "coverage_limited" and dimension:
            display_text = f"{dimension}：补充具体例子、关键指标和取舍说明"
        out.append(
            {
                "category": category,
                "label": label,
                "dimension": dimension,
                "focus": focus,
                "display_text": display_text,
            }
        )
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
    payload = {
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
        "next_step": _next_step_text(
            evaluation.get("recommended_next"),
            evaluation.get("recommended_next_plan"),
        ),
    }
    payload.update(_resume_anchor_display_fields(qa_turn))
    payload.update(_anchor_followup_display_fields(qa_turn))
    followup_reason = sanitize_replay_followup_reason(
        evaluation.get("followup_reason")
    ) or sanitize_replay_followup_reason(qa_evaluation.get("followup_reason"))
    if followup_reason is not None:
        payload["followup_reason"] = followup_reason
    question_basis = sanitize_replay_question_basis(qa_turn.get("question_basis"))
    if question_basis is not None:
        payload["question_basis"] = question_basis
    return payload


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
            payload = {
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
                "next_step": _next_step_text(
                    evidence.get("recommended_next"),
                    evidence.get("recommended_next_plan"),
                ),
            }
            payload.update(_resume_anchor_display_fields(evidence))
            followup_reason = sanitize_replay_followup_reason(
                evidence.get("followup_reason")
            )
            if followup_reason is not None:
                payload["followup_reason"] = followup_reason
            question_basis = sanitize_replay_question_basis(
                evidence.get("question_basis")
            )
            if question_basis is not None:
                payload["question_basis"] = question_basis
            timeline.append(payload)

    return _annotate_anchor_followups(
        sorted(
            timeline,
            key=lambda item: (
                item.get("turn_idx") is None,
                int(item.get("turn_idx") or 0),
            ),
        )
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
    return _annotate_anchor_followups(
        [by_turn_idx[idx] for idx in sorted(by_turn_idx)] + unindexed
    )


def _annotate_anchor_followups(timeline: list[dict[str, Any]]) -> list[dict[str, Any]]:
    totals: dict[str, int] = {}
    for turn in timeline:
        anchor_key = str(turn.get("resume_anchor_key") or "").strip()
        if anchor_key:
            totals[anchor_key] = totals.get(anchor_key, 0) + 1

    seen: dict[str, int] = {}
    for turn in timeline:
        anchor_key = str(turn.get("resume_anchor_key") or "").strip()
        if not anchor_key:
            continue
        seen[anchor_key] = seen.get(anchor_key, 0) + 1
        if turn.get("anchor_followup"):
            continue
        total = totals.get(anchor_key, 0)
        if total < 2 or seen[anchor_key] < 2:
            continue
        turn["anchor_followup"] = {
            "attempt": seen[anchor_key],
            "max_attempts": total,
        }
    return timeline


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
    context_basis = build_replay_context_basis(
        report=report,
        setup_snapshot=row.setup_snapshot,
    )
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
            "priority_items": _priority_items(report),
        },
        "context_basis": context_basis,
        "timeline": timeline,
        "training_plan": report.get("training_plan") or {},
    }
