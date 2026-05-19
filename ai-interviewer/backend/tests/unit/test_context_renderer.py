"""Unit tests for :func:`frame_to_generator_messages`.

The renderer is the last layer before ``call_chat``, so it is worth
isolating from both the builder and the live prompt templates. We stub
``render_prompt`` to confirm the exact kwarg mapping.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from app.engine.context import (
    ContextFrame,
    frame_to_evaluator_messages,
    frame_to_generator_messages,
)


def _full_payload(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "dimension": "system_design",
        "target_difficulty": "medium",
        "probe_intent": "architecture_challenge",
        "action": "{}",
        "refine_mode": "False",
        "job_title": "SWE",
        "job_level": "mid",
        "role_required_skills": "[]",
        "target_skills": "[]",
        "highlights": "[]",
        "resume_anchor": "{}",
        "user_material_boundary": "USER MATERIAL BOUNDARY",
        "history_section": "RECENT_QA = []",
        "retrieval": "RETRIEVAL",
        "question_seed": "",
        "candidate_anchor": "",
        "strategy": "STRATEGY",
        "skills": "(no relevant interview skills)",
        "avoid_patterns": "(no historical shallow patterns on this dimension)",
        "contract_hints": "{}",
        "self_intro_profile": "{}",
    }
    base.update(overrides)
    return base


def test_renderer_splits_static_and_dynamic_system() -> None:
    """PR-2b: with a non-empty dynamic layer the renderer emits three
    messages (static-cached, dynamic-uncached, user) so Anthropic can
    prompt-cache the static prefix without the strategy tail
    invalidating the cache on every session."""
    captured: dict[str, Any] = {}

    def fake_render(name: str, **kwargs: Any) -> str:
        captured["name"] = name
        captured["kwargs"] = kwargs
        return "USER_RENDERED"

    frame = ContextFrame(
        agent_role="generator",
        turn_idx=0,
        static_system="SYS",
        dynamic_system="DYN",
        payload=_full_payload(),
    )
    with patch(
        "app.engine.context.renderer.render_prompt",
        side_effect=fake_render,
    ):
        messages = frame_to_generator_messages(frame)

    assert len(messages) == 3
    assert messages[0].role == "system"
    assert messages[0].content == "SYS"
    assert messages[0].cache_control == "ephemeral"
    assert messages[1].role == "system"
    assert messages[1].content == "DYN"
    # Dynamic tail must NOT be cached: strategy index changes per
    # session, caching it would be a net loss.
    assert messages[1].cache_control is None
    assert messages[2].role == "user"
    assert messages[2].content == "USER_RENDERED"

    assert captured["name"] == "generator_task.md"
    for key in (
        "dimension",
        "target_difficulty",
        "probe_intent",
        "action",
        "refine_mode",
        "job_title",
        "job_level",
        "role_required_skills",
        "target_skills",
        "highlights",
        "resume_anchor",
        "user_material_boundary",
        "history_section",
        "retrieval",
        "question_seed",
        "candidate_anchor",
        "strategy",
        "skills",
        "avoid_patterns",
        "contract_hints",
        "self_intro_profile",
    ):
        assert captured["kwargs"][key] == frame.payload[key]


def test_renderer_omits_dynamic_when_empty() -> None:
    """Empty dynamic_system collapses the renderer back to (static, user)
    with the static block still marked cacheable."""
    frame = ContextFrame(
        agent_role="generator",
        turn_idx=0,
        static_system="SYS",
        dynamic_system="",  # empty
        payload=_full_payload(),
    )
    with patch(
        "app.engine.context.renderer.render_prompt",
        return_value="USER",
    ):
        messages = frame_to_generator_messages(frame)

    assert len(messages) == 2
    assert messages[0].role == "system"
    assert messages[0].content == "SYS"
    assert messages[0].cache_control == "ephemeral"
    assert messages[1].role == "user"


def test_generator_renderer_suppresses_empty_question_seed_prompt_section() -> None:
    """Vector/shadow mode keeps the structured seed prompt completely absent."""
    rendered = """Resume grounding rules:
- Prefer resume anchors.
- If STRUCTURED_QUESTION_SEED is non-empty, treat it as the primary reusable
  question skeleton for this turn. Use it to shape the scenario and contract,
  but do not reveal seed IDs, expected signals, anti-patterns, or hints.
- Treat TARGET_SKILLS as primary.
RETRIEVED_KNOWLEDGE =
RAG

STRUCTURED_QUESTION_SEED =

STRATEGY_MEMORY =
STRATEGY
"""
    frame = ContextFrame(
        agent_role="generator",
        turn_idx=0,
        static_system="SYS",
        dynamic_system="",
        payload=_full_payload(question_seed=""),
    )
    with patch(
        "app.engine.context.renderer.render_prompt",
        return_value=rendered,
    ):
        messages = frame_to_generator_messages(frame)

    user_text = messages[-1].content
    assert "STRUCTURED_QUESTION_SEED" not in user_text
    assert "primary reusable" not in user_text
    assert "RETRIEVED_KNOWLEDGE" in user_text
    assert "STRATEGY_MEMORY" in user_text


def test_generator_renderer_suppresses_empty_candidate_anchor_prompt_section() -> None:
    rendered = """Resume grounding rules:
- If CANDIDATE_ANCHOR is non-empty, use it to adapt the structured seed
  to the candidate's project and job skills, but do not reveal internal
  fit scores, seed IDs, expected signals, anti-patterns, or hints.
RETRIEVED_KNOWLEDGE =
RAG

STRUCTURED_QUESTION_SEED =
Seed: cache consistency

CANDIDATE_ANCHOR =

STRATEGY_MEMORY =
STRATEGY
"""
    frame = ContextFrame(
        agent_role="generator",
        turn_idx=0,
        static_system="SYS",
        dynamic_system="",
        payload=_full_payload(question_seed="Seed: cache consistency", candidate_anchor=""),
    )
    with patch(
        "app.engine.context.renderer.render_prompt",
        return_value=rendered,
    ):
        messages = frame_to_generator_messages(frame)

    user_text = messages[-1].content
    assert "CANDIDATE_ANCHOR" not in user_text
    assert "fit scores" not in user_text
    assert "STRUCTURED_QUESTION_SEED" in user_text


def test_generator_renderer_keeps_non_empty_question_seed_prompt_section() -> None:
    rendered = """STRUCTURED_QUESTION_SEED =
Seed: cache consistency

CANDIDATE_ANCHOR =
Project: Inventory

STRATEGY_MEMORY =
STRATEGY
"""
    frame = ContextFrame(
        agent_role="generator",
        turn_idx=0,
        static_system="SYS",
        dynamic_system="",
        payload=_full_payload(
            question_seed="Seed: cache consistency",
            candidate_anchor="Project: Inventory",
        ),
    )
    with patch(
        "app.engine.context.renderer.render_prompt",
        return_value=rendered,
    ):
        messages = frame_to_generator_messages(frame)

    assert "STRUCTURED_QUESTION_SEED" in messages[-1].content
    assert "Seed: cache consistency" in messages[-1].content
    assert "CANDIDATE_ANCHOR" in messages[-1].content
    assert "Project: Inventory" in messages[-1].content


def test_renderer_rejects_wrong_role() -> None:
    frame = ContextFrame(
        agent_role="evaluator",  # wrong role
        turn_idx=0,
        static_system="SYS",
        payload=_full_payload(),
    )
    with pytest.raises(ValueError, match="agent_role='generator'"):
        frame_to_generator_messages(frame)


def test_renderer_rejects_missing_payload_keys() -> None:
    frame = ContextFrame(
        agent_role="generator",
        turn_idx=0,
        static_system="SYS",
        payload={"dimension": "only_one_key"},  # intentionally incomplete
    )
    with pytest.raises(KeyError, match="missing Generator keys"):
        frame_to_generator_messages(frame)


def _full_evaluator_payload(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "dimension": "coding",
        "question": "Design a rate limiter.",
        "contract": "{}",
        "rubric_points": "[]",
        "answer": "A",
        "threshold": 7.5,
        "user_material_boundary": "USER MATERIAL BOUNDARY",
        "video_signals": "",
    }
    base.update(overrides)
    return base


def test_evaluator_renderer_builds_two_messages() -> None:
    captured: dict[str, Any] = {}

    def fake_render(name: str, **kwargs: Any) -> str:
        captured["name"] = name
        captured["kwargs"] = kwargs
        return "EVAL_RENDERED"

    frame = ContextFrame(
        agent_role="evaluator",
        turn_idx=0,
        static_system="SYS",
        dynamic_system="",  # Evaluator never carries a dynamic layer.
        payload=_full_evaluator_payload(),
    )
    with patch(
        "app.engine.context.renderer.render_prompt",
        side_effect=fake_render,
    ):
        messages = frame_to_evaluator_messages(frame)

    assert len(messages) == 2
    assert messages[0].role == "system"
    # No dynamic layer => system is exactly the static prefix, no
    # trailing "\n\n".
    assert messages[0].content == "SYS"
    # PR-2b: the evaluator's static prefix is cacheable too.
    assert messages[0].cache_control == "ephemeral"
    assert messages[1].role == "user"
    assert messages[1].content == "EVAL_RENDERED"

    assert captured["name"] == "evaluator_task.md"
    for key in (
        "dimension",
        "question",
        "contract",
        "rubric_points",
        "answer",
        "threshold",
        "user_material_boundary",
    ):
        assert captured["kwargs"][key] == frame.payload[key]


def test_evaluator_renderer_rejects_wrong_role() -> None:
    frame = ContextFrame(
        agent_role="generator",  # wrong role
        turn_idx=0,
        static_system="SYS",
        payload=_full_evaluator_payload(),
    )
    with pytest.raises(ValueError, match="agent_role='evaluator'"):
        frame_to_evaluator_messages(frame)


def test_evaluator_renderer_rejects_missing_keys() -> None:
    frame = ContextFrame(
        agent_role="evaluator",
        turn_idx=0,
        static_system="SYS",
        payload={"dimension": "only_one"},
    )
    with pytest.raises(KeyError, match="missing Evaluator keys"):
        frame_to_evaluator_messages(frame)
