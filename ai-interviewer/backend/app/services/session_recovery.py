from __future__ import annotations

from typing import Any

from app.core.logging import get_logger

log = get_logger(__name__)


def _graph_config_for_session(session_id: str) -> dict[str, Any]:
    return {
        "configurable": {"thread_id": session_id},
        "recursion_limit": 120,
    }


class RecoveryService:
    """Checkpoint probes used by durable HITL recovery paths."""

    def __init__(self, workflow: Any) -> None:
        self._workflow = workflow

    def checkpoint_exists(self, session_id: str) -> bool:
        """Return whether LangGraph has non-empty checkpoint state."""
        try:
            state = self._workflow.get_state(_graph_config_for_session(session_id))
            values = getattr(state, "values", None) if state is not None else None
            return bool(values)
        except Exception as e:
            log.debug("checkpoint probe for %s: %s", session_id, e)
            return False

    def checkpoint_values(self, session_id: str) -> dict[str, Any] | None:
        """Return checkpoint values without requiring a specific next node."""
        try:
            state = self._workflow.get_state(_graph_config_for_session(session_id))
        except Exception as e:
            log.warning("checkpoint values lookup failed for %s: %s", session_id, e)
            return None

        values = getattr(state, "values", None) or {}
        return values if isinstance(values, dict) and values else None

    def checkpoint_retryable_question_failure(self, session_id: str) -> bool:
        """Return whether question generation can be safely retried."""
        try:
            state = self._workflow.get_state(_graph_config_for_session(session_id))
        except Exception as e:
            log.warning("checkpoint retry probe failed for %s: %s", session_id, e)
            return False

        values = getattr(state, "values", None) or {}
        next_nodes = tuple(getattr(state, "next", ()) or ())
        if "ask_question" not in next_nodes:
            return False
        if values.get("final_report"):
            return False
        current_question = values.get("current_question")
        current_answer = str(values.get("current_answer") or "").strip()
        if not current_question:
            return True
        return bool(current_answer)

    def checkpoint_retryable_evaluator_failure(self, session_id: str) -> bool:
        """Return whether answer evaluation can be safely retried."""
        try:
            state = self._workflow.get_state(_graph_config_for_session(session_id))
        except Exception as e:
            log.warning(
                "checkpoint evaluator retry probe failed for %s: %s",
                session_id,
                e,
            )
            return False

        values = getattr(state, "values", None) or {}
        next_nodes = tuple(getattr(state, "next", ()) or ())
        if "evaluator" not in next_nodes:
            return False
        if values.get("final_report"):
            return False
        if not isinstance(values.get("current_question"), dict):
            return False
        return bool(str(values.get("current_answer") or "").strip())

    def checkpoint_waiting_question(self, session_id: str) -> dict[str, Any] | None:
        """Return checkpoint values when the graph waits for an answer."""
        try:
            state = self._workflow.get_state(_graph_config_for_session(session_id))
        except Exception as e:
            log.warning("checkpoint waiting probe failed for %s: %s", session_id, e)
            return None

        values = getattr(state, "values", None) or {}
        next_nodes = tuple(getattr(state, "next", ()) or ())
        question = values.get("current_question")
        if "wait_answer" not in next_nodes:
            return None
        if not isinstance(question, dict) or not question:
            return None
        if values.get("final_report"):
            return None
        return values
