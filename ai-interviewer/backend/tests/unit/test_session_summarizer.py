"""Tests for the LLM-backed session summariser and its integration
with ``compress_context_node``."""
from __future__ import annotations

import json
from typing import Any

import pytest

from app.engine.agents import session_summarizer as ss
from app.engine.workflow.nodes import compress_context as cc


def _turn(turn_idx: int, dim: str, score: float) -> dict[str, Any]:
    return {
        "turn_idx": turn_idx,
        "dimension": dim,
        "question": f"q{turn_idx}",
        "answer": f"a{turn_idx}",
        "selected_action": "plan_adaptive",
        "evaluation": {
            "score": score,
            "passed": score >= 7.0,
            "strengths": [f"s{turn_idx}"],
            "weaknesses": [f"w{turn_idx}"],
            "rubric_coverage": {"depth": "covered"},
        },
    }


def test_format_summary_for_prompt_plain_string_passthrough() -> None:
    raw = "[system_design]\n  Turns: 2 | Scores: 7.0, 8.0\n"
    assert ss.format_summary_for_prompt(raw) == raw


def test_format_summary_for_prompt_structured_json_is_expanded() -> None:
    payload = {
        "by_dimension": {
            "system_design": {
                "progression": "Started cleanly, wobbled under deep probe.",
                "key_evidence": ["Redis for idempotency", "Lua atomicity"],
                "gaps": ["Did not mention split-brain handling"],
            }
        },
        "overall_trajectory": "Uneven, strong early, fragile later.",
        "summary_version": 2,
    }
    rendered = ss.format_summary_for_prompt(json.dumps(payload))
    assert "Overall: Uneven" in rendered
    assert "[system_design]" in rendered
    assert "Progression: Started cleanly" in rendered
    assert "- Redis for idempotency" in rendered
    assert "- Did not mention split-brain handling" in rendered


def test_format_summary_for_prompt_invalid_json_falls_back() -> None:
    not_json = "{not really json"
    assert ss.format_summary_for_prompt(not_json) == not_json


def test_validate_rejects_wrong_shape() -> None:
    assert ss._validate({"wrong": 1}) is None
    assert ss._validate([]) is None
    assert ss._validate({"by_dimension": {}}) is None


def test_summarise_session_empty_turns_returns_existing(monkeypatch) -> None:
    called: list[bool] = []
    monkeypatch.setattr(
        "app.engine.agents.session_summarizer.call_chat",
        lambda *a, **kw: called.append(True) or "",
    )
    out = ss.summarise_session(
        job_title="SWE",
        job_level="mid",
        new_turns=[],
        existing_summary="EXISTING",
    )
    assert out == "EXISTING"
    assert not called


def test_summarise_session_uses_llm_path(monkeypatch) -> None:
    """Happy path: provider returns valid JSON, we serialise it back."""
    payload = {
        "by_dimension": {
            "system_design": {
                "progression": "fine start",
                "key_evidence": ["redis"],
                "gaps": ["partition"],
            }
        },
        "overall_trajectory": "ok",
        "summary_version": 2,
    }

    def fake_call(*_args, **_kwargs):
        return json.dumps(payload)

    monkeypatch.setattr(
        "app.engine.agents.session_summarizer.call_chat", fake_call
    )

    out = ss.summarise_session(
        job_title="SWE",
        job_level="senior",
        new_turns=[_turn(0, "system_design", 7.0)],
        existing_summary="",
    )
    assert isinstance(out, str)
    parsed = json.loads(out)
    assert parsed["by_dimension"]["system_design"]["key_evidence"] == ["redis"]
    assert parsed["summary_version"] == 2


def test_summarise_session_schema_failure_preserves_existing(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.engine.agents.session_summarizer.call_chat",
        lambda *a, **kw: json.dumps({"totally": "wrong"}),
    )
    out = ss.summarise_session(
        job_title="SWE",
        job_level="mid",
        new_turns=[_turn(0, "d", 7.0)],
        existing_summary="OLD",
    )
    assert out == "OLD"


def test_summarise_session_llm_raises_preserves_existing(monkeypatch) -> None:
    def boom(*_a, **_kw):
        raise RuntimeError("provider down")

    monkeypatch.setattr(
        "app.engine.agents.session_summarizer.call_chat", boom
    )
    out = ss.summarise_session(
        job_title="SWE",
        job_level="mid",
        new_turns=[_turn(0, "d", 7.0)],
        existing_summary="OLD",
    )
    assert out == "OLD"


def test_compress_context_no_longer_updates_qa_summary() -> None:
    """compress_context is now turn-finalize only; ask_question owns the
    prompt-facing history projection."""
    state = {
        "qa_history": [
            _turn(0, "dim_a", 7.0),
            _turn(1, "dim_a", 6.5),
            _turn(2, "dim_b", 8.0),
            _turn(3, "dim_b", 7.5),
        ],
        "qa_summary": "",
        "qa_summary_through_turn": -1,
    }
    out = cc.compress_context_node(state)  # type: ignore[arg-type]
    assert "qa_summary" not in out
    assert "qa_summary_through_turn" not in out


def test_compress_context_llm_mode_does_not_invoke_summariser(monkeypatch) -> None:
    calls: list[int] = []

    monkeypatch.setattr(
        "app.engine.agents.session_summarizer.call_chat",
        lambda *a, **kw: calls.append(1) or "{}",
    )

    state = {
        "runtime_config": {"summary_mode": "llm"},
        "qa_history": [
            _turn(0, "dim_a", 7.0),
            _turn(1, "dim_a", 6.5),
            _turn(2, "dim_a", 8.0),
        ],
        "qa_summary": "",
        "qa_summary_through_turn": -1,
        "job_spec": {"title": "SWE", "level": "mid"},
    }
    out = cc.compress_context_node(state)  # type: ignore[arg-type]
    assert calls == []
    assert "qa_summary" not in out


def test_compress_context_auto_mode_does_not_invoke_summariser(monkeypatch) -> None:
    calls: list[int] = []

    def fake_call(*_a, **_kw):
        calls.append(1)
        return json.dumps(
            {
                "by_dimension": {
                    "d": {"progression": "p", "key_evidence": [], "gaps": []}
                },
                "overall_trajectory": "",
                "summary_version": 1,
            }
        )

    monkeypatch.setattr(
        "app.engine.agents.session_summarizer.call_chat", fake_call
    )

    short_history = [_turn(i, "d", 7.0) for i in range(5)]
    state_short = {
        "runtime_config": {"summary_mode": "auto"},
        "qa_history": short_history,
        "qa_summary": "",
        "qa_summary_through_turn": -1,
        "job_spec": {},
    }
    cc.compress_context_node(state_short)  # type: ignore[arg-type]
    assert calls == []

    long_history = [_turn(i, "d", 7.0) for i in range(6)]
    state_long = {
        "runtime_config": {"summary_mode": "auto"},
        "qa_history": long_history,
        "qa_summary": "",
        "qa_summary_through_turn": -1,
        "job_spec": {},
    }
    cc.compress_context_node(state_long)  # type: ignore[arg-type]
    assert calls == []


def test_compress_context_ignores_llm_failure_because_no_hot_path_summary(
    monkeypatch,
) -> None:
    """The summarizer can still exist as a standalone helper, but it is
    no longer called from the interview hot path."""

    def boom(*_a, **_kw):
        raise RuntimeError("provider down")

    monkeypatch.setattr(
        "app.engine.agents.session_summarizer.call_chat", boom
    )

    state = {
        "runtime_config": {"summary_mode": "llm"},
        "qa_history": [_turn(i, "d", 7.0) for i in range(4)],
        "qa_summary": "PRIOR",
        "qa_summary_through_turn": -1,
        "job_spec": {},
    }
    out = cc.compress_context_node(state)  # type: ignore[arg-type]
    assert "qa_summary" not in out
    assert "qa_summary_through_turn" not in out
