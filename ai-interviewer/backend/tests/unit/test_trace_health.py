"""Pin down the rules of the admin trace-health classifier.

``_trace_health`` is the small private helper behind two visible
properties of the admin observability surface:

- ``GET /admin/interview-sessions`` decorates each session row with a
  ``trace_health`` field used by the UI badge.
- ``GET /admin/interview-sessions/{session_id}/traces`` echoes the same
  classifier into the per-session trace explorer panel.

Before this change the classifier ignored the session-level status:
a session that happened to write an ``evaluator`` and ``reward_update``
row before being cancelled mid-flight still showed up as
``"complete"``. The tests below lock in:

1. The legacy node-level rules (missing / partial / complete by node
   coverage) still hold when ``session_status`` is not supplied —
   this preserves backwards compatibility for any caller that has not
   been updated yet.
2. A finished session is reported as ``complete`` only when its
   ``InterviewSession.status == "completed"``; ``"cancelled"`` and
   ``"running"`` both downgrade to ``"partial"`` even if the node
   coverage looks clean.
"""
from __future__ import annotations

import pytest

from app.api.v1.admin import _trace_health


# ---------------------------------------------------------------------------
# Legacy contract (no session_status passed) — must not regress.
# ---------------------------------------------------------------------------


def test_returns_missing_when_no_nodes() -> None:
    assert _trace_health([]) == "missing"


@pytest.mark.parametrize(
    "nodes",
    [
        [{"node": "evaluator"}],
        [{"node": "reward_update"}],
        [{"node": "final_report"}],
        [{"node": "ask_question"}, {"node": "verification"}],
    ],
)
def test_returns_partial_when_only_one_signal(nodes: list[dict[str, str]]) -> None:
    """Either evaluator or close-out alone is not enough."""
    assert _trace_health(nodes) == "partial"


@pytest.mark.parametrize(
    "close_node",
    ["reward_update", "final_report"],
)
def test_returns_complete_with_evaluator_and_close_signal(close_node: str) -> None:
    """Legacy: evaluator + (reward_update OR final_report) ⇒ complete."""
    nodes = [{"node": "evaluator"}, {"node": close_node}]
    assert _trace_health(nodes) == "complete"


# ---------------------------------------------------------------------------
# New contract: session_status gates the "complete" verdict.
# ---------------------------------------------------------------------------


def test_completed_session_passes_through_complete() -> None:
    nodes = [{"node": "evaluator"}, {"node": "final_report"}]
    assert _trace_health(nodes, session_status="completed") == "complete"


@pytest.mark.parametrize(
    "status",
    ["cancelled", "running", "errored"],
)
def test_non_completed_session_downgrades_to_partial(status: str) -> None:
    """Even with full node coverage, an unfinished session is partial.

    This blocks the "false-complete" panel state where an interview
    that was abandoned mid-flight (``status='cancelled'``) but had
    already written ``evaluator`` + ``reward_update`` rows still
    flashed a green badge.
    """
    nodes = [{"node": "evaluator"}, {"node": "reward_update"}]
    assert _trace_health(nodes, session_status=status) == "partial"


def test_session_status_none_is_back_compat() -> None:
    """An explicit ``None`` is the same as not passing the kwarg."""
    nodes = [{"node": "evaluator"}, {"node": "reward_update"}]
    assert _trace_health(nodes, session_status=None) == "complete"
