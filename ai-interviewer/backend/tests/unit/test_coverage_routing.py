from __future__ import annotations

from typing import Any

from app.engine.workflow.routers import (
    route_after_eval,
    route_after_eval_diagnostics,
    route_after_skip,
)
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


def _candidate_with_focus() -> dict[str, Any]:
    return {
        "resume_parsed": {
            "projects": [
                {
                    "id": "proj_coupon",
                    "name": "Coupon Guard",
                    "tech_stack": ["Redis"],
                }
            ],
            "focus_areas": [
                {
                    "id": "focus_coupon_design",
                    "anchor_key": "focus-coupon-design",
                    "project_id": "proj_coupon",
                    "label": "Coupon consistency",
                    "priority": 1,
                    "skills": ["Redis"],
                    "dimensions": ["system_design"],
                }
            ],
        }
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


def test_route_after_eval_continues_for_standard_anchor_expansion() -> None:
    state = {
        "status": "running",
        "evaluation": {"passed": True},
        "current_dimension": "system_design",
        "turn_idx": 2,
        "formal_turn_idx": 2,
        "max_turns": 8,
        "turn_budget_remaining": 6,
        "runtime_config": {"interview_depth": "standard"},
        "candidate": _candidate_with_focus(),
        "job_spec": {
            "required_skills": ["Redis"],
            "rubric_dimensions": ["system_design", "technical_depth"],
        },
        "dimensions": ["system_design", "technical_depth"],
        "dimension_status": {
            "system_design": "passed",
            "technical_depth": "passed",
        },
        "qa_history": [
            {
                **_scored_turn(0, "system_design", passed=True),
                "resume_anchor": {"anchor_key": "focus-coupon-design"},
            },
            _scored_turn(1, "technical_depth", passed=True),
        ],
    }

    assert route_after_eval(state) == "next_question"  # type: ignore[arg-type]


def test_route_after_eval_ends_when_anchor_expansion_exhausted() -> None:
    state = {
        "status": "running",
        "evaluation": {"passed": True},
        "current_dimension": "system_design",
        "turn_idx": 2,
        "formal_turn_idx": 2,
        "max_turns": 8,
        "turn_budget_remaining": 6,
        "runtime_config": {"interview_depth": "standard"},
        "candidate": _candidate_with_focus(),
        "job_spec": {
            "required_skills": ["Redis"],
            "rubric_dimensions": ["system_design", "technical_depth"],
        },
        "dimensions": ["system_design", "technical_depth"],
        "dimension_status": {
            "system_design": "passed",
            "technical_depth": "passed",
        },
        "qa_history": [
            {
                **_scored_turn(0, "system_design", passed=True),
                "resume_anchor": {"anchor_key": "focus-coupon-design"},
            },
            {
                **_scored_turn(1, "technical_depth", passed=True),
                "resume_anchor": {"anchor_key": "focus-coupon-design"},
            },
        ],
    }

    assert route_after_eval(state) == "end"  # type: ignore[arg-type]


def test_route_after_eval_diagnostics_explains_evaluator_refine() -> None:
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

    diagnostics = route_after_eval_diagnostics(state)  # type: ignore[arg-type]

    assert diagnostics["decision"] == "refine"
    assert diagnostics["next_node"] == "refine_followup"
    assert diagnostics["decision_reason"] == "evaluator_recommended_refine"
    assert diagnostics["decision_inputs"]["current_dimension_attempts"] == 1
    assert diagnostics["decision_inputs"]["max_refines_per_dimension"] == 2


def test_route_after_eval_diagnostics_explains_coverage_advance() -> None:
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

    diagnostics = route_after_eval_diagnostics(state)  # type: ignore[arg-type]

    assert diagnostics["decision"] == "next_question"
    assert diagnostics["next_node"] == "director_sample"
    assert diagnostics["decision_reason"] == "coverage_advance"
    assert diagnostics["decision_inputs"]["coverage_advance"] is True
    assert diagnostics["decision_inputs"]["current_dimension_attempts"] == 2
    assert diagnostics["decision_inputs"]["has_pending_other_dimension"] is True


def test_route_after_eval_diagnostics_explains_evaluator_fallback() -> None:
    state = {
        "status": "running",
        "evaluation": {
            "passed": False,
            "recommended_next": "refine",
            "source": "fallback",
            "fallback_reason": "llm_failed",
        },
        "current_dimension": "technical_depth",
        "turn_idx": 1,
        "formal_turn_idx": 1,
        "max_turns": 8,
        "turn_budget_remaining": 7,
        "dimensions": ["technical_depth", "system_design"],
        "dimension_status": {
            "technical_depth": "active",
            "system_design": "pending",
        },
        "qa_history": [_failed_turn(0, "technical_depth")],
    }

    diagnostics = route_after_eval_diagnostics(state)  # type: ignore[arg-type]

    assert diagnostics["decision"] == "next_question"
    assert diagnostics["next_node"] == "director_sample"
    assert diagnostics["decision_reason"] == "evaluator_fallback"
    assert diagnostics["decision_inputs"]["evaluator_fallback"] is True


def test_route_after_eval_diagnostics_explains_all_dimensions_done() -> None:
    state = {
        "status": "running",
        "evaluation": {"passed": True},
        "current_dimension": "system_design",
        "turn_idx": 2,
        "formal_turn_idx": 2,
        "max_turns": 8,
        "turn_budget_remaining": 6,
        "runtime_config": {"interview_depth": "standard"},
        "candidate": _candidate_with_focus(),
        "job_spec": {
            "required_skills": ["Redis"],
            "rubric_dimensions": ["system_design", "technical_depth"],
        },
        "dimensions": ["system_design", "technical_depth"],
        "dimension_status": {
            "system_design": "passed",
            "technical_depth": "passed",
        },
        "qa_history": [
            {
                **_scored_turn(0, "system_design", passed=True),
                "resume_anchor": {"anchor_key": "focus-coupon-design"},
            },
            {
                **_scored_turn(1, "technical_depth", passed=True),
                "resume_anchor": {"anchor_key": "focus-coupon-design"},
            },
        ],
    }

    diagnostics = route_after_eval_diagnostics(state)  # type: ignore[arg-type]

    assert diagnostics["decision"] == "end"
    assert diagnostics["next_node"] == "final_report"
    assert diagnostics["decision_reason"] == "all_dimensions_passed"
    assert diagnostics["decision_inputs"]["all_dimensions_done"] is True
    assert diagnostics["decision_inputs"]["has_anchor_expansion_slot"] is False


def test_route_after_eval_continues_for_deep_followup_before_target() -> None:
    anchor = {
        "anchor_key": "focus-redis",
        "label": "Redis coupon consistency",
        "project_id": "proj_coupon",
        "skills": ["Redis"],
    }
    state = {
        "status": "running",
        "evaluation": {"passed": True},
        "current_dimension": "technical_depth",
        "turn_idx": 10,
        "formal_turn_idx": 10,
        "max_turns": 12,
        "turn_budget_remaining": 2,
        "runtime_config": {"interview_depth": "deep"},
        "candidate": {"resume_parsed": {"projects": [], "focus_areas": []}},
        "job_spec": {"rubric_dimensions": ["technical_depth", "system_design"]},
        "dimensions": ["technical_depth", "system_design"],
        "dimension_status": {
            "technical_depth": "passed",
            "system_design": "passed",
        },
        "qa_history": [
            {
                **_failed_turn(7, "technical_depth"),
                "resume_anchor": anchor,
            },
            {
                **_scored_turn(8, "technical_depth", passed=True),
                "resume_anchor": anchor,
            },
            _scored_turn(9, "system_design", passed=True),
        ],
    }

    diagnostics = route_after_eval_diagnostics(state)  # type: ignore[arg-type]

    assert route_after_eval(state) == "next_question"  # type: ignore[arg-type]
    assert diagnostics["decision"] == "next_question"
    assert diagnostics["decision_reason"] == "depth_followup"
    assert diagnostics["decision_inputs"]["has_depth_followup_slot"] is True
    assert diagnostics["decision_inputs"]["depth_followup_slot"]["source_turn_idx"] == 8


def test_route_after_eval_ends_deep_target_when_no_high_value_slot() -> None:
    state = {
        "status": "running",
        "evaluation": {"passed": True},
        "current_dimension": "technical_depth",
        "turn_idx": 10,
        "formal_turn_idx": 10,
        "max_turns": 12,
        "turn_budget_remaining": 2,
        "runtime_config": {"interview_depth": "deep"},
        "candidate": {"resume_parsed": {"projects": [], "focus_areas": []}},
        "job_spec": {"rubric_dimensions": ["technical_depth", "system_design"]},
        "dimensions": ["technical_depth", "system_design"],
        "dimension_status": {
            "technical_depth": "passed",
            "system_design": "passed",
        },
        "qa_history": [],
    }

    diagnostics = route_after_eval_diagnostics(state)  # type: ignore[arg-type]

    assert route_after_eval(state) == "end"  # type: ignore[arg-type]
    assert diagnostics["decision_reason"] == "depth_target_no_high_value_slot"
    assert diagnostics["decision_inputs"]["has_depth_followup_slot"] is False


def test_route_after_skip_can_continue_for_deep_followup() -> None:
    anchor = {
        "anchor_key": "focus-redis",
        "label": "Redis coupon consistency",
    }
    state = {
        "formal_turn_idx": 10,
        "max_turns": 12,
        "turn_budget_remaining": 2,
        "runtime_config": {"interview_depth": "deep"},
        "candidate": {"resume_parsed": {"projects": [], "focus_areas": []}},
        "job_spec": {"rubric_dimensions": ["technical_depth", "system_design"]},
        "dimensions": ["technical_depth", "system_design"],
        "dimension_status": {
            "technical_depth": "passed",
            "system_design": "passed",
        },
        "qa_history": [
            {**_failed_turn(7, "technical_depth"), "resume_anchor": anchor},
            {**_scored_turn(8, "technical_depth"), "resume_anchor": anchor},
        ],
    }

    assert route_after_skip(state) == "next_question"  # type: ignore[arg-type]


def test_route_after_skip_cancelled_hard_stops_before_depth_followup() -> None:
    state = {
        "status": "cancelled",
        "formal_turn_idx": 10,
        "max_turns": 12,
        "turn_budget_remaining": 2,
        "runtime_config": {"interview_depth": "deep"},
        "dimensions": ["technical_depth"],
        "dimension_status": {"technical_depth": "passed"},
        "qa_history": [
            {
                "turn_idx": 8,
                "dimension": "technical_depth",
                "question": "Q",
                "answer": "A",
                "resume_anchor": {"anchor_key": "focus-redis"},
                "evaluation": {"passed": True, "score": 8.0},
            }
        ],
    }

    assert route_after_skip(state) == "end"  # type: ignore[arg-type]


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


def test_director_targets_anchor_dimension_after_all_dimensions_passed(
    monkeypatch,
) -> None:
    from app.engine.workflow.nodes import director_sample as director_mod

    class _Bandit:
        def observation_count(self, *_args: Any, **_kwargs: Any) -> int:
            return 10

        def select(self, *_args: Any, **_kwargs: Any):
            return PLAN_DEEP_PROBE, {"mode": "test_anchor_expansion"}

    monkeypatch.setattr(director_mod, "get_bandit", lambda: _Bandit())

    state = {
        "session_id": "sess-anchor-expansion",
        "trace_id": "trace-anchor-expansion",
        "candidate": _candidate_with_focus(),
        "job_spec": {
            "level": "senior",
            "required_skills": ["Redis"],
            "rubric_dimensions": ["system_design", "technical_depth"],
        },
        "dimensions": ["system_design", "technical_depth"],
        "dimension_status": {
            "system_design": "passed",
            "technical_depth": "passed",
        },
        "current_dimension": "technical_depth",
        "turn_idx": 2,
        "formal_turn_idx": 2,
        "turn_budget_remaining": 6,
        "evaluation": {"passed": True},
        "qa_history": [
            {
                **_scored_turn(0, "system_design", passed=True),
                "resume_anchor": {"anchor_key": "focus-coupon-design"},
            },
            _scored_turn(1, "technical_depth", passed=True),
        ],
        "runtime_config": {
            "policy_mode": "template",
            "interview_depth": "standard",
        },
        "refine_mode": False,
    }

    out = director_mod.director_sample_node(state)  # type: ignore[arg-type]

    assert out["selected_action"]["diagnostics"]["mode"] == "anchor_expansion"
    assert out["selected_action"]["diagnostics"]["target_anchor_key"] == "focus-coupon-design"
    assert out["current_dimension"] == "system_design"
    assert out["dimension_status"]["system_design"] == "passed"
    assert out["dimension_status"]["technical_depth"] == "passed"


def test_director_forces_depth_followup_slot_after_all_dimensions_passed(
    monkeypatch,
) -> None:
    from app.engine.workflow.nodes import director_sample as director_mod

    class _Bandit:
        def observation_count(self, *_args: Any, **_kwargs: Any) -> int:
            return 10

        def select(self, *_args: Any, **_kwargs: Any):
            return PLAN_ADAPTIVE, {"mode": "test_prefers_non_deep"}

    monkeypatch.setattr(director_mod, "get_bandit", lambda: _Bandit())
    anchor = {
        "anchor_key": "focus-redis",
        "label": "Redis coupon consistency",
        "project_id": "proj_coupon",
        "skills": ["Redis"],
        "dimensions": ["technical_depth"],
    }

    state = {
        "session_id": "sess-depth-followup",
        "trace_id": "trace-depth-followup",
        "candidate": {"resume_parsed": {"projects": [], "focus_areas": []}},
        "job_spec": {
            "level": "senior",
            "required_skills": ["Redis"],
            "rubric_dimensions": ["technical_depth", "system_design"],
        },
        "dimensions": ["technical_depth", "system_design"],
        "dimension_status": {
            "technical_depth": "passed",
            "system_design": "passed",
        },
        "current_dimension": "system_design",
        "turn_idx": 10,
        "formal_turn_idx": 10,
        "max_turns": 12,
        "turn_budget_remaining": 2,
        "evaluation": {"passed": True},
        "qa_history": [
            {**_failed_turn(7, "technical_depth"), "resume_anchor": anchor},
            {**_scored_turn(8, "technical_depth", passed=True), "resume_anchor": anchor},
            _scored_turn(9, "system_design", passed=True),
        ],
        "runtime_config": {
            "policy_mode": "template",
            "interview_depth": "deep",
        },
        "refine_mode": False,
    }

    out = director_mod.director_sample_node(state)  # type: ignore[arg-type]

    assert out["selected_action"]["id"] == PLAN_DEEP_PROBE.id
    assert out["selected_action"]["diagnostics"]["mode"] == "depth_followup"
    assert (
        out["selected_action"]["diagnostics"]["depth_followup_slot"]["source_turn_idx"]
        == 8
    )
    assert out["current_dimension"] == "technical_depth"
    assert out["dimension_status"]["technical_depth"] == "passed"


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
