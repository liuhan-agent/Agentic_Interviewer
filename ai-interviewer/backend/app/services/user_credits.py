"""Credit ledger service for platform-hosted interview sessions."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import func

from app.core.settings import get_settings
from app.models.auth import User
from app.models.user_credit import UserCreditAccount, UserCreditLedger

FREE_GRANT_VERSION = "free_grant:v1"
CREDIT_UNIT = "interview"


class InsufficientCreditsError(Exception):
    """Raised when a debit would make the user's balance negative."""


class CreditUserNotFoundError(Exception):
    """Raised when an operation targets a missing user row."""


def _require_user(db: Any, user_id: int) -> User:
    user = db.get(User, int(user_id))
    if user is None:
        raise CreditUserNotFoundError(f"user {int(user_id)} not found")
    return user


def free_grant_amount(settings: Any | None = None) -> int:
    settings = settings or get_settings()
    return max(0, int(getattr(settings, "free_interview_credits", 10)))


def credit_policy_payload(settings: Any | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    return {
        "enforced": getattr(settings, "app_env", "dev") == "prod",
        "free_grant": free_grant_amount(settings),
        "interview_unit": CREDIT_UNIT,
        "requires_login_for_platform_hosted": True,
        "registration_mode": getattr(settings, "auth_registration_mode", "open"),
        "free_credits_require_email_verified": bool(
            getattr(settings, "free_credits_require_email_verified", False)
        ),
    }


def ensure_free_grant(db: Any, user_id: int, *, settings: Any | None = None) -> UserCreditAccount:
    settings = settings or get_settings()
    user = _require_user(db, int(user_id))
    account = db.get(UserCreditAccount, int(user_id))
    now = datetime.now(UTC)
    if account is None:
        account = UserCreditAccount(
            user_id=int(user_id),
            balance=0,
            created_at=now,
            updated_at=now,
        )
        db.add(account)
        db.flush()

    amount = free_grant_amount(settings)
    if (
        bool(getattr(settings, "free_credits_require_email_verified", False))
        and user.email_verified_at is None
    ):
        return account
    if amount <= 0 or account.free_grant_version == FREE_GRANT_VERSION:
        return account

    external_ref = f"{FREE_GRANT_VERSION}:user:{int(user_id)}"
    existing = (
        db.query(UserCreditLedger)
        .filter(UserCreditLedger.external_ref == external_ref)
        .one_or_none()
    )
    if existing is None:
        account.balance = int(account.balance or 0) + amount
        account.free_grant_version = FREE_GRANT_VERSION
        account.updated_at = now
        db.add(
            UserCreditLedger(
                user_id=int(user_id),
                delta=amount,
                kind="free_grant",
                external_ref=external_ref,
                session_id=None,
                reason="initial free interview credits",
                metadata_json={"grant_version": FREE_GRANT_VERSION},
                balance_after=int(account.balance),
                created_at=now,
            )
        )
        db.flush()
    else:
        account.free_grant_version = FREE_GRANT_VERSION
        account.balance = int(existing.balance_after)
        account.updated_at = now
        db.flush()
    return account


def account_credit_summary(
    db: Any,
    user_id: int,
    *,
    recent_limit: int = 20,
    settings: Any | None = None,
) -> dict[str, Any]:
    account = ensure_free_grant(db, int(user_id), settings=settings)
    free_total = int(
        db.query(func.coalesce(func.sum(UserCreditLedger.delta), 0))
        .filter(UserCreditLedger.user_id == int(user_id))
        .filter(UserCreditLedger.kind == "free_grant")
        .scalar()
        or 0
    )
    entries = (
        db.query(UserCreditLedger)
        .filter(UserCreditLedger.user_id == int(user_id))
        .order_by(UserCreditLedger.created_at.desc(), UserCreditLedger.id.desc())
        .limit(max(0, min(int(recent_limit), 100)))
        .all()
    )
    return {
        "balance": int(account.balance or 0),
        "free_grant_total": free_total,
        "unit": CREDIT_UNIT,
        "recent_entries": [ledger_entry_payload(entry) for entry in entries],
    }


def current_balance(db: Any, user_id: int, *, settings: Any | None = None) -> int:
    return int(ensure_free_grant(db, int(user_id), settings=settings).balance or 0)


def debit_session_start(
    db: Any,
    *,
    user_id: int,
    session_id: str,
    settings: Any | None = None,
) -> dict[str, Any]:
    account = ensure_free_grant(db, int(user_id), settings=settings)
    external_ref = f"session_start:{session_id}"
    existing = (
        db.query(UserCreditLedger)
        .filter(UserCreditLedger.external_ref == external_ref)
        .one_or_none()
    )
    if existing is not None:
        return ledger_entry_payload(existing)
    if int(account.balance or 0) <= 0:
        raise InsufficientCreditsError("platform interview credits exhausted")

    now = datetime.now(UTC)
    account.balance = int(account.balance or 0) - 1
    account.updated_at = now
    entry = UserCreditLedger(
        user_id=int(user_id),
        delta=-1,
        kind="session_debit",
        external_ref=external_ref,
        session_id=session_id,
        reason="platform-hosted interview session start",
        metadata_json=None,
        balance_after=int(account.balance),
        created_at=now,
    )
    db.add(entry)
    db.flush()
    return ledger_entry_payload(entry)


def refund_session_start(
    db: Any,
    *,
    user_id: int,
    session_id: str,
    reason: str,
    settings: Any | None = None,
) -> dict[str, Any] | None:
    account = ensure_free_grant(db, int(user_id), settings=settings)
    external_ref = f"session_refund:{session_id}"
    existing = (
        db.query(UserCreditLedger)
        .filter(UserCreditLedger.external_ref == external_ref)
        .one_or_none()
    )
    if existing is not None:
        return ledger_entry_payload(existing)
    debit = (
        db.query(UserCreditLedger)
        .filter(UserCreditLedger.external_ref == f"session_start:{session_id}")
        .one_or_none()
    )
    if debit is None:
        return None
    now = datetime.now(UTC)
    account.balance = int(account.balance or 0) + 1
    account.updated_at = now
    entry = UserCreditLedger(
        user_id=int(user_id),
        delta=1,
        kind="session_refund",
        external_ref=external_ref,
        session_id=session_id,
        reason=reason[:300] or "session start failed before response",
        metadata_json={"refunded_external_ref": debit.external_ref},
        balance_after=int(account.balance),
        created_at=now,
    )
    db.add(entry)
    db.flush()
    return ledger_entry_payload(entry)


def admin_adjust_credit(
    db: Any,
    *,
    user_id: int,
    amount_delta: int,
    reason: str,
    admin_note: str | None = None,
    settings: Any | None = None,
) -> dict[str, Any]:
    delta = int(amount_delta)
    if delta == 0:
        raise ValueError("amount_delta must not be zero")
    account = ensure_free_grant(db, int(user_id), settings=settings)
    next_balance = int(account.balance or 0) + delta
    if next_balance < 0:
        raise InsufficientCreditsError("credit adjustment would make balance negative")
    now = datetime.now(UTC)
    account.balance = next_balance
    account.updated_at = now
    entry = UserCreditLedger(
        user_id=int(user_id),
        delta=delta,
        kind="admin_adjustment",
        external_ref=f"admin_adjustment:{uuid4().hex}",
        session_id=None,
        reason=reason.strip()[:300],
        metadata_json=None,
        balance_after=next_balance,
        admin_note=admin_note.strip() if isinstance(admin_note, str) and admin_note.strip() else None,
        created_at=now,
    )
    db.add(entry)
    db.flush()
    return ledger_entry_payload(entry)


def list_user_credit_accounts(
    db: Any,
    *,
    email: str | None = None,
    limit: int = 100,
    offset: int = 0,
    settings: Any | None = None,
) -> dict[str, Any]:
    capped_limit = max(1, min(int(limit or 100), 100))
    safe_offset = max(0, min(int(offset or 0), 10_000))
    query = db.query(User)
    needle = (email or "").strip().lower()
    if needle:
        query = query.filter(User.email.ilike(f"%{needle}%"))
    total_count = int(query.with_entities(func.count()).scalar() or 0)
    users = query.order_by(User.created_at.desc()).offset(safe_offset).limit(capped_limit).all()
    items = []
    for user in users:
        account = ensure_free_grant(db, int(user.id), settings=settings)
        items.append(
            {
                "user_id": int(user.id),
                "email": user.email,
                "status": user.status,
                "role": user.role,
                "balance": int(account.balance or 0),
                "free_grant_version": account.free_grant_version,
                "created_at": _iso_datetime(user.created_at),
                "updated_at": _iso_datetime(account.updated_at),
            }
        )
    return {
        "count": len(items),
        "total_count": total_count,
        "limit": capped_limit,
        "offset": safe_offset,
        "users": items,
    }


def user_credit_ledger(
    db: Any,
    *,
    user_id: int,
    limit: int = 100,
    offset: int = 0,
    settings: Any | None = None,
) -> dict[str, Any]:
    ensure_free_grant(db, int(user_id), settings=settings)
    capped_limit = max(1, min(int(limit or 100), 100))
    safe_offset = max(0, min(int(offset or 0), 10_000))
    query = db.query(UserCreditLedger).filter(UserCreditLedger.user_id == int(user_id))
    total_count = int(query.with_entities(func.count()).scalar() or 0)
    rows = (
        query.order_by(UserCreditLedger.created_at.desc(), UserCreditLedger.id.desc())
        .offset(safe_offset)
        .limit(capped_limit)
        .all()
    )
    account = db.get(UserCreditAccount, int(user_id))
    return {
        "user_id": int(user_id),
        "balance": int(account.balance or 0) if account is not None else 0,
        "count": len(rows),
        "total_count": total_count,
        "limit": capped_limit,
        "offset": safe_offset,
        "entries": [ledger_entry_payload(row) for row in rows],
    }


def ledger_entry_payload(entry: UserCreditLedger) -> dict[str, Any]:
    return {
        "id": entry.id,
        "user_id": entry.user_id,
        "delta": entry.delta,
        "kind": entry.kind,
        "external_ref": entry.external_ref,
        "session_id": entry.session_id,
        "reason": entry.reason,
        "metadata": entry.metadata_json,
        "balance_after": entry.balance_after,
        "admin_note": entry.admin_note,
        "created_at": _iso_datetime(entry.created_at),
    }


def _iso_datetime(value: Any) -> str | None:
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()
