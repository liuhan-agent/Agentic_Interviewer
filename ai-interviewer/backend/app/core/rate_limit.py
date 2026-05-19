"""Sliding-window rate limiter for high-cost setup endpoints."""
from __future__ import annotations

import math
import threading
import time
import uuid
from collections import defaultdict, deque
from typing import Any, Protocol

from app.core.settings import get_settings


class RateLimitExceededError(Exception):
    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__("rate limit exceeded")
        self.retry_after_seconds = retry_after_seconds


class RateLimiter(Protocol):
    def check(
        self,
        key: str,
        *,
        limit: int,
        window_seconds: float,
        now: float | None = None,
    ) -> None:
        """Raise :class:`RateLimitExceededError` when the bucket is full."""

    def clear(self) -> None:
        """Clear stored buckets. Intended for tests and operator reset paths."""


class MemoryRateLimiter:
    """Process-local sliding-window limiter used for dev and tests."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def clear(self) -> None:
        with self._lock:
            self._hits.clear()

    def check(
        self,
        key: str,
        *,
        limit: int,
        window_seconds: float,
        now: float | None = None,
    ) -> None:
        if limit <= 0 or window_seconds <= 0:
            return
        current = time.monotonic() if now is None else now
        cutoff = current - window_seconds

        with self._lock:
            bucket = self._hits[key]
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            if len(bucket) >= limit:
                retry_after = max(1, math.ceil(bucket[0] + window_seconds - current))
                raise RateLimitExceededError(retry_after)
            bucket.append(current)


_RATE_LIMIT_LUA = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local window_seconds = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
local member = ARGV[4]
local ttl_seconds = tonumber(ARGV[5])
redis.call("ZREMRANGEBYSCORE", key, "-inf", now - window_seconds)
local count = redis.call("ZCARD", key)
if count >= limit then
  local oldest = redis.call("ZRANGE", key, 0, 0, "WITHSCORES")
  return {0, oldest[2] or now}
end
redis.call("ZADD", key, now, member)
redis.call("EXPIRE", key, ttl_seconds)
return {1, 0}
"""


class RedisRateLimiter:
    """Redis-backed sliding-window limiter shared across workers."""

    def __init__(
        self,
        *,
        redis_client: Any | None = None,
        redis_url: str | None = None,
        redis_prefix: str = "agentic_interviewer:rate_limit",
    ) -> None:
        self._redis_client = redis_client
        self._redis_url = redis_url
        self._redis_prefix = redis_prefix.rstrip(":")

    def _redis(self) -> Any:
        if self._redis_client is not None:
            return self._redis_client
        from redis import Redis

        url = self._redis_url or get_settings().redis_url
        self._redis_client = Redis.from_url(url, decode_responses=True)
        return self._redis_client

    def _key(self, key: str) -> str:
        return f"{self._redis_prefix}:{key}"

    def clear(self) -> None:
        redis_client = self._redis()
        keys = list(redis_client.scan_iter(match=f"{self._redis_prefix}:*"))
        if keys:
            redis_client.delete(*keys)

    def check(
        self,
        key: str,
        *,
        limit: int,
        window_seconds: float,
        now: float | None = None,
    ) -> None:
        if limit <= 0 or window_seconds <= 0:
            return
        current = time.monotonic() if now is None else now
        ttl_seconds = max(1, math.ceil(window_seconds))
        result = self._redis().eval(
            _RATE_LIMIT_LUA,
            1,
            self._key(key),
            current,
            window_seconds,
            int(limit),
            f"{current}:{uuid.uuid4().hex}",
            ttl_seconds,
        )
        allowed = int(result[0])
        if allowed:
            return
        oldest = float(result[1])
        retry_after = max(1, math.ceil(oldest + window_seconds - current))
        raise RateLimitExceededError(retry_after)


_memory_limiter = MemoryRateLimiter()
_limiter: RateLimiter | None = None
_limiter_lock = threading.Lock()


def _build_rate_limiter() -> RateLimiter:
    settings = get_settings()
    if settings.rate_limit_backend == "redis":
        return RedisRateLimiter(
            redis_url=settings.redis_url,
            redis_prefix=settings.rate_limit_redis_prefix,
        )
    return _memory_limiter


def get_rate_limiter() -> RateLimiter:
    global _limiter
    if _limiter is None:
        with _limiter_lock:
            if _limiter is None:
                _limiter = _build_rate_limiter()
    return _limiter


def clear_rate_limits() -> None:
    global _limiter
    with _limiter_lock:
        limiter = _limiter
        _limiter = None
    _memory_limiter.clear()
    if limiter is not None and limiter is not _memory_limiter:
        limiter.clear()


def check_rate_limit(
    key: str,
    *,
    limit: int,
    window_seconds: float,
    now: float | None = None,
) -> None:
    get_rate_limiter().check(
        key,
        limit=limit,
        window_seconds=window_seconds,
        now=now,
    )
