from __future__ import annotations

import pytest

from app.core.rate_limit import (
    RateLimitExceededError,
    check_rate_limit,
    clear_rate_limits,
)


def test_check_rate_limit_blocks_after_window_quota() -> None:
    clear_rate_limits()

    check_rate_limit("llm:test:127.0.0.1", limit=2, window_seconds=60, now=100.0)
    check_rate_limit("llm:test:127.0.0.1", limit=2, window_seconds=60, now=101.0)

    with pytest.raises(RateLimitExceededError) as exc_info:
        check_rate_limit("llm:test:127.0.0.1", limit=2, window_seconds=60, now=102.0)

    assert exc_info.value.retry_after_seconds == 58


def test_check_rate_limit_expires_old_hits() -> None:
    clear_rate_limits()

    check_rate_limit("resume:parse:127.0.0.1", limit=1, window_seconds=10, now=100.0)
    check_rate_limit("resume:parse:127.0.0.1", limit=1, window_seconds=10, now=111.0)
