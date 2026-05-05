"""Audit F4 — fallback turns shouldn't count toward refine cap."""
from __future__ import annotations

from app.engine.workflow.routers import (
    _attempts_for_dimension,
    should_advance_for_coverage,
)


def _qa_turn(dim: str, *, fallback: bool, score: float = 6.0, passed: bool = False) -> dict:
    evaluation = {
        "score": score,
        "passed": passed,
        "weaknesses": [],
        "rationale": "",
    }
    if fallback:
        evaluation["source"] = "fallback"
        evaluation["fallback_reason"] = "llm_failed"
    return {"dimension": dim, "evaluation": evaluation}


def test_attempts_excludes_fallback_turns() -> None:
    state = {
        "qa_history": [
            _qa_turn("technical_depth", fallback=True),
            _qa_turn("technical_depth", fallback=True),
            _qa_turn("technical_depth", fallback=False),
        ],
    }
    # Two of three were fallback → only one real attempt counts.
    assert _attempts_for_dimension(state, "technical_depth") == 1


def test_attempts_counts_real_turns_only() -> None:
    state = {
        "qa_history": [
            _qa_turn("communication", fallback=False),
            _qa_turn("communication", fallback=False),
            _qa_turn("technical_depth", fallback=False),
        ],
    }
    assert _attempts_for_dimension(state, "communication") == 2
    assert _attempts_for_dimension(state, "technical_depth") == 1


def test_coverage_advance_not_triggered_by_fallback_attempts() -> None:
    # Two fallbacks on technical_depth + a pending other dim should
    # NOT trip coverage_advance — the dim hasn't really been probed.
    state = {
        "qa_history": [
            _qa_turn("technical_depth", fallback=True),
            _qa_turn("technical_depth", fallback=True),
        ],
        "evaluation": {"passed": False},
        "current_dimension": "technical_depth",
        "current_question": {"dimension": "technical_depth"},
        "dimensions": ["technical_depth", "problem_solving"],
        "dimension_status": {"technical_depth": "active", "problem_solving": "pending"},
        "runtime_config": {"max_refines_per_dimension": 2},
    }
    assert should_advance_for_coverage(state) is False


def test_coverage_advance_triggered_by_real_attempts_at_cap() -> None:
    state = {
        "qa_history": [
            _qa_turn("technical_depth", fallback=False),
            _qa_turn("technical_depth", fallback=False),
        ],
        "evaluation": {"passed": False},
        "current_dimension": "technical_depth",
        "current_question": {"dimension": "technical_depth"},
        "dimensions": ["technical_depth", "problem_solving"],
        "dimension_status": {"technical_depth": "active", "problem_solving": "pending"},
        "runtime_config": {"max_refines_per_dimension": 2},
    }
    assert should_advance_for_coverage(state) is True
