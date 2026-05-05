"""Tests for the ``since`` filter on ``trainset_builder.export_jsonl``.

Legacy callers that do not pass ``since`` must continue to see the
full dump (backwards compatibility); new callers that *do* pass a
cutoff must see only rows whose ``created_at`` is at or after that
cutoff.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import delete

from app.data.trainset_builder import export_jsonl
from app.models import GenerationTrace, get_session, init_db


@pytest.fixture(autouse=True)
def _fresh_db():
    init_db()
    with get_session() as sess:
        sess.execute(delete(GenerationTrace))
    yield
    with get_session() as sess:
        sess.execute(delete(GenerationTrace))


def _add_trace(session_id: str, created_at: datetime) -> None:
    with get_session() as sess:
        sess.add(
            GenerationTrace(
                trace_id=f"trace-{session_id}",
                session_id=session_id,
                turn_idx=0,
                node="evaluator",
                dimension="technical_depth",
                action_id="plan_adaptive",
                policy_id="thompson_v1::template::senior:technical_depth",
                context_key="senior:technical_depth",
                score=7.5,
                passed=True,
                immediate_reward=0.8,
                created_at=created_at,
            )
        )


def test_export_without_since_dumps_everything(tmp_path: Path):
    now = datetime.now(UTC)
    _add_trace("sess-old", now - timedelta(days=10))
    _add_trace("sess-mid", now - timedelta(days=2))
    _add_trace("sess-new", now)

    out = tmp_path / "full.jsonl"
    n = export_jsonl(out)
    assert n == 3

    lines = out.read_text(encoding="utf-8").splitlines()
    ids = {json.loads(ln)["session_id"] for ln in lines}
    assert ids == {"sess-old", "sess-mid", "sess-new"}


def test_export_with_since_filters_rows(tmp_path: Path):
    now = datetime.now(UTC)
    _add_trace("sess-old", now - timedelta(days=10))
    _add_trace("sess-mid", now - timedelta(days=2))
    _add_trace("sess-new", now)

    out = tmp_path / "recent.jsonl"
    n = export_jsonl(out, since=now - timedelta(days=3))
    assert n == 2

    lines = out.read_text(encoding="utf-8").splitlines()
    ids = {json.loads(ln)["session_id"] for ln in lines}
    assert ids == {"sess-mid", "sess-new"}


def test_export_with_future_since_returns_zero_rows(tmp_path: Path):
    """``since`` in the future is a valid no-op: the output file is
    created (empty) and the return value is 0."""
    now = datetime.now(UTC)
    _add_trace("sess-any", now - timedelta(days=1))

    out = tmp_path / "future.jsonl"
    n = export_jsonl(out, since=now + timedelta(days=7))
    assert n == 0
    assert out.exists()
    assert out.read_text(encoding="utf-8") == ""
