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


def test_compress_context_deterministic_default() -> None:
    """Default mode must behave exactly like the pre-rollout version."""
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
    assert "qa_summary" in out
    summary = out["qa_summary"]
    # Deterministic summary is plain text grouped by dimension.
    assert "[dim_a]" in summary
    assert "Turns:" in summary


def test_compress_context_llm_mode_invokes_summariser(monkeypatch) -> None:
    payload = {
        "by_dimension": {
            "dim_a": {
                "progression": "p",
                "key_evidence": ["e"],
                "gaps": ["g"],
            }
        },
        "overall_trajectory": "t",
        "summary_version": 2,
    }
    monkeypatch.setattr(
        "app.engine.agents.session_summarizer.call_chat",
        lambda *a, **kw: json.dumps(payload),
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
    assert "qa_summary" in out
    stored = json.loads(out["qa_summary"])
    assert stored["by_dimension"]["dim_a"]["key_evidence"] == ["e"]


def test_compress_context_auto_upgrades_above_threshold(monkeypatch) -> None:
    """``auto`` stays deterministic below threshold, LLM above."""
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

    short_history = [_turn(i, "d", 7.0) for i in range(cc.AUTO_LLM_THRESHOLD - 1)]
    state_short = {
        "runtime_config": {"summary_mode": "auto"},
        "qa_history": short_history,
        "qa_summary": "",
        "qa_summary_through_turn": -1,
        "job_spec": {},
    }
    cc.compress_context_node(state_short)  # type: ignore[arg-type]
    assert calls == []  # deterministic path

    long_history = [_turn(i, "d", 7.0) for i in range(cc.AUTO_LLM_THRESHOLD)]
    state_long = {
        "runtime_config": {"summary_mode": "auto"},
        "qa_history": long_history,
        "qa_summary": "",
        "qa_summary_through_turn": -1,
        "job_spec": {},
    }
    cc.compress_context_node(state_long)  # type: ignore[arg-type]
    assert calls == [1]  # LLM path triggered once


def test_compress_context_llm_failure_degrades_to_deterministic(
    monkeypatch,
) -> None:
    """If the LLM summariser raises, compress_context must keep the
    interview alive by persisting the prior summary rather than raising."""

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
    # The node should still advance the cursor (so we don't retry the
    # same turns forever) but keep the prior summary unchanged.
    assert out["qa_summary"] == "PRIOR"
    assert out["qa_summary_through_turn"] >= 0


@pytest.mark.parametrize(
    "mode,expected",
    [
        ("deterministic", "deterministic"),
        ("llm", "llm"),
        ("auto", "auto"),
        ("garbage", "deterministic"),
        (None, "deterministic"),
    ],
)
def test_resolve_summary_mode(mode: Any, expected: str) -> None:
    rc = {} if mode is None else {"summary_mode": mode}
    state = {"runtime_config": rc}
    assert cc._resolve_summary_mode(state) == expected  # type: ignore[arg-type]
