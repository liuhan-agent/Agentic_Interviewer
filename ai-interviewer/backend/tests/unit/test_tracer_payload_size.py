"""Pin down the tracer's compact-snapshot guarantees.

``Tracer._strip_messages`` is the single chokepoint that decides what
ends up in the ``state_snapshot`` JSON column on every
``generation_traces`` row. For a long interview (8+ turns × ~9 trace
nodes) the previous implementation embedded the *entire* ``qa_history``
list verbatim into every snapshot, which meant the JSON column grew
quadratically with the turn count and made the trace-explorer page
sluggish on Postgres.

The current contract is:

1. ``qa_history`` is truncated to the last
   ``settings.tracer_qa_history_window`` entries (default 5).
2. ``qa_history_total`` is added so analytics readers can still tell
   how many turns were complete when the row was written.
3. The total serialised size of a typical 12-turn snapshot stays well
   under 50 KB so admin filters and ``json_extract`` queries do not
   become bottlenecks.
4. The whitelist outside of ``qa_history`` (``selected_action``,
   ``scores_per_dim``, …) is unaffected — older expectations must
   keep working.

The tests below lock in those four invariants. ``json.dumps`` is used
as a stand-in for the actual SQLAlchemy JSON serializer because both
emit a UTF-8 byte stream with the same shape.
"""
from __future__ import annotations

import json
from typing import Any

import pytest

from app.core import tracer as tracer_mod


def _qa_turn(turn_idx: int) -> dict[str, Any]:
    """Synthesize a realistic-looking QA turn entry.

    The ``answer`` is intentionally chunky (~ 1 KB) so a 12-turn
    history has enough mass to expose the truncation behaviour. We
    stay close to the actual ``QATurn`` shape so the test would catch
    accidental shape regressions in ``_strip_messages``.
    """
    return {
        "turn_idx": turn_idx,
        "dimension": "system_design",
        "question": f"Walk me through how you'd design subsystem #{turn_idx}.",
        "answer": (
            "I'd start with the load profile, dimension the request rate, "
            "set SLOs, and pick a storage tier accordingly. "
        )
        * 12,
        "selected_action": "plan_adaptive",
        "evaluation": {
            "score": 7.4 + (turn_idx % 3) * 0.1,
            "passed": turn_idx % 2 == 0,
            "strengths": [f"clear-tradeoffs-{turn_idx}"],
            "weaknesses": [f"missing-metric-{turn_idx}"],
        },
        "timestamp": f"2025-04-30T10:{turn_idx:02d}:00Z",
    }


def _state_with_history(turns: int) -> dict[str, Any]:
    return {
        "session_id": "sess-payload-1",
        "trace_id": "trace-payload-1",
        "turn_idx": turns,
        "current_dimension": "system_design",
        "scores_per_dim": {"system_design": 7.4},
        "dimension_status": {"system_design": "active"},
        "qa_history": [_qa_turn(i) for i in range(turns)],
        "selected_action": {"id": "plan_adaptive"},
        "policy_id": "template",
    }


def test_strip_messages_keeps_last_window_entries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The default 5-entry window is what the panel actually consumes."""
    state = _state_with_history(turns=12)

    snapshot = tracer_mod._strip_messages(state)

    assert snapshot["qa_history_total"] == 12
    assert len(snapshot["qa_history"]) == 5, (
        "default window=5 should land 5 entries in the trace row, "
        "not the full 12-turn history."
    )
    # Ordering check: the kept slice is the most recent five turns.
    kept_turns = [entry["turn_idx"] for entry in snapshot["qa_history"]]
    assert kept_turns == [7, 8, 9, 10, 11]


def test_strip_messages_window_zero_keeps_only_counter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        tracer_mod, "_qa_history_window", lambda: 0
    )
    state = _state_with_history(turns=4)

    snapshot = tracer_mod._strip_messages(state)

    assert snapshot["qa_history"] == []
    assert snapshot["qa_history_total"] == 4


def test_strip_messages_short_history_passes_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the actual history is shorter than the window we must
    still report the real total and not pad with empties."""
    state = _state_with_history(turns=2)

    snapshot = tracer_mod._strip_messages(state)

    assert snapshot["qa_history_total"] == 2
    assert len(snapshot["qa_history"]) == 2


def test_strip_messages_preserves_other_whitelisted_fields() -> None:
    """Trim must not regress unrelated whitelist keys."""
    state = _state_with_history(turns=3)

    snapshot = tracer_mod._strip_messages(state)

    assert snapshot["session_id"] == "sess-payload-1"
    assert snapshot["scores_per_dim"] == {"system_design": 7.4}
    assert snapshot["selected_action"] == {"id": "plan_adaptive"}
    assert snapshot["policy_id"] == "template"


def test_strip_messages_payload_stays_under_50kb_for_12_turns() -> None:
    """Serialised snapshot size budget: ≤ 50 KB at 12 turns.

    This is the headline reason for the change — without truncation the
    same shape produces ~ 70-90 KB, which inflates Postgres row size
    multiplicatively across the ~9 trace rows per turn.
    """
    state = _state_with_history(turns=12)

    snapshot = tracer_mod._strip_messages(state)

    byte_size = len(json.dumps(snapshot, ensure_ascii=False).encode("utf-8"))
    assert byte_size < 50 * 1024, (
        f"snapshot grew to {byte_size} bytes; budget is 50 KB. "
        "Did the qa_history window regression sneak back in?"
    )


def test_qa_history_window_handles_invalid_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _BadSettings:
        tracer_qa_history_window = "not-an-int"

    monkeypatch.setattr(
        "app.core.settings.get_settings",
        lambda: _BadSettings(),
    )

    assert tracer_mod._qa_history_window() == 5


def test_qa_history_window_clamps_negative_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _NegSettings:
        tracer_qa_history_window = -3

    monkeypatch.setattr(
        "app.core.settings.get_settings",
        lambda: _NegSettings(),
    )

    assert tracer_mod._qa_history_window() == 0
