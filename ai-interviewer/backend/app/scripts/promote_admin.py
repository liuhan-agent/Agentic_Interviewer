"""Promote an existing product account to the admin role."""
from __future__ import annotations

import argparse
from typing import Any

from app.models.auth import USER_ROLE_ADMIN, User
from app.models.base import get_session
from app.services.user_auth import normalize_email


class PromoteAdminError(RuntimeError):
    """Raised when an operator asks to promote a user that does not exist."""


def promote_admin_by_email(email: str) -> dict[str, Any]:
    normalized = normalize_email(email)
    if not normalized:
        raise PromoteAdminError("email is required")
    with get_session() as db:
        user = db.query(User).filter(User.email == normalized).one_or_none()
        if user is None:
            raise PromoteAdminError(
                f"user {normalized!r} does not exist; register the account first",
            )
        changed = user.role != USER_ROLE_ADMIN
        if changed:
            user.role = USER_ROLE_ADMIN
        return {
            "id": int(user.id),
            "email": user.email,
            "role": user.role,
            "changed": changed,
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Promote an existing Agentic Interviewer account to admin.",
    )
    parser.add_argument("--email", required=True, help="Existing user email to promote")
    args = parser.parse_args(argv)
    try:
        result = promote_admin_by_email(args.email)
    except PromoteAdminError as e:
        parser.error(str(e))
    status = "promoted" if result["changed"] else "already-admin"
    print(f"{status}: {result['email']} role={result['role']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
