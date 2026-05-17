"""Integration tests for the skill-injection slot in ``ask_question_node``.

Verifies that :func:`_step_retrieve_strategy` (which bundles the
skill retrieval for minimal churn on the plan step list) correctly:

1. Skips skill retrieval when ``enable_skill_injection`` is OFF
   (the default). The ``ctx['skill_block']`` must stay at the
   placeholder the node seeded it with.
2. Engages skill retrieval when the flag is ON and surfaces the
   rendered block for matching skills.
3. Degrades to the placeholder when the flag is ON but the
   ``knowledge/skills/`` directory contains nothing matching the
   current dimension.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core.settings import Settings
from app.engine.workflow.nodes import ask_question as ask_question_module
from app.memory import skill_store

_MATCHING_SKILL = """\
---
name: System Design Scale Reasoning
description: Force one concrete failure mode per answer.
dimensions: [system_design]
job_levels: [senior]
---
Probe for one concrete failure mode and one quantified scale
argument in every answer.
"""


def _stub_settings(
    *, enable_skill_injection: bool, skill_retrieval_limit: int = 3
) -> SimpleNamespace:
    """Minimal settings stub for the skill-injection branch."""
    return SimpleNamespace(
        enable_skill_injection=enable_skill_injection,
        skill_retrieval_limit=skill_retrieval_limit,
    )


@pytest.fixture
def skills_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Path:
    """Isolate the skills directory for the duration of a single test."""
    root = tmp_path / "skills"
    monkeypatch.setattr(skill_store, "_skills_dir", lambda: root)
    return root


def _seed_strategy_retrieval(monkeypatch: pytest.MonkeyPatch) -> None:
    """Short-circuit the strategy retrieval so the test focuses on the
    skill branch. Strategy retrieval reads files from disk and the
    strategy directory is orthogonal to what this test cares about.
    """
    monkeypatch.setattr(
        ask_question_module,
        "retrieve_strategies",
        lambda **_: [],
    )
    monkeypatch.setattr(
        ask_question_module,
        "format_strategies_for_prompt",
        lambda entries: "(no relevant strategy memories)",
    )


def _build_state() -> dict[str, object]:
    return {
        "job_spec": {"level": "senior", "title": "Senior Backend"},
    }


def _run_step(
    *,
    settings: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, object]:
    _seed_strategy_retrieval(monkeypatch)
    monkeypatch.setattr(
        ask_question_module, "get_settings", lambda: settings
    )
    state = _build_state()
    ctx: dict[str, object] = {
        "dimension": "system_design",
        "skill_block": "(no relevant interview skills)",
    }
    ask_question_module._step_retrieve_strategy(state, ctx)
    return ctx


def test_flag_off_leaves_skill_block_untouched(
    skills_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (skills_root / "a.md").parent.mkdir(parents=True, exist_ok=True)
    (skills_root / "a.md").write_text(_MATCHING_SKILL, encoding="utf-8")

    ctx = _run_step(
        settings=_stub_settings(enable_skill_injection=False),
        monkeypatch=monkeypatch,
    )
    assert ctx["skill_block"] == "(no relevant interview skills)"


def test_skill_injection_default_is_enabled() -> None:
    assert Settings(_env_file=None).enable_skill_injection is True


def test_flag_on_with_matching_skill_injects_rendered_block(
    skills_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    skills_root.mkdir(parents=True, exist_ok=True)
    (skills_root / "a.md").write_text(_MATCHING_SKILL, encoding="utf-8")

    ctx = _run_step(
        settings=_stub_settings(enable_skill_injection=True),
        monkeypatch=monkeypatch,
    )
    block = str(ctx["skill_block"])
    assert "System Design Scale Reasoning" in block
    assert "dims=system_design" in block


def test_flag_on_with_empty_dir_falls_back_to_placeholder(
    skills_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # No skill files at all; retrieve_skills returns empty list;
    # build_skills_block maps that to the placeholder string.
    ctx = _run_step(
        settings=_stub_settings(enable_skill_injection=True),
        monkeypatch=monkeypatch,
    )
    assert ctx["skill_block"] == "(no relevant interview skills)"


def test_flag_on_respects_skill_retrieval_limit(
    skills_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    skills_root.mkdir(parents=True, exist_ok=True)
    for i in range(4):
        (skills_root / f"s{i}.md").write_text(
            f"---\nname: Skill {i}\ndescription: d{i}.\n"
            f"dimensions: [system_design]\n"
            f"job_levels: [senior]\n---\nBody {i}",
            encoding="utf-8",
        )

    ctx = _run_step(
        settings=_stub_settings(
            enable_skill_injection=True, skill_retrieval_limit=2
        ),
        monkeypatch=monkeypatch,
    )
    block = str(ctx["skill_block"])
    # Two bullets rendered (``[Skill 1] ... [Skill 2] ...``); a third
    # would show as ``[Skill 3]`` and it must NOT.
    assert "[Skill 1]" in block
    assert "[Skill 2]" in block
    assert "[Skill 3]" not in block
