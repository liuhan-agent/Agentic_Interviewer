from __future__ import annotations

from typing import Any

from app.engine.workflow.routers import route_after_eval
from app.ml.rl.action_space import PLAN_ADAPTIVE, PLAN_SWITCH


def _failed_turn(turn_idx: int, dimension: str) -> dict[str, Any]:
    return {
        "turn_idx": turn_idx,
        "dimension": dimension,
        "evaluation": {"passed": False, "score": 5.0},
    }


def test_route_after_eval_advances_when_refine_cap_reached() -> None:
    state = {
        "status": "running",
        "evaluation": {"passed": False, "recommended_next": "refine"},
        "current_dimension": "technical_depth",
        "turn_idx": 2,
        "formal_turn_idx": 2,
        "max_turns": 8,
        "turn_budget_remaining": 6,
        "runtime_config": {"max_refines_per_dimension": 2},
        "dimensions": ["technical_depth", "system_design"],
        "dimension_status": {
            "technical_depth": "active",
            "system_design": "pending",
        },
        "qa_history": [
            _failed_turn(0, "technical_depth"),
            _failed_turn(1, "technical_depth"),
        ],
    }

    assert route_after_eval(state) == "next_question"  # type: ignore[arg-type]


def test_route_after_eval_keeps_refining_before_cap() -> None:
    state = {
        "status": "running",
        "evaluation": {"passed": False, "recommended_next": "refine"},
        "current_dimension": "technical_depth",
        "turn_idx": 1,
        "formal_turn_idx": 1,
        "max_turns": 8,
        "turn_budget_remaining": 7,
        "runtime_config": {"max_refines_per_dimension": 2},
        "dimensions": ["technical_depth", "system_design"],
        "dimension_status": {
            "technical_depth": "active",
            "system_design": "pending",
        },
        "qa_history": [_failed_turn(0, "technical_depth")],
    }

    assert route_after_eval(state) == "refine"  # type: ignore[arg-type]


def test_director_forces_switch_when_refine_cap_reached(monkeypatch) -> None:
    from app.engine.workflow.nodes import director_sample as director_mod

    class _Bandit:
        def observation_count(self, *_args: Any, **_kwargs: Any) -> int:
            return 10

        def select(self, *_args: Any, **_kwargs: Any):
            return PLAN_ADAPTIVE, {"mode": "test_prefers_same_dimension"}

    monkeypatch.setattr(director_mod, "get_bandit", lambda: _Bandit())

    state = {
        "session_id": "sess-coverage",
        "trace_id": "trace-coverage",
        "job_spec": {"level": "senior"},
        "dimensions": ["technical_depth", "system_design"],
        "dimension_status": {
            "technical_depth": "active",
            "system_design": "pending",
        },
        "current_dimension": "technical_depth",
        "turn_idx": 2,
        "formal_turn_idx": 2,
        "evaluation": {"passed": False},
        "qa_history": [
            _failed_turn(0, "technical_depth"),
            _failed_turn(1, "technical_depth"),
        ],
        "runtime_config": {
            "policy_mode": "template",
            "max_refines_per_dimension": 2,
        },
        "refine_mode": False,
    }

    out = director_mod.director_sample_node(state)  # type: ignore[arg-type]

    assert out["selected_action"]["id"] == PLAN_SWITCH.id
    assert out["selected_action"]["diagnostics"]["mode"] == "coverage_force_switch"
    assert out["current_dimension"] == "system_design"
