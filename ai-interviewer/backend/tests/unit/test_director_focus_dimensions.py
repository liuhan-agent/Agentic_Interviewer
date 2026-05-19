from __future__ import annotations

from app.engine.workflow.nodes import director_sample


def test_pick_next_dimension_prefers_pending_focus_dimension() -> None:
    state = {
        "dimensions": ["technical_depth", "system_design", "communication"],
        "focus_dimensions": ["system_design"],
        "dimension_status": {
            "technical_depth": "pending",
            "system_design": "pending",
            "communication": "pending",
        },
    }

    assert director_sample._pick_next_dimension(state) == "system_design"


def test_focus_dimension_skips_passed_dimensions() -> None:
    state = {
        "dimensions": ["technical_depth", "system_design", "communication"],
        "focus_dimensions": ["system_design", "communication"],
        "dimension_status": {
            "technical_depth": "pending",
            "system_design": "passed",
            "communication": "pending",
        },
    }

    assert director_sample._pick_next_dimension(state) == "communication"


def test_switch_effect_prefers_remaining_focus_dimension() -> None:
    state = {
        "dimensions": ["technical_depth", "system_design", "communication"],
        "focus_dimensions": ["communication"],
        "dimension_status": {
            "technical_depth": "active",
            "system_design": "pending",
            "communication": "pending",
        },
    }

    next_dim, status = director_sample._apply_dimension_effect(
        state,
        director_sample.PLAN_SWITCH,
        "technical_depth",
    )

    assert next_dim == "communication"
    assert status["technical_depth"] == "pending"
    assert status["communication"] == "active"
