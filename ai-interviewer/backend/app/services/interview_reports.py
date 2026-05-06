from __future__ import annotations

from typing import Any

from app.core.logging import get_logger

log = get_logger(__name__)


def attach_trace_health(payload: dict[str, Any], session_id: str) -> dict[str, Any]:
    """Attach report trace coverage without letting observability break reports."""
    try:
        from app.services.trace_health import compute_session_trace_health

        payload["trace_health"] = compute_session_trace_health(session_id)
    except Exception as e:  # pragma: no cover - defensive
        log.warning("attach_trace_health failed for %s: %s", session_id, e)
        payload["trace_health"] = "missing"
    return payload


def report_payload_from_persisted_session(
    session_id: str,
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
    except Exception as e:
        log.warning("load persisted report %s failed: %s", session_id, e)
        return None

    if status == "completed":
        return attach_trace_health(
            {
                "session_id": session_id,
                "final_report": final_report,
                "error": None,
            },
            session_id,
        )
    if status == "cancelled":
        return attach_trace_health(
            {
                "session_id": session_id,
                "final_report": final_report,
                "error": "session cancelled",
                "error_kind": None,
            },
            session_id,
        )
    if status in {"error", "errored", "failed", "stale"}:
        return attach_trace_health(
            {
                "session_id": session_id,
                "final_report": final_report,
                "error": persisted_error
                or (
                    f"这场面试当前状态为 {status}，没有可用报告。"
                    "请重新开始一场面试。"
                ),
                "error_kind": persisted_error_kind,
            },
            session_id,
        )
    return None
