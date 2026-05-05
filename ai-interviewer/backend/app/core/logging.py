"""Logging helpers with request/session context injection."""
from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar, Token
from datetime import UTC, datetime
from typing import TextIO

from .settings import get_settings

_CONFIGURED = False
_TEST_STREAM: TextIO | None = None
_LOG_CONTEXT: ContextVar[dict[str, str] | None] = ContextVar(
    "log_context",
    default=None,
)
_CONTEXT_FIELDS = (
    "request_id",
    "traceparent_trace_id",
    "trace_id",
    "session_id",
)


def bind_log_context(**fields: object) -> Token[dict[str, str] | None]:
    """Bind structured fields to every log record in this context."""
    current = dict(_LOG_CONTEXT.get() or {})
    for key, value in fields.items():
        if key not in _CONTEXT_FIELDS or value is None:
            continue
        current[key] = str(value)
    return _LOG_CONTEXT.set(current)


def reset_log_context(token: Token[dict[str, str] | None]) -> None:
    """Restore the previous logging context."""
    _LOG_CONTEXT.reset(token)


def current_log_context() -> dict[str, str]:
    """Return a copy of the current structured logging context."""
    return dict(_LOG_CONTEXT.get() or {})


class _ContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        ctx = _LOG_CONTEXT.get() or {}
        for field in _CONTEXT_FIELDS:
            setattr(record, field, ctx.get(field, "-"))
        return True


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for field in _CONTEXT_FIELDS:
            value = getattr(record, field, "-")
            if value != "-":
                payload[field] = value
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging() -> None:
    """Install a root handler once, honouring ``LOG_LEVEL``."""
    global _CONFIGURED
    if _CONFIGURED:
        return
    settings = get_settings()
    level = getattr(logging, getattr(settings, "log_level", "INFO").upper(), logging.INFO)
    log_format = getattr(settings, "log_format", "auto")
    if log_format == "auto":
        log_format = "json" if getattr(settings, "app_env", "dev") == "prod" else "console"

    handler = logging.StreamHandler(_TEST_STREAM or sys.stdout)
    handler.addFilter(_ContextFilter())
    if log_format == "json":
        handler.setFormatter(_JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s | %(levelname)-7s | %(name)s | "
                "request=%(request_id)s traceparent=%(traceparent_trace_id)s "
                "trace=%(trace_id)s session=%(session_id)s | %(message)s",
                datefmt="%H:%M:%S",
            )
        )

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)
    _CONFIGURED = True


def _reset_logging_for_tests(*, stream: TextIO | None = None) -> None:
    """Reset root logging state for unit tests."""
    global _CONFIGURED, _TEST_STREAM
    logging.getLogger().handlers.clear()
    _CONFIGURED = False
    _TEST_STREAM = stream
    _LOG_CONTEXT.set({})


def get_logger(name: str) -> logging.Logger:
    configure_logging()
    return logging.getLogger(name)
