"""Tests for the shared classifier in ``app.services.trace_health``.

The classifier is consumed by both the admin panel and the report
API: any rule drift here would silently misalign the two surfaces,
so the tests below pin the behaviour. They mirror the assertions in
``test_trace_health.py`` (which targets the admin shim) so a future
refactor that accidentally diverges the two would fail in both places.
"""
from __future__ import annotations

import pytest

from app.services.trace_health import classify_trace_health


def test_classifies_empty_node_list_as_missing() -> None:
    assert classify_trace_health([]) == "missing"


@pytest.mark.parametrize(
    "nodes",
    [
        [{"node": "evaluator"}],
        [{"node": "reward_update"}],
        [{"node": "final_report"}],
        [{"node": "ask_question"}, {"node": "verification"}],
    ],
)
def test_partial_when_only_one_signal(nodes: list[dict[str, str]]) -> None:
    assert classify_trace_health(nodes) == "partial"


@pytest.mark.parametrize("close_node", ["reward_update", "final_report"])
def test_complete_when_evaluator_plus_close_node(close_node: str) -> None:
    assert (
        classify_trace_health([{"node": "evaluator"}, {"node": close_node}])
        == "complete"
    )


def test_completed_session_passes_through_complete() -> None:
    assert (
        classify_trace_health(
            [{"node": "evaluator"}, {"node": "final_report"}],
            session_status="completed",
        )
        == "complete"
    )


@pytest.mark.parametrize("status", ["cancelled", "running", "errored"])
def test_unfinished_session_downgrades_to_partial(status: str) -> None:
    assert (
        classify_trace_health(
            [{"node": "evaluator"}, {"node": "reward_update"}],
            session_status=status,
        )
        == "partial"
    )


def test_session_status_none_is_back_compat() -> None:
    assert (
        classify_trace_health(
            [{"node": "evaluator"}, {"node": "reward_update"}],
            session_status=None,
        )
        == "complete"
    )


def test_admin_shim_delegates_to_service() -> None:
    """Smoke test: the admin shim must keep producing the same answers
    as the service, otherwise we have two sources of truth again."""
    from app.api.v1.admin import _trace_health

    nodes = [{"node": "evaluator"}, {"node": "reward_update"}]
    assert _trace_health(nodes) == classify_trace_health(nodes)
    assert _trace_health(nodes, session_status="cancelled") == classify_trace_health(
        nodes, session_status="cancelled"
    )
