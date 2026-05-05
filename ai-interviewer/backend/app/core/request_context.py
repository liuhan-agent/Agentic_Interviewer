"""Request-scoped trace context helpers."""
from __future__ import annotations

import time
import uuid
from collections.abc import Awaitable, Callable
from contextvars import ContextVar

from fastapi import FastAPI, Request, Response

from app.core.logging import bind_log_context, reset_log_context
from app.core.metrics import record_http_request

_TRACEPARENT_TRACE_ID: ContextVar[str | None] = ContextVar(
    "traceparent_trace_id",
    default=None,
)
_REQUEST_ID: ContextVar[str | None] = ContextVar("request_id", default=None)


def parse_traceparent(value: str | None) -> str | None:
    """Extract the W3C trace id from a traceparent header."""
    if not value:
        return None
    parts = value.strip().split("-")
    if len(parts) != 4:
        return None
    version, trace_id, span_id, flags = parts
    if (
        len(version) == 2
        and len(trace_id) == 32
        and len(span_id) == 16
        and len(flags) == 2
        and all(c in "0123456789abcdefABCDEF" for c in trace_id + span_id + flags)
        and trace_id != "0" * 32
    ):
        return trace_id.lower()
    return None


def current_traceparent_trace_id() -> str | None:
    return _TRACEPARENT_TRACE_ID.get()


def current_request_id() -> str | None:
    return _REQUEST_ID.get()


def install_request_context_middleware(app: FastAPI) -> None:
    """Install request logging context and HTTP metrics middleware."""

    @app.middleware("http")
    async def _request_context_middleware(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        traceparent_trace_id = parse_traceparent(request.headers.get("traceparent"))
        request_id = request.headers.get("x-request-id") or f"req-{uuid.uuid4().hex[:12]}"
        trace_token = _TRACEPARENT_TRACE_ID.set(traceparent_trace_id)
        request_token = _REQUEST_ID.set(request_id)
        log_token = bind_log_context(
            request_id=request_id,
            traceparent_trace_id=traceparent_trace_id,
        )
        start = time.monotonic()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            response.headers.setdefault("X-Request-ID", request_id)
            return response
        finally:
            duration = time.monotonic() - start
            record_http_request(
                request.method,
                request.url.path,
                status,
                duration,
            )
            reset_log_context(log_token)
            _REQUEST_ID.reset(request_token)
            _TRACEPARENT_TRACE_ID.reset(trace_token)
