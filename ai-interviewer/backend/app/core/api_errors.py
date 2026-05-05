"""Small helpers for stable user-facing API error details."""
from __future__ import annotations

from typing import Any


def api_error_detail(
    code: str,
    message: str,
    action: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    detail: dict[str, Any] = {"code": code, "message": message}
    if action:
        detail["action"] = action
    detail.update(extra)
    return detail
