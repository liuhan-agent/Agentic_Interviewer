from __future__ import annotations

from typing import Any

from app.core.logging import get_logger

log = get_logger(__name__)


def terminal_error_payload(
    *,
    session_id: str,
    error: str | None,
    error_kind: str | None,
    retryable: bool = False,
) -> dict[str, Any]:
    payload = {
        "session_id": session_id,
        "status": "error",
        "question": None,
        "error": error,
        "error_kind": error_kind,
    }
    if retryable:
        payload["retryable"] = True
    return payload


def stale_session_error(
    session_id: str,
    *,
    status: str | None = None,
    retryable: bool = False,
) -> dict[str, Any]:
    label = status or "unknown"
    return terminal_error_payload(
        session_id=session_id,
        error=(
            f"这场面试当前状态为 {label}，"
            + (
                "可以点继续处理来恢复上一轮进度。"
                if retryable
                else "已经无法继续。请回到首页重新开始一场面试。"
            )
        ),
        error_kind=None,
        retryable=retryable,
    )


def terminal_payload_from_persisted_session(
    session_id: str,
    *,
    retryable: bool = False,
) -> dict[str, Any] | None:
    try:
        from app.models.base import get_session as get_db_session
        from app.models.interview_session import InterviewSession

        with get_db_session() as db:
            row = db.get(InterviewSession, session_id)
            if row is None:
                return None
            status = row.status
            final_report = row.final_report
            persisted_error = getattr(row, "error", None)
            persisted_error_kind = getattr(row, "error_kind", None)
            persisted_retryable = bool(getattr(row, "retryable", False))
            enable_video_analysis = bool(
                getattr(row, "enable_video_analysis", False)
            )
    except Exception as e:
        log.warning("load persisted session %s failed: %s", session_id, e)
        return None

    if status == "completed":
        return {
            "session_id": session_id,
            "status": "completed",
            "question": None,
            "final_report": final_report,
            "enable_video_analysis": enable_video_analysis,
        }
    if status == "cancelled":
        return {
            "session_id": session_id,
            "status": "cancelled",
            "question": None,
            "enable_video_analysis": enable_video_analysis,
        }
    if status in {"error", "errored", "failed", "stale", "interrupted", "running"}:
        effective_retryable = retryable or persisted_retryable
        if persisted_error:
            payload = terminal_error_payload(
                session_id=session_id,
                error=persisted_error,
                error_kind=persisted_error_kind,
                retryable=effective_retryable,
            )
            payload["enable_video_analysis"] = enable_video_analysis
            return payload
        payload = stale_session_error(
            session_id,
            status=status,
            retryable=effective_retryable,
        )
        payload["enable_video_analysis"] = enable_video_analysis
        return payload
    return None
