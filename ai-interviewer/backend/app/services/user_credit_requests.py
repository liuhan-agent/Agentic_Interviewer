"""Lightweight user credit request workflow."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy import func

from app.models.auth import User
from app.models.user_credit_request import (
    CREDIT_REQUEST_STATUS_APPROVED,
    CREDIT_REQUEST_STATUS_PENDING,
    CREDIT_REQUEST_STATUS_REJECTED,
    UserCreditRequest,
)
from app.services.user_credits import admin_adjust_credit

MAX_CREDIT_REQUEST_AMOUNT = 20

CreditRequestDecision = Literal["approved", "rejected"]


class PendingCreditRequestExistsError(Exception):
    """Raised when a user already has a pending credit request."""


class CreditRequestNotFoundError(Exception):
    """Raised when an admin targets a missing credit request."""


class CreditRequestAlreadyDecidedError(Exception):
    """Raised when a request is approved/rejected more than once."""


def create_credit_request(
    db: Any,
    *,
    user_id: int,
    requested_amount: int,
    reason: str,
) -> dict[str, Any]:
    existing = (
        db.query(UserCreditRequest)
        .filter(UserCreditRequest.user_id == int(user_id))
        .filter(UserCreditRequest.status == CREDIT_REQUEST_STATUS_PENDING)
        .one_or_none()
    )
    if existing is not None:
        raise PendingCreditRequestExistsError("pending credit request already exists")

    now = datetime.now(UTC)
    row = UserCreditRequest(
        user_id=int(user_id),
        requested_amount=int(requested_amount),
        reason=reason.strip(),
        status=CREDIT_REQUEST_STATUS_PENDING,
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    db.flush()
    return credit_request_payload(row)


def list_account_credit_requests(
    db: Any,
    *,
    user_id: int,
    limit: int = 20,
    offset: int = 0,
) -> dict[str, Any]:
    capped_limit = max(1, min(int(limit or 20), 100))
    safe_offset = max(0, min(int(offset or 0), 10_000))
    query = db.query(UserCreditRequest).filter(UserCreditRequest.user_id == int(user_id))
    total_count = int(query.with_entities(func.count(UserCreditRequest.id)).scalar() or 0)
    rows = (
        query.order_by(UserCreditRequest.created_at.desc(), UserCreditRequest.id.desc())
        .offset(safe_offset)
        .limit(capped_limit)
        .all()
    )
    return {
        "count": len(rows),
        "total_count": total_count,
        "limit": capped_limit,
        "offset": safe_offset,
        "requests": [credit_request_payload(row) for row in rows],
    }


def list_admin_credit_requests(
    db: Any,
    *,
    status_filter: str | None = None,
    email: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    capped_limit = max(1, min(int(limit or 100), 100))
    safe_offset = max(0, min(int(offset or 0), 10_000))
    query = db.query(UserCreditRequest, User.email).join(
        User,
        User.id == UserCreditRequest.user_id,
    )
    if status_filter:
        query = query.filter(UserCreditRequest.status == status_filter)
    needle = (email or "").strip().lower()
    if needle:
        query = query.filter(User.email.ilike(f"%{needle}%"))
    total_count = int(query.with_entities(func.count(UserCreditRequest.id)).scalar() or 0)
    rows = (
        query.order_by(UserCreditRequest.created_at.desc(), UserCreditRequest.id.desc())
        .offset(safe_offset)
        .limit(capped_limit)
        .all()
    )
    return {
        "count": len(rows),
        "total_count": total_count,
        "limit": capped_limit,
        "offset": safe_offset,
        "requests": [
            credit_request_payload(row, user_email=user_email)
            for row, user_email in rows
        ],
    }


def decide_credit_request(
    db: Any,
    *,
    request_id: int,
    status: CreditRequestDecision,
    reason: str,
    actor_user_id: int | None,
    settings: Any | None = None,
) -> dict[str, Any]:
    row = db.get(UserCreditRequest, int(request_id))
    if row is None:
        raise CreditRequestNotFoundError(f"credit request {int(request_id)} not found")
    if row.status != CREDIT_REQUEST_STATUS_PENDING:
        raise CreditRequestAlreadyDecidedError("credit request already decided")

    clean_reason = reason.strip()
    now = datetime.now(UTC)
    ledger_entry: dict[str, Any] | None = None
    if status == CREDIT_REQUEST_STATUS_APPROVED:
        ledger_entry = admin_adjust_credit(
            db,
            user_id=int(row.user_id),
            amount_delta=int(row.requested_amount),
            reason=f"credit request approved: {clean_reason}"[:300],
            admin_note=f"credit_request:{int(row.id)}; user_reason:{row.reason}"[:500],
            settings=settings,
        )
        row.credit_ledger_entry_id = int(ledger_entry["id"])
    elif status != CREDIT_REQUEST_STATUS_REJECTED:
        raise ValueError(f"unsupported credit request decision: {status}")

    row.status = status
    row.decision_reason = clean_reason
    row.decided_by_user_id = int(actor_user_id) if actor_user_id is not None else None
    row.decided_at = now
    row.updated_at = now
    db.flush()

    user = db.get(User, int(row.user_id))
    return {
        "request": credit_request_payload(
            row,
            user_email=user.email if user is not None else None,
        ),
        "credit_ledger_entry": ledger_entry,
    }


def credit_request_payload(
    row: UserCreditRequest,
    *,
    user_email: str | None = None,
) -> dict[str, Any]:
    payload = {
        "id": int(row.id),
        "user_id": int(row.user_id),
        "requested_amount": int(row.requested_amount),
        "reason": row.reason,
        "status": row.status,
        "decision_reason": row.decision_reason,
        "decided_by_user_id": row.decided_by_user_id,
        "decided_at": _iso_datetime(row.decided_at),
        "credit_ledger_entry_id": row.credit_ledger_entry_id,
        "created_at": _iso_datetime(row.created_at),
        "updated_at": _iso_datetime(row.updated_at),
    }
    if user_email is not None:
        payload["user_email"] = user_email
    return payload


def _iso_datetime(value: Any) -> str | None:
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()
