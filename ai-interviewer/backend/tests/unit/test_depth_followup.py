from __future__ import annotations

from typing import Any

from app.engine.workflow.depth_followup import (
    preserve_depth_followup_dimension_status,
    select_depth_followup_slot,
    should_consider_depth_followup,
)


def _anchor(key: str = "focus-redis") -> dict[str, Any]:
    return {
        "anchor_key": key,
        "label": "Redis coupon consistency",
        "project_id": "proj_coupon",
        "skills": ["Redis", "Lua"],
    }


def _turn(
    turn_idx: int,
    dimension: str,
    *,
    score: float,
    passed: bool,
    anchor: dict[str, Any] | None = None,
    phase: str | None = None,
    depth_followup: dict[str, Any] | None = None,
    skipped: bool = False,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "turn_idx": turn_idx,
        "dimension": dimension,
        "question": f"Q{turn_idx}",
        "answer": "" if skipped else "A detailed answer",
        "answer_intent": "skipped" if skipped else "normal",
        "evaluation": {
            "score": score,
            "passed": passed,
            "recommended_next": "advance" if passed else "refine",
            "weaknesses": [] if passed else ["Missing failure boundary"],
            "failure_categories": [] if passed else ["weak_debugging"],
        },
    }
    if anchor is not None:
        out["resume_anchor"] = anchor
    if phase is not None:
        out["phase"] = phase
    if depth_followup is not None:
        out["depth_followup"] = depth_followup
    if skipped:
        out["evaluation"]["skipped"] = True
    return out


def _state(**overrides: Any) -> dict[str, Any]:
    state: dict[str, Any] = {
        "runtime_config": {"interview_depth": "deep"},
        "formal_turn_idx": 10,
        "max_turns": 12,
        "turn_budget_remaining": 2,
        "dimensions": ["technical_depth", "system_design"],
        "dimension_status": {
            "technical_depth": "passed",
            "system_design": "passed",
        },
        "qa_history": [],
    }
    state.update(overrides)
    return state


def test_should_consider_depth_followup_only_for_deep_under_target_done() -> None:
    assert should_consider_depth_followup(_state()) is True  # type: ignore[arg-type]
    assert (
        should_consider_depth_followup(
            _state(runtime_config={"interview_depth": "standard"})
        )
        is False
    )
    assert should_consider_depth_followup(_state(formal_turn_idx=12)) is False
    assert should_consider_depth_followup(_state(turn_budget_remaining=0)) is False
    assert (
        should_consider_depth_followup(
            _state(dimension_status={"technical_depth": "passed", "system_design": "active"})
        )
        is False
    )


def test_select_depth_followup_prefers_recent_refine_then_passed_anchor() -> None:
    anchor = _anchor()
    state = _state(
        qa_history=[
            _turn(7, "technical_depth", score=5.0, passed=False, anchor=anchor),
            _turn(8, "technical_depth", score=9.0, passed=True, anchor=anchor),
        ]
    )

    slot = select_depth_followup_slot(state)  # type: ignore[arg-type]

    assert slot is not None
    assert slot["phase"] == "depth_followup"
    assert slot["source_turn_idx"] == 8
    assert slot["dimension"] == "technical_depth"
    assert slot["resume_anchor"]["anchor_key"] == "focus-redis"
    assert slot["depth_reason"] == "recent_refine_then_passed"
    assert slot["depth_slot_rank"] == 1
    assert slot["depth_target_turns"] == 12
    assert slot["plan_template"] == "deep_probe"


def test_select_depth_followup_recovers_failed_depth_followup_once() -> None:
    anchor = _anchor()
    state = _state(
        formal_turn_idx=11,
        qa_history=[
            _turn(8, "technical_depth", score=9.0, passed=True, anchor=anchor),
            _turn(
                10,
                "technical_depth",
                score=6.0,
                passed=False,
                anchor=anchor,
                phase="depth_followup",
                depth_followup={
                    "source_turn_idx": 8,
                    "depth_reason": "recent_refine_then_passed",
                    "depth_slot_rank": 1,
                    "depth_target_turns": 12,
                },
            ),
        ],
    )

    slot = select_depth_followup_slot(state)  # type: ignore[arg-type]

    assert slot is not None
    assert slot["source_turn_idx"] == 8
    assert slot["parent_turn_idx"] == 10
    assert slot["depth_reason"] == "depth_followup_recovery"
    assert slot["depth_slot_rank"] == 2


def test_select_depth_followup_returns_none_without_real_evidence() -> None:
    assert select_depth_followup_slot(_state()) is None  # type: ignore[arg-type]


def test_preserve_depth_followup_dimension_status_keeps_passed_status() -> None:
    status = preserve_depth_followup_dimension_status(
        state={
            "current_question": {
                "phase": "depth_followup",
                "dimension": "technical_depth",
            },
            "dimension_status": {"technical_depth": "passed"},
        },
        status={"technical_depth": "active"},
        dimension="technical_depth",
    )

    assert status["technical_depth"] == "passed"
