"""Structured logging context tests."""
from __future__ import annotations

import io
import json
import logging
from types import SimpleNamespace

from app.core import logging as logging_mod


def test_json_logging_includes_bound_context(monkeypatch) -> None:
    monkeypatch.setattr(
        logging_mod,
        "get_settings",
        lambda: SimpleNamespace(log_level="INFO", log_format="json", app_env="prod"),
    )
    stream = io.StringIO()
    logging_mod._reset_logging_for_tests(stream=stream)
    logging_mod.configure_logging()

    token = logging_mod.bind_log_context(
        request_id="req-1",
        traceparent_trace_id="0" * 32,
        trace_id="trace-1",
        session_id="sess-1",
    )
    try:
        logging_mod.get_logger("test.logger").info("hello %s", "world")
    finally:
        logging_mod.reset_log_context(token)

    payload = json.loads(stream.getvalue().strip())
    assert payload["level"] == "INFO"
    assert payload["logger"] == "test.logger"
    assert payload["message"] == "hello world"
    assert payload["request_id"] == "req-1"
    assert payload["traceparent_trace_id"] == "0" * 32
    assert payload["trace_id"] == "trace-1"
    assert payload["session_id"] == "sess-1"


def test_auto_logging_uses_json_in_prod(monkeypatch) -> None:
    monkeypatch.setattr(
        logging_mod,
        "get_settings",
        lambda: SimpleNamespace(log_level="INFO", log_format="auto", app_env="prod"),
    )
    stream = io.StringIO()
    logging_mod._reset_logging_for_tests(stream=stream)
    logging_mod.configure_logging()

    logging.getLogger("test.auto").info("prod-json")

    payload = json.loads(stream.getvalue().strip())
    assert payload["message"] == "prod-json"
