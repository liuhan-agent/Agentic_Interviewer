from __future__ import annotations

from typing import Any

from app.engine.workflow.routers import route_after_eval
from app.ml.rl.action_space import PLAN_ADAPTIVE, PLAN_DEEP_PROBE, PLAN_SWITCH


def _failed_turn(turn_idx: int, dimension: str) -> dict[str, Any]:
    return {
        "turn_idx": turn_idx,
        "dimension": dimension,
        "evaluation": {"passed": False, "score": 5.0},
    }


def _scored_turn(turn_idx: int, dimension: str, *, passed: bool = True) -> dict[str, Any]:
    return {
        "turn_idx": turn_idx,
        "dimension": dimension,
        "evaluation": {"passed": passed, "score": 9.0},
    }


def _fallback_turn(turn_idx: int, dimension: str) -> dict[str, Any]:
    return {
        "turn_idx": turn_idx,
        "dimension": dimension,
        "evaluation": {
            "passed": False,
            "score": 5.0,
            "source": "fallback",
            "fallback_reason": "llm_failed",
        },
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


def test_director_prioritizes_unscored_dimension_after_current_passed(
    monkeypatch,
) -> None:
    from app.engine.workflow.nodes import director_sample as director_mod

    class _Bandit:
        def observation_count(self, *_args: Any, **_kwargs: Any) -> int:
            return 10

        def select(self, *_args: Any, **_kwargs: Any):
            return PLAN_DEEP_PROBE, {"mode": "test_prefers_passed_dimension"}

    monkeypatch.setattr(director_mod, "get_bandit", lambda: _Bandit())

    state = {
        "session_id": "sess-coverage-priority",
        "trace_id": "trace-coverage-priority",
        "job_spec": {"level": "senior"},
        "dimensions": ["technical_depth", "system_design", "coding_quality"],
        "dimension_status": {
            "technical_depth": "passed",
            "system_design": "pending",
            "coding_quality": "pending",
        },
        "current_dimension": "technical_depth",
        "turn_idx": 1,
        "formal_turn_idx": 1,
        "turn_budget_remaining": 7,
        "evaluation": {"passed": True},
        "qa_history": [_scored_turn(0, "technical_depth", passed=True)],
        "runtime_config": {"policy_mode": "template"},
        "refine_mode": False,
    }

    out = director_mod.director_sample_node(state)  # type: ignore[arg-type]

    assert out["selected_action"]["id"] == PLAN_SWITCH.id
    assert out["selected_action"]["diagnostics"]["mode"] == "coverage_priority_switch"
    assert out["selected_action"]["diagnostics"]["target_dimension"] == "system_design"
    assert out["current_dimension"] == "system_design"
    assert out["dimension_status"]["technical_depth"] == "passed"
    assert out["dimension_status"]["system_design"] == "active"


def test_director_forces_unscored_dimension_when_remaining_turns_are_tight(
    monkeypatch,
) -> None:
    from app.engine.workflow.nodes import director_sample as director_mod

    class _Bandit:
        def observation_count(self, *_args: Any, **_kwargs: Any) -> int:
            return 10

        def select(self, *_args: Any, **_kwargs: Any):
            return PLAN_DEEP_PROBE, {"mode": "test_prefers_same_dimension"}

    monkeypatch.setattr(director_mod, "get_bandit", lambda: _Bandit())

    state = {
        "session_id": "sess-tight-coverage",
        "trace_id": "trace-tight-coverage",
        "job_spec": {"level": "senior"},
        "dimensions": ["technical_depth", "system_design", "coding_quality"],
        "dimension_status": {
            "technical_depth": "active",
            "system_design": "pending",
            "coding_quality": "pending",
        },
        "current_dimension": "technical_depth",
        "turn_idx": 3,
        "formal_turn_idx": 3,
        "turn_budget_remaining": 2,
        "evaluation": {"passed": False},
        "qa_history": [_scored_turn(0, "technical_depth", passed=False)],
        "runtime_config": {"policy_mode": "template"},
        "refine_mode": True,
    }

    out = director_mod.director_sample_node(state)  # type: ignore[arg-type]

    assert out["selected_action"]["id"] == PLAN_SWITCH.id
    assert out["selected_action"]["diagnostics"]["mode"] == "coverage_priority_switch"
    assert out["current_dimension"] == "system_design"
    assert out["dimension_status"]["technical_depth"] == "pending"
    assert out["dimension_status"]["system_design"] == "active"


def test_director_keeps_current_dimension_when_it_has_no_valid_score(
    monkeypatch,
) -> None:
    from app.engine.workflow.nodes import director_sample as director_mod

    class _Bandit:
        def observation_count(self, *_args: Any, **_kwargs: Any) -> int:
            return 10

        def select(self, *_args: Any, **_kwargs: Any):
            return PLAN_ADAPTIVE, {"mode": "test_same_dimension"}

    monkeypatch.setattr(director_mod, "get_bandit", lambda: _Bandit())

    state = {
        "session_id": "sess-no-score-yet",
        "trace_id": "trace-no-score-yet",
        "job_spec": {"level": "senior"},
        "dimensions": ["technical_depth", "system_design"],
        "dimension_status": {
            "technical_depth": "active",
            "system_design": "pending",
        },
        "current_dimension": "technical_depth",
        "turn_idx": 0,
        "formal_turn_idx": 0,
        "turn_budget_remaining": 1,
        "evaluation": {},
        "qa_history": [],
        "runtime_config": {"policy_mode": "template"},
        "refine_mode": False,
    }

    out = director_mod.director_sample_node(state)  # type: ignore[arg-type]

    assert out["selected_action"]["id"] == PLAN_ADAPTIVE.id
    assert out["current_dimension"] == "technical_depth"


def test_director_allows_deepening_after_all_dimensions_have_scores(
    monkeypatch,
) -> None:
    from app.engine.workflow.nodes import director_sample as director_mod

    class _Bandit:
        def observation_count(self, *_args: Any, **_kwargs: Any) -> int:
            return 10

        def select(self, *_args: Any, **_kwargs: Any):
            return PLAN_DEEP_PROBE, {"mode": "test_deepen_after_coverage"}

    monkeypatch.setattr(director_mod, "get_bandit", lambda: _Bandit())

    state = {
        "session_id": "sess-all-covered",
        "trace_id": "trace-all-covered",
        "job_spec": {"level": "senior"},
        "dimensions": ["technical_depth", "system_design"],
        "dimension_status": {
            "technical_depth": "passed",
            "system_design": "passed",
        },
        "current_dimension": "technical_depth",
        "turn_idx": 2,
        "formal_turn_idx": 2,
        "turn_budget_remaining": 6,
        "evaluation": {"passed": True},
        "qa_history": [
            _scored_turn(0, "technical_depth", passed=True),
            _scored_turn(1, "system_design", passed=True),
        ],
        "runtime_config": {"policy_mode": "template"},
        "refine_mode": False,
    }

    out = director_mod.director_sample_node(state)  # type: ignore[arg-type]

    assert out["selected_action"]["id"] == PLAN_DEEP_PROBE.id
    assert out["current_dimension"] == "technical_depth"


def test_director_does_not_count_fallback_as_dimension_coverage(monkeypatch) -> None:
    from app.engine.workflow.nodes import director_sample as director_mod

    class _Bandit:
        def observation_count(self, *_args: Any, **_kwargs: Any) -> int:
            return 10

        def select(self, *_args: Any, **_kwargs: Any):
            return PLAN_DEEP_PROBE, {"mode": "test_prefers_passed_dimension"}

    monkeypatch.setattr(director_mod, "get_bandit", lambda: _Bandit())

    state = {
        "session_id": "sess-fallback-uncovered",
        "trace_id": "trace-fallback-uncovered",
        "job_spec": {"level": "senior"},
        "dimensions": ["technical_depth", "system_design", "coding_quality"],
        "dimension_status": {
            "technical_depth": "passed",
            "system_design": "pending",
            "coding_quality": "pending",
        },
        "current_dimension": "technical_depth",
        "turn_idx": 2,
        "formal_turn_idx": 2,
        "turn_budget_remaining": 6,
        "evaluation": {"passed": True},
        "qa_history": [
            _scored_turn(0, "technical_depth", passed=True),
            _fallback_turn(1, "system_design"),
        ],
        "runtime_config": {"policy_mode": "template"},
        "refine_mode": False,
    }

    out = director_mod.director_sample_node(state)  # type: ignore[arg-type]

    assert out["current_dimension"] == "system_design"
