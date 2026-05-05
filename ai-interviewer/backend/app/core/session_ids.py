"""Shared validation rules for externally visible session identifiers."""
from __future__ import annotations

import re

SESSION_ID_MAX_LENGTH = 64
SESSION_ID_PATTERN = r"^[A-Za-z0-9._:-]{1,64}$"
_SESSION_ID_RE = re.compile(SESSION_ID_PATTERN)


def is_valid_session_id(value: str | None) -> bool:
    if not isinstance(value, str):
        return False
    return bool(_SESSION_ID_RE.fullmatch(value))
