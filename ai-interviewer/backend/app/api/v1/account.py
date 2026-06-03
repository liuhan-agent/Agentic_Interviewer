"""Account-scoped APIs for user-owned interview records."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func

from app.core.settings import get_settings
from app.models.base import get_session as get_db_session
from app.models.interview_session import InterviewSession
from app.services.user_auth import require_user
from app.services.user_credit_requests import (
    MAX_CREDIT_REQUEST_AMOUNT,
    PendingCreditRequestExistsError,
    create_credit_request,
    list_account_credit_requests,
)
from app.services.user_credits import account_credit_summary, credit_policy_payload

router = APIRouter(prefix="/api/v1/account", tags=["account"])


class CreditRequestCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requested_amount: int = Field(ge=1, le=MAX_CREDIT_REQUEST_AMOUNT)
    reason: str = Field(min_length=1, max_length=500)


def _ensure_aware_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _iso_datetime(value: Any) -> str | None:
    if not isinstance(value, datetime):
        return None
    aware = _ensure_aware_utc(value)
    return aware.isoformat() if aware else None


def _compact_dimension_scores(scores: Any) -> dict[str, float]:
    if not isinstance(scores, dict):
        return {}
    out: dict[str, float] = {}
    for dimension, value in scores.items():
        if not isinstance(dimension, str) or not dimension:
            continue
        raw_score: Any
        if isinstance(value, dict):
            raw_score = value.get("score")
        else:
            raw_score = value
        if isinstance(raw_score, bool):
            continue
        if isinstance(raw_score, (int, float)):
            out[dimension] = float(raw_score)
    return out


def _session_item(row: InterviewSession) -> dict[str, Any]:
    report = row.final_report if isinstance(row.final_report, dict) else {}
    return {
        "session_id": row.session_id,
        "status": row.status,
        "created_at": _iso_datetime(row.created_at),
        "updated_at": _iso_datetime(row.updated_at),
        "job_title": row.job_title,
        "candidate_name": row.candidate_name,
        "job_level": row.job_level,
        "mode": row.mode,
        "turn_idx": row.turn_idx,
        "asked_turn": row.asked_turn,
        "has_report": bool(report),
        "overall_score": report.get("overall_score"),
        "growth_signal": report.get("growth_signal"),
        "overall_verdict": report.get("overall_verdict") or report.get("verdict"),
        "dimension_scores": _compact_dimension_scores(report.get("dimension_scores")),
        "owner_user_id": row.owner_user_id,
        "owner_claimed_at": _iso_datetime(row.owner_claimed_at),
    }


@router.get("/interview-sessions")
def list_account_interview_sessions(
    request: Request,
    limit: int = Query(default=100, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=10_000),
) -> dict[str, Any]:
    user = require_user(request)
    capped_limit = max(1, min(int(limit or 100), 100))
    safe_offset = max(0, min(int(offset or 0), 10_000))
    with get_db_session() as db:
        base_query = db.query(InterviewSession).filter(
            InterviewSession.owner_user_id == int(user.id)
        )
        total_count = int(base_query.with_entities(func.count()).scalar() or 0)
        rows = (
            base_query.order_by(InterviewSession.created_at.desc())
            .offset(safe_offset)
            .limit(capped_limit)
            .all()
        )
    return {
        "count": len(rows),
        "total_count": total_count,
        "limit": capped_limit,
        "offset": safe_offset,
        "sessions": [_session_item(row) for row in rows],
    }


@router.get("/credit-policy")
def credit_policy() -> dict[str, Any]:
    return credit_policy_payload(get_settings())


@router.get("/credits")
def account_credits(request: Request) -> dict[str, Any]:
    user = require_user(request)
    with get_db_session() as db:
        return account_credit_summary(db, int(user.id), settings=get_settings())


@router.get("/credit-requests")
def account_credit_requests(
    request: Request,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=10_000),
) -> dict[str, Any]:
    user = require_user(request)
    with get_db_session() as db:
        return list_account_credit_requests(
            db,
            user_id=int(user.id),
            limit=limit,
            offset=offset,
        )


@router.post("/credit-requests")
def create_account_credit_request(
    body: CreditRequestCreate,
    request: Request,
) -> dict[str, Any]:
    user = require_user(request)
    reason = body.reason.strip()
    if not reason:
        raise HTTPException(status_code=422, detail="reason must not be blank")
    with get_db_session() as db:
        try:
            created = create_credit_request(
                db,
                user_id=int(user.id),
                requested_amount=int(body.requested_amount),
                reason=reason,
            )
        except PendingCreditRequestExistsError as e:
            raise HTTPException(status_code=409, detail=str(e)) from e
        return {"request": created}
