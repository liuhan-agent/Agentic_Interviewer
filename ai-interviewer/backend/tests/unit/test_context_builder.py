"""Unit tests for :func:`build_context_frame_for_generator`.

Verifies that the builder populates the frame slots with exactly the
same strings the legacy generator path would produce, independent of
the renderer. Think of it as a white-box test of the ``payload`` shape.
"""
from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch

from app.engine.context import (
    build_context_frame_for_evaluator,
    build_context_frame_for_generator,
    build_context_frame_for_verifier,
)


def _fake_load_prompt(name: str) -> str:
    # Use a stable, non-empty system prompt so tests don't depend on
    # whatever the real ``system_skeleton.md`` happens to say today.
    if name == "system_skeleton.md":
        return "SYS_SKELETON"
    raise AssertionError(f"unexpected prompt name: {name}")


def test_builder_produces_expected_slot_shape() -> None:
    """Happy path: every payload key is exactly what the prompt
    template will substitute into ``generator_task.md``."""
    with (
        patch(
            "app.engine.context.builder.load_prompt",
            side_effect=_fake_load_prompt,
        ),
        patch(
            "app.engine.context.builder.build_strategy_index",
            return_value="STRATEGY_INDEX",
        ),
    ):
        frame = build_context_frame_for_generator(
            dimension="system_design",
            action={"name": "deepen_technical"},
            job_spec={"title": "Senior Backend", "level": "senior"},
            candidate={"resume_parsed": {"highlights": ["h1", "h2"]}},
            recent_qa=[{"q": "Q1", "a": "A1"}],
            retrieval_block="RETRIEVAL",
            question_seed_block="STRUCTURED_SEED",
            candidate_anchor_block="CANDIDATE_ANCHOR",
            strategy_block="STRATEGY",
            resume_anchor={"project_name": "Payment Migration"},
            qa_summary="",
            refine_mode=False,
            contract_hints={"bar_level": "standard"},
            target_difficulty="medium",
            probe_intent="architecture_challenge",
        )

    assert frame.agent_role == "generator"
    assert frame.turn_idx == 1  # derived from len(recent_qa)
    assert frame.static_system == "SYS_SKELETON"
    assert frame.dynamic_system == "STRATEGY_INDEX"

    # Payload keys map 1:1 onto ``generator_task.md`` variables.
    payload: dict[str, Any] = frame.payload
    assert payload["dimension"] == "system_design"
    assert payload["target_difficulty"] == "medium"
    assert payload["probe_intent"] == "architecture_challenge"
    assert payload["action"] == json.dumps(
        {"name": "deepen_technical"}, ensure_ascii=False
    )
    assert payload["refine_mode"] == "False"
    assert payload["job_title"] == "Senior Backend"
    assert payload["job_level"] == "senior"
    assert payload["highlights"] == json.dumps(["h1", "h2"], ensure_ascii=False)
    assert payload["resume_anchor"] == json.dumps(
        {"project_name": "Payment Migration"}, ensure_ascii=False
    )
    assert 'RECENT_QA (verbatim) = [{"q": "Q1", "a": "A1"}]' in payload["history_section"]
    assert payload["retrieval"] == "RETRIEVAL"
    assert payload["question_seed"] == "STRUCTURED_SEED"
    assert payload["candidate_anchor"] == "CANDIDATE_ANCHOR"
    assert payload["strategy"] == "STRATEGY"
    # PLAN_SKILL_INJECTION: default placeholder when caller does not
    # pass ``skill_block`` (feature flag OFF path).
    assert payload["skills"] == "(no relevant interview skills)"
    # PLAN_DRIFT_RAG_FEEDBACK: default placeholder when caller does not
    # pass ``avoid_patterns_block`` (feature flag OFF / empty drift).
    assert payload["avoid_patterns"] == (
        "(no historical shallow patterns on this dimension)"
    )
    assert payload["contract_hints"] == json.dumps(
        {"bar_level": "standard"}, ensure_ascii=False
    )
    assert payload["self_intro_profile"] == "{}"


def test_builder_handles_empty_strategy_index_as_empty_dynamic() -> None:
    """``build_strategy_index`` returning an empty string must collapse
    the dynamic layer so ``frame.system_text`` equals the static prompt
    alone - that's the legacy behaviour."""
    with (
        patch(
            "app.engine.context.builder.load_prompt",
            side_effect=_fake_load_prompt,
        ),
        patch(
            "app.engine.context.builder.build_strategy_index",
            return_value="",
        ),
    ):
        frame = build_context_frame_for_generator(
            dimension="coding",
            action={},
            job_spec={},
            candidate={},
            recent_qa=[],
            retrieval_block="",
            strategy_block="",
        )
    assert frame.dynamic_system == ""
    assert frame.system_text == "SYS_SKELETON"


def test_builder_turn_idx_override() -> None:
    """Callers with an authoritative turn counter can override the
    default ``len(recent_qa)``."""
    with (
        patch(
            "app.engine.context.builder.load_prompt",
            side_effect=_fake_load_prompt,
        ),
        patch(
            "app.engine.context.builder.build_strategy_index",
            return_value="",
        ),
    ):
        frame = build_context_frame_for_generator(
            dimension="coding",
            action={},
            job_spec={},
            candidate={},
            recent_qa=[{"q": "Q1", "a": "A1"}, {"q": "Q2", "a": "A2"}],
            retrieval_block="",
            strategy_block="",
            turn_idx=42,
        )
    assert frame.turn_idx == 42


def test_builder_defaults_for_missing_job_spec_fields() -> None:
    """Legacy code fell back to ``"(unspecified)"`` / ``"mid"``. Keep
    that exact contract so downstream prompts don't change."""
    with (
        patch(
            "app.engine.context.builder.load_prompt",
            side_effect=_fake_load_prompt,
        ),
        patch(
            "app.engine.context.builder.build_strategy_index",
            return_value="",
        ),
    ):
        frame = build_context_frame_for_generator(
            dimension="coding",
            action={},
            job_spec={},  # empty
            candidate={},  # no resume_parsed key
            recent_qa=[],
            retrieval_block="",
            strategy_block="",
        )
    assert frame.payload["job_title"] == "(unspecified)"
    assert frame.payload["job_level"] == "mid"
    # No resume_parsed => highlights is the default empty list.
    assert frame.payload["highlights"] == "[]"


def test_evaluator_builder_happy_path() -> None:
    """Evaluator frame mirrors ``evaluate_answer`` kwargs 1:1 and
    always has an empty dynamic system layer."""
    with patch(
        "app.engine.context.builder.load_prompt",
        side_effect=_fake_load_prompt,
    ):
        frame = build_context_frame_for_evaluator(
            dimension="system_design",
            question="Design a rate limiter.",
            rubric_points=["clarity", "depth"],
            answer="I would use a token bucket...",
            quality_threshold=7.5,
            contract={"must_cover": ["clarity"]},
        )

    assert frame.agent_role == "evaluator"
    assert frame.turn_idx == 0
    assert frame.static_system == "SYS_SKELETON"
    # Evaluator never carries a dynamic layer today; the renderer relies
    # on this to keep byte-equivalence with the legacy single system msg.
    assert frame.dynamic_system == ""
    assert frame.system_text == "SYS_SKELETON"

    payload: dict[str, Any] = frame.payload
    assert payload["dimension"] == "system_design"
    assert payload["question"] == "Design a rate limiter."
    assert payload["rubric_points"] == json.dumps(
        ["clarity", "depth"], ensure_ascii=False
    )
    assert payload["contract"] == json.dumps(
        {"must_cover": ["clarity"]}, ensure_ascii=False
    )
    assert payload["answer"] == "I would use a token bucket..."
    assert payload["threshold"] == 7.5


def test_evaluator_builder_empty_answer_defaults() -> None:
    """Empty answer string collapses to the ``(empty answer)`` sentinel -
    matching legacy behaviour that prevents the evaluator prompt from
    receiving a blank ``CANDIDATE_ANSWER`` placeholder."""
    with patch(
        "app.engine.context.builder.load_prompt",
        side_effect=_fake_load_prompt,
    ):
        frame = build_context_frame_for_evaluator(
            dimension="coding",
            question="Q",
            rubric_points=[],
            answer="",  # empty
            quality_threshold=7.0,
            contract=None,
        )
    assert frame.payload["answer"] == "(empty answer)"
    # ``None`` contract normalises to the empty dict JSON.
    assert frame.payload["contract"] == "{}"
    assert frame.payload["rubric_points"] == "[]"


def test_verifier_builder_keeps_core_evidence_and_drops_planning_fields() -> None:
    frame = build_context_frame_for_verifier(
        dimension="system_design",
        question="Q",
        answer="A",
        contract={"must_cover": ["tradeoff"]},
        evaluator_report={
            "score": 8.2,
            "passed": True,
            "strengths": ["structured"],
            "weaknesses": ["thin evidence"],
            "rubric_coverage": {"tradeoff": "covered"},
            "acceptance_check_results": {
                "Names a tradeoff.": {
                    "verdict": "yes",
                    "evidence": ["used async queue to absorb spikes"],
                }
            },
            "recommended_next": "advance",
            "recommended_next_plan": "adaptive",
            "rationale": "sounds plausible",
        },
    )

    report = json.loads(frame.payload["evaluator_report"])

    assert report == {
        "score": 8.2,
        "passed": True,
        "rubric_coverage": {"tradeoff": "covered"},
        "acceptance_check_results": {
            "Names a tradeoff.": {
                "verdict": "yes",
                "evidence": ["used async queue to absorb spikes"],
            }
        },
    }
