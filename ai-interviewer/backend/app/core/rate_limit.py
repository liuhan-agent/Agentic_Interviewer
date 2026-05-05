"""Small in-process sliding-window rate limiter.

This protects high-cost setup endpoints (resume / jd parse, llm test)
without adding infrastructure dependencies. It is intentionally
process-local: each uvicorn worker / pod keeps its own counter dict.

Deployment caveat (see also ``backend/.env.example`` rate-limit
section): running with ``--workers N`` or N replicas behind a load
balancer multiplies the effective ceiling by N. If you do that, do
**one** of:

* Divide the limits in Settings by the worker count, or
* Add an upstream limiter (nginx ``limit_req`` / ALB rate-based rule)
  enforcing the canonical ceiling, or
* Drop in a Redis-backed sliding window that exposes the same
  ``check_rate_limit`` / :class:`RateLimitExceededError` contract.

The LLM-backed endpoints (resume / jd parse) are the dollar-amount
risk if you skip this; the auth-protected admin surface is a
separate concern handled by ``require_admin_token``.
"""
from __future__ import annotations

import math
import threading
import time
from collections import defaultdict, deque


class RateLimitExceededError(Exception):
    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__("rate limit exceeded")
        self.retry_after_seconds = retry_after_seconds


_lock = threading.Lock()
_hits: dict[str, deque[float]] = defaultdict(deque)


def clear_rate_limits() -> None:
    with _lock:
        _hits.clear()


def check_rate_limit(
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

    with _lock:
        bucket = _hits[key]
        while bucket and bucket[0] <= cutoff:
            bucket.popleft()
        if len(bucket) >= limit:
            retry_after = max(1, math.ceil(bucket[0] + window_seconds - current))
            raise RateLimitExceededError(retry_after)
        bucket.append(current)
