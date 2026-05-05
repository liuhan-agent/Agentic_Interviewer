"""Tests for ``trace_health`` enrichment on the report API.

The candidate-facing ``GET /sessions/{id}/report`` payload now ships
the same ``trace_health`` signal that the admin Trace Explorer
shows, so the **Quality Center** card on the report page can warn
the user when the interview did not run all the way through. The
tests below pin three behaviours:

1. A persisted, completed session reports ``trace_health="complete"``
   when the underlying nodes are present.
2. A persisted, cancelled session reports ``trace_health="partial"``
   even when the same node coverage is present (the status-aware
   downgrade introduced by PR1).
3. An in-memory (still-running -> done) session also gets the
   enrichment so the engineer view of the same session does not
   diverge.

We use the same fake-session pattern as ``test_tracer_run_id`` to
avoid touching a real DB.
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Any

import pytest

from app.api.v1 import interview as interview_mod


class _FakeInterviewSession:
    def __init__(self, *, session_id: str, status: str) -> None:
        self.session_id = session_id
        self.status = status
        self.final_report = {"overall_score": 7.4, "overall_verdict": "hire"}
        self.error = None
        self.error_kind = None


class _FakeQuery:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def filter(self, *_args: Any, **_kwargs: Any) -> "_FakeQuery":
        return self

    def group_by(self, *_args: Any) -> "_FakeQuery":
        return self

    def all(self) -> list[Any]:
        return list(self._rows)


class _FakeSession:
    def __init__(
        self,
        *,
        session_row: _FakeInterviewSession | None,
        node_rows: list[tuple[str, int]],
    ) -> None:
        self._session_row = session_row
        self._node_rows = node_rows

    def get(self, _model: Any, _key: Any) -> Any:
        return self._session_row

    def query(self, *_args: Any) -> _FakeQuery:
        return _FakeQuery(self._node_rows)


@pytest.fixture
def patch_db(monkeypatch: pytest.MonkeyPatch):
    """Factory: install a fake DB with the requested rows and return
    the helpers that produced them, so each test can express the
    scenario it cares about."""

    def _install(
        *,
        session_status: str | None,
        node_counts: dict[str, int],
    ) -> None:
        session_row = (
            None
            if session_status is None
            else _FakeInterviewSession(session_id="sess-1", status=session_status)
        )
        node_rows = [(node, count) for node, count in node_counts.items()]

        @contextmanager
        def _fake_app_models_get_session():
            yield _FakeSession(session_row=session_row, node_rows=node_rows)

        monkeypatch.setattr(
            "app.models.base.get_session", _fake_app_models_get_session
        )
        monkeypatch.setattr("app.models.get_session", _fake_app_models_get_session)

    return _install


# ---------------------------------------------------------------------------
# _report_payload_from_persisted_session enrichment
# ---------------------------------------------------------------------------


def test_completed_session_reports_complete(patch_db: Any) -> None:
    patch_db(
        session_status="completed",
        node_counts={"evaluator": 1, "reward_update": 1, "final_report": 1},
    )

    payload = interview_mod._report_payload_from_persisted_session("sess-1")

    assert payload is not None
    assert payload["session_id"] == "sess-1"
    assert payload["trace_health"] == "complete"


def test_cancelled_session_downgrades_to_partial(patch_db: Any) -> None:
    patch_db(
        session_status="cancelled",
        node_counts={"evaluator": 1, "reward_update": 1},
    )

    payload = interview_mod._report_payload_from_persisted_session("sess-1")

    assert payload is not None
    assert payload["trace_health"] == "partial"
    assert payload["error"] == "session cancelled"


def test_session_with_no_traces_is_missing(patch_db: Any) -> None:
    patch_db(session_status="completed", node_counts={})

    payload = interview_mod._report_payload_from_persisted_session("sess-1")

    assert payload is not None
    assert payload["trace_health"] == "missing"


def test_db_failure_falls_back_to_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """An admin DB outage must not 500 the report API; trace_health
    falls back to ``missing`` instead."""

    @contextmanager
    def _broken_get_session():
        raise RuntimeError("simulated outage")
        yield  # pragma: no cover

    # The persisted-session helper still needs to succeed (the row
    # itself loads fine), but the trace lookup it calls in turn must
    # tolerate the broken session manager.
    class _OkSession:
        def get(self, _model: Any, _key: Any) -> Any:
            return _FakeInterviewSession(session_id="sess-1", status="completed")

    @contextmanager
    def _ok_get_session():
        yield _OkSession()

    monkeypatch.setattr("app.models.base.get_session", _ok_get_session)
    monkeypatch.setattr("app.models.get_session", _broken_get_session)

    payload = interview_mod._report_payload_from_persisted_session("sess-1")

    assert payload is not None
    assert payload["trace_health"] == "missing"


def test_unknown_session_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """If the InterviewSession row is missing the helper returns None
    so the API falls through to its 404 path; trace_health does not
    apply to a non-existent session."""

    class _EmptySession:
        def get(self, _model: Any, _key: Any) -> Any:
            return None

    @contextmanager
    def _empty():
        yield _EmptySession()

    monkeypatch.setattr("app.models.base.get_session", _empty)

    payload = interview_mod._report_payload_from_persisted_session("ghost")

    assert payload is None
