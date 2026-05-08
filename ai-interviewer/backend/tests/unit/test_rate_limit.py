from __future__ import annotations

import pytest

from app.core.rate_limit import (
    MemoryRateLimiter,
    RateLimitExceededError,
    RedisRateLimiter,
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


def test_memory_rate_limiter_preserves_existing_retry_after_contract() -> None:
    limiter = MemoryRateLimiter()

    limiter.check("llm:test:127.0.0.1", limit=2, window_seconds=60, now=100.0)
    limiter.check("llm:test:127.0.0.1", limit=2, window_seconds=60, now=101.0)

    with pytest.raises(RateLimitExceededError) as exc_info:
        limiter.check("llm:test:127.0.0.1", limit=2, window_seconds=60, now=102.0)

    assert exc_info.value.retry_after_seconds == 58


class _FakeRedis:
    def __init__(self) -> None:
        self.windows: dict[str, list[tuple[float, str]]] = {}
        self.expires: dict[str, int] = {}
        self.deleted: list[str] = []

    def eval(self, _script: str, numkeys: int, *args):
        assert numkeys == 1
        key = str(args[0])
        now = float(args[1])
        window_seconds = float(args[2])
        limit = int(args[3])
        member = str(args[4])
        ttl_seconds = int(args[5])

        cutoff = now - window_seconds
        bucket = [
            (score, item)
            for score, item in self.windows.get(key, [])
            if score > cutoff
        ]
        self.windows[key] = bucket
        if len(bucket) >= limit:
            oldest = min(score for score, _item in bucket)
            return [0, oldest]

        bucket.append((now, member))
        self.expires[key] = ttl_seconds
        return [1, 0]

    def delete(self, *keys: str) -> None:
        for key in keys:
            self.deleted.append(key)
            self.windows.pop(key, None)

    def scan_iter(self, match: str):
        prefix = match.rstrip("*")
        for key in sorted(self.windows):
            if key.startswith(prefix):
                yield key


def test_redis_rate_limiter_uses_shared_sliding_window() -> None:
    fake = _FakeRedis()
    limiter = RedisRateLimiter(redis_client=fake, redis_prefix="test-rate")

    limiter.check("resume_parse:127.0.0.1", limit=2, window_seconds=60, now=100.0)
    limiter.check("resume_parse:127.0.0.1", limit=2, window_seconds=60, now=101.0)

    with pytest.raises(RateLimitExceededError) as exc_info:
        limiter.check("resume_parse:127.0.0.1", limit=2, window_seconds=60, now=102.0)

    assert exc_info.value.retry_after_seconds == 58
    assert "test-rate:resume_parse:127.0.0.1" in fake.expires


def test_redis_rate_limiter_expires_old_hits() -> None:
    fake = _FakeRedis()
    limiter = RedisRateLimiter(redis_client=fake, redis_prefix="test-rate")

    limiter.check("jd_parse:127.0.0.1", limit=1, window_seconds=10, now=100.0)
    limiter.check("jd_parse:127.0.0.1", limit=1, window_seconds=10, now=111.0)

    assert len(fake.windows["test-rate:jd_parse:127.0.0.1"]) == 1


def test_redis_rate_limiter_clear_removes_prefixed_keys() -> None:
    fake = _FakeRedis()
    limiter = RedisRateLimiter(redis_client=fake, redis_prefix="test-rate")
    limiter.check("a", limit=5, window_seconds=60, now=1.0)
    limiter.check("b", limit=5, window_seconds=60, now=1.0)

    limiter.clear()

    assert fake.deleted == ["test-rate:a", "test-rate:b"]
