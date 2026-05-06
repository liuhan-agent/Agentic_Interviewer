from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Callable

from app.models.outcome_record import OutcomeRecord

FEEDBACK_OUTCOME_MAP: dict[str, str] = {
    "got_offer": "hired",
    "no_offer": "rejected",
    "still_preparing": "withdrew",
    "withdrew": "ghosted",
}


@dataclass(frozen=True)
class FeedbackSaveResult:
    canonical_outcome: str
    helpful_norm: float | None


def normalize_helpful_score(helpful_score: int | None) -> float | None:
    if helpful_score is None:
        return None
    return (helpful_score - 1) / 4.0


def save_interview_feedback(
    *,
    session_id: str,
    outcome: str,
    helpful_score: int | None,
    notes: str | None,
    get_db_session_fn: Callable,
) -> FeedbackSaveResult:
    canonical_outcome = FEEDBACK_OUTCOME_MAP[outcome]
    helpful_norm = normalize_helpful_score(helpful_score)
    now = datetime.now(UTC)

    with get_db_session_fn() as db:
        existing = db.get(OutcomeRecord, session_id)
        if existing is not None:
            existing.outcome = canonical_outcome
            existing.source = "user_feedback"
            existing.helpful_score = helpful_norm
            existing.notes = notes
            existing.collected_at = now
        else:
            db.add(
                OutcomeRecord(
                    session_id=session_id,
                    outcome=canonical_outcome,
                    source="user_feedback",
                    helpful_score=helpful_norm,
                    notes=notes,
                    collected_at=now,
                )
            )

    return FeedbackSaveResult(
        canonical_outcome=canonical_outcome,
        helpful_norm=helpful_norm,
    )
