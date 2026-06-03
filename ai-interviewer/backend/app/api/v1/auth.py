"""Account authentication API for product ownership control-plane."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.api_errors import api_error_detail
from app.core.metrics import record_rate_limit_block
from app.core.rate_limit import RateLimitExceededError, check_rate_limit
from app.core.settings import get_settings
from app.models.auth import USER_ROLE_USER, User
from app.models.base import get_session as get_db_session
from app.services.user_auth import (
    AUTH_COOKIE_NAME,
    MAX_PASSWORD_LENGTH,
    MIN_PASSWORD_LENGTH,
    create_auth_session,
    get_optional_user,
    hash_password,
    is_valid_email,
    normalize_email,
    revoke_auth_token,
    verify_password,
)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


class AuthRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=MAX_PASSWORD_LENGTH)

    @field_validator("email")
    @classmethod
    def _email_shape(cls, value: str) -> str:
        normalized = normalize_email(value)
        if not is_valid_email(normalized):
            raise ValueError("invalid email")
        return normalized


def _user_payload(user: User) -> dict[str, Any]:
    return {
        "id": user.id,
        "email": user.email,
        "role": user.role,
        "status": user.status,
        "email_verified": user.email_verified_at is not None,
    }


def _auth_payload(user: User | None) -> dict[str, Any]:
    return {
        "authenticated": user is not None,
        "user": _user_payload(user) if user is not None else None,
    }


def _rate_limit_client_key(request: Request, endpoint: str) -> str:
    host = request.client.host if request.client else "unknown"
    return f"{endpoint}:{host}"


def _enforce_auth_rate_limit(
    request: Request,
    *,
    endpoint: str,
    limit: int,
) -> None:
    if int(limit) <= 0:
        return
    settings = get_settings()
    try:
        check_rate_limit(
            _rate_limit_client_key(request, endpoint),
            limit=int(limit),
            window_seconds=float(getattr(settings, "rate_limit_window_seconds", 60)),
        )
    except RateLimitExceededError as e:
        record_rate_limit_block(endpoint)
        raise HTTPException(
            status_code=429,
            detail=api_error_detail(
                "rate_limit_exceeded",
                "请求过于频繁，请稍后再试。",
                "retry_later",
            ),
            headers={"Retry-After": str(e.retry_after_seconds)},
        ) from e


def _set_auth_cookie(response: Response, token: str, expires_at: datetime) -> None:
    settings = get_settings()
    now = datetime.now(UTC)
    max_age = max(0, int((expires_at - now).total_seconds()))
    response.set_cookie(
        key=AUTH_COOKIE_NAME,
        value=token,
        max_age=max_age,
        expires=max_age,
        path="/",
        httponly=True,
        secure=getattr(settings, "app_env", "dev") == "prod",
        samesite="lax",
    )


def _clear_auth_cookie(response: Response) -> None:
    settings = get_settings()
    response.delete_cookie(
        key=AUTH_COOKIE_NAME,
        path="/",
        httponly=True,
        secure=getattr(settings, "app_env", "dev") == "prod",
        samesite="lax",
    )


def _current_user_from_request(request: Request) -> User | None:
    return get_optional_user(request)


@router.post("/register")
def register(body: AuthRequest, request: Request, response: Response) -> dict[str, Any]:
    settings = get_settings()
    if getattr(settings, "auth_registration_mode", "open") != "open":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=api_error_detail(
                "registration_closed",
                "当前暂未开放新账号注册。",
                "login_existing_account",
            ),
        )
    _enforce_auth_rate_limit(
        request,
        endpoint="auth_register",
        limit=int(getattr(settings, "auth_register_rate_limit_per_minute", 20)),
    )
    with get_db_session() as db:
        existing = db.query(User).filter(User.email == body.email).one_or_none()
        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="email already registered",
            )
        user = User(
            email=body.email,
            password_hash=hash_password(body.password),
            role=USER_ROLE_USER,
            status="active",
        )
        db.add(user)
        db.flush()
        token, expires_at = create_auth_session(
            db,
            user_id=int(user.id),
            ttl_days=getattr(settings, "auth_session_ttl_days", 14),
        )
        _set_auth_cookie(response, token, expires_at)
        return _auth_payload(user)


@router.post("/login")
def login(body: AuthRequest, request: Request, response: Response) -> dict[str, Any]:
    settings = get_settings()
    _enforce_auth_rate_limit(
        request,
        endpoint="auth_login",
        limit=int(getattr(settings, "auth_login_rate_limit_per_minute", 60)),
    )
    with get_db_session() as db:
        user = db.query(User).filter(User.email == body.email).one_or_none()
        if (
            user is None
            or user.status != "active"
            or not verify_password(body.password, user.password_hash)
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="invalid email or password",
            )
        token, expires_at = create_auth_session(
            db,
            user_id=int(user.id),
            ttl_days=getattr(settings, "auth_session_ttl_days", 14),
        )
        _set_auth_cookie(response, token, expires_at)
        return _auth_payload(user)


@router.post("/logout")
def logout(request: Request, response: Response) -> dict[str, Any]:
    token = request.cookies.get(AUTH_COOKIE_NAME)
    if token:
        with get_db_session() as db:
            revoke_auth_token(db, token)
    _clear_auth_cookie(response)
    return {"ok": True}


@router.get("/me")
def me(request: Request) -> dict[str, Any]:
    return _auth_payload(_current_user_from_request(request))
