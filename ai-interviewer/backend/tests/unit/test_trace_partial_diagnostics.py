"""Tests for human-readable trace coverage diagnostics."""
from __future__ import annotations


def test_partial_diagnostics_names_missing_key_nodes() -> None:
    from app.services.trace_health import trace_diagnostics

    diag = trace_diagnostics(
        [{"node": "evaluator"}],
        session_status="running",
    )

    assert diag["health"] == "partial"
    assert diag["present_nodes"] == ["evaluator"]
    assert diag["last_node"] == "evaluator"
    assert diag["session_status"] == "running"
    assert "reward_update" in diag["missing_key_nodes"]
    assert "final_report" in diag["missing_key_nodes"]


def test_complete_health_can_still_report_missing_decision_nodes() -> None:
    from app.services.trace_health import trace_diagnostics

    diag = trace_diagnostics(
        [{"node": "evaluator"}, {"node": "final_report"}],
        session_status="completed",
    )

    assert diag["health"] == "complete"
    assert "director_sample" in diag["missing_key_nodes"]
    assert "ask_question" in diag["missing_key_nodes"]
    assert "verification" in diag["missing_key_nodes"]


def test_missing_diagnostics_keep_empty_shape() -> None:
    from app.services.trace_health import trace_diagnostics

    diag = trace_diagnostics([], session_status=None)

    assert diag == {
        "health": "missing",
        "present_nodes": [],
        "missing_key_nodes": [
            "director_sample",
            "ask_question",
            "evaluator",
            "verification",
            "reward_update",
            "final_report",
        ],
        "last_node": None,
        "session_status": None,
    }
