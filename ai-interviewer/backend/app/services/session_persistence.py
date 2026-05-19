from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.core.logging import get_logger
from app.models.interview_session import InterviewSession

log = get_logger(__name__)


class SessionPersistence:
    """Persistence boundary for durable HITL session rows."""

    def __init__(self, *, get_db_session_fn: Callable[[], Any]) -> None:
        self._get_db_session = get_db_session_fn

    def persist_interrupt(
        self,
        handle: Any,
        question: dict[str, Any],
        turn_idx: int,
    ) -> None:
        """Write the current interrupt state to the DB row."""
        try:
            with self._get_db_session() as db:
                row = db.get(InterviewSession, handle.session_id)
                if row is None:
                    row = InterviewSession(
                        session_id=handle.session_id,
                        trace_id=handle.trace_id,
                    )
                    db.add(row)
                row.status = "interrupted"
                if handle.session_token_hash and not row.session_token_hash:
                    row.session_token_hash = handle.session_token_hash
                if getattr(handle, "session_token_expires_at", None):
                    row.session_token_expires_at = handle.session_token_expires_at
                if getattr(handle, "recovery_token_hash", None) and not row.recovery_token_hash:
                    row.recovery_token_hash = handle.recovery_token_hash
                if getattr(handle, "recovery_token_expires_at", None):
                    row.recovery_token_expires_at = handle.recovery_token_expires_at
                if handle.llm_config_meta:
                    row.llm_config_meta = handle.llm_config_meta
                if getattr(handle, "setup_snapshot", None) is not None:
                    row.setup_snapshot = handle.setup_snapshot
                row.enable_video_analysis = bool(
                    getattr(handle, "enable_video_analysis", False)
                )
                row.current_question = question
                row.turn_idx = turn_idx
                row.asked_turn = handle.asked_turn
        except Exception as e:
            log.warning("persist_interrupt failed for %s: %s", handle.session_id, e)

    def persist_completed(
        self,
        handle: Any,
        final_state: dict[str, Any] | None,
    ) -> None:
        try:
            with self._get_db_session() as db:
                row = db.get(InterviewSession, handle.session_id)
                if row is None:
                    row = InterviewSession(
                        session_id=handle.session_id,
                        trace_id=handle.trace_id,
                    )
                    db.add(row)
                status = (final_state or {}).get("status", "completed")
                if handle.session_token_hash and not row.session_token_hash:
                    row.session_token_hash = handle.session_token_hash
                if getattr(handle, "session_token_expires_at", None):
                    row.session_token_expires_at = handle.session_token_expires_at
                if getattr(handle, "recovery_token_hash", None) and not row.recovery_token_hash:
                    row.recovery_token_hash = handle.recovery_token_hash
                if getattr(handle, "recovery_token_expires_at", None):
                    row.recovery_token_expires_at = handle.recovery_token_expires_at
                if handle.llm_config_meta:
                    row.llm_config_meta = handle.llm_config_meta
                if getattr(handle, "setup_snapshot", None) is not None:
                    row.setup_snapshot = handle.setup_snapshot
                row.enable_video_analysis = bool(
                    getattr(handle, "enable_video_analysis", False)
                )
                row.status = status if status != "running" else "completed"
                row.final_report = (final_state or {}).get("final_report")
                if status in {"error", "errored", "failed", "stale"}:
                    row.error = (final_state or {}).get("error") or handle.error
                    row.error_kind = (
                        (final_state or {}).get("error_kind") or handle.error_kind
                    )
                    row.retryable = bool((final_state or {}).get("retryable", False))
                else:
                    row.error = None
                    row.error_kind = None
                    row.retryable = False
                row.current_question = None
        except Exception as e:
            log.warning("persist_completed failed for %s: %s", handle.session_id, e)

    def load_session_for_retry(self, session_id: str) -> dict[str, Any] | None:
        """Load minimal session metadata needed to rebuild a handle."""
        try:
            with self._get_db_session() as db:
                row = db.get(InterviewSession, session_id)
                if row is None:
                    return None
                return {
                    "trace_id": row.trace_id,
                    "candidate_name": row.candidate_name,
                    "job_title": row.job_title,
                    "job_level": row.job_level,
                    "mode": row.mode,
                    "enable_video_analysis": bool(
                        getattr(row, "enable_video_analysis", False)
                    ),
                    "session_token_hash": row.session_token_hash,
                    "session_token_expires_at": row.session_token_expires_at,
                    "llm_config_meta": row.llm_config_meta,
                    "turn_idx": row.turn_idx,
                    "asked_turn": row.asked_turn,
                }
        except Exception as e:
            log.warning("load retry session %s failed: %s", session_id, e)
            return None

    def mark_retry_running(self, session_id: str) -> None:
        try:
            with self._get_db_session() as db:
                row = db.get(InterviewSession, session_id)
                if row is not None:
                    row.status = "running"
                    row.current_question = None
                    row.final_report = None
                    row.error = None
                    row.error_kind = None
                    row.retryable = False
        except Exception as e:
            log.warning("mark retry running failed for %s: %s", session_id, e)
