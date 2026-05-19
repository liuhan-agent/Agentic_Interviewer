"""Per-session capability tokens for anonymous interview sessions."""
from __future__ import annotations

import hashlib
import hmac
import secrets


def new_session_token() -> str:
    """Return a high-entropy browser-held session secret."""
    return secrets.token_urlsafe(32)


def new_recovery_token() -> str:
    """Return a high-entropy browser-held recovery secret."""
    return new_session_token()


def hash_session_token(token: str) -> str:
    """Hash a token before storing it on handles or in the database."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def hash_recovery_token(token: str) -> str:
    """Hash a recovery token before storing it in the database."""
    return hash_session_token(token)


def verify_session_token(token: str | None, token_hash: str | None) -> bool:
    """Constant-time token verification against a stored hash."""
    if not token or not token_hash:
        return False
    return hmac.compare_digest(hash_session_token(token), token_hash)


def verify_recovery_token(token: str | None, token_hash: str | None) -> bool:
    """Constant-time recovery token verification against a stored hash."""
    return verify_session_token(token, token_hash)
