"""Small auth primitives for account ownership control-plane APIs."""
from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
from fastapi import HTTPException, Request, status

from app.models.auth import USER_ROLE_ADMIN, AuthSession, User
from app.models.base import get_session as get_db_session

AUTH_COOKIE_NAME = "ai_interviewer_auth"
MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 128


def normalize_email(value: str) -> str:
    return value.strip().lower()


def is_valid_email(value: str) -> bool:
    if len(value) > 320 or "@" not in value:
        return False
    local, _, domain = value.partition("@")
    return bool(local and domain and "." in domain)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode(
        "utf-8"
    )


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except Exception:
        return False


def new_auth_token() -> str:
    return secrets.token_urlsafe(32)


def hash_auth_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_auth_session(
    db: Any,
    *,
    user_id: int,
    ttl_days: int,
    now: datetime | None = None,
) -> tuple[str, datetime]:
    issued_at = now or datetime.now(UTC)
    expires_at = issued_at + timedelta(days=max(1, int(ttl_days or 1)))
    token = new_auth_token()
    db.add(
        AuthSession(
            user_id=user_id,
            token_hash=hash_auth_token(token),
            expires_at=expires_at,
            created_at=issued_at,
            last_seen_at=issued_at,
        )
    )
    return token, expires_at


def load_active_user_for_token(
    db: Any,
    token: str | None,
    *,
    now: datetime | None = None,
) -> User | None:
    if not token:
        return None
    checked_at = now or datetime.now(UTC)
    row = (
        db.query(AuthSession)
        .filter(AuthSession.token_hash == hash_auth_token(token))
        .one_or_none()
    )
    if row is None or row.revoked_at is not None:
        return None
    expires_at = row.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    if expires_at <= checked_at:
        return None
    user = db.get(User, row.user_id)
    if user is None or user.status != "active":
        return None
    row.last_seen_at = checked_at
    return user


def revoke_auth_token(db: Any, token: str | None, *, now: datetime | None = None) -> bool:
    if not token:
        return False
    row = (
        db.query(AuthSession)
        .filter(AuthSession.token_hash == hash_auth_token(token))
        .one_or_none()
    )
    if row is None or row.revoked_at is not None:
        return False
    row.revoked_at = now or datetime.now(UTC)
    return True


def get_optional_user(request: Request) -> User | None:
    token = request.cookies.get(AUTH_COOKIE_NAME)
    if not token:
        return None
    with get_db_session() as db:
        return load_active_user_for_token(db, token)


def require_user(request: Request) -> User:
    user = get_optional_user(request)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="login required",
        )
    return user


def require_admin_user(request: Request) -> User:
    user = require_user(request)
    if user.role != USER_ROLE_ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="admin role required",
        )
    return user
