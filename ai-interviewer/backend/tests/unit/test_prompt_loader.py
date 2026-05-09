"""Tests for the frontmatter-aware prompt loader."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.engine.agents.prompts import loader as prompt_loader


def _write_tmp_prompt(tmp_path: Path, name: str, content: str) -> Path:
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return p


@pytest.fixture
def patched_prompt_dir(tmp_path, monkeypatch):
    """Redirect the loader at a throwaway directory so tests don't
    depend on the real prompt files in the repo."""
    monkeypatch.setattr(prompt_loader, "_PROMPT_DIR", tmp_path)
    prompt_loader.clear_cache()
    yield tmp_path
    prompt_loader.clear_cache()


def test_render_prompt_happy_path(patched_prompt_dir: Path) -> None:
    _write_tmp_prompt(
        patched_prompt_dir,
        "greet.md",
        """---
name: greet
version: v1
description: hello world
variables:
  - subject
---
Hello, {subject}!
""",
    )
    out = prompt_loader.render_prompt("greet.md", subject="world")
    assert out.strip() == "Hello, world!"


def test_render_prompt_missing_variable(patched_prompt_dir: Path) -> None:
    _write_tmp_prompt(
        patched_prompt_dir,
        "need_two.md",
        """---
name: need_two
version: v1
variables:
  - a
  - b
---
{a} {b}
""",
    )
    with pytest.raises(prompt_loader.PromptVariableMissing) as exc:
        prompt_loader.render_prompt("need_two.md", a="x")
    assert exc.value.missing == ["b"]
    assert "need_two.md" in str(exc.value)


def test_render_prompt_ignores_extra_kwargs(patched_prompt_dir: Path) -> None:
    _write_tmp_prompt(
        patched_prompt_dir,
        "one_var.md",
        """---
name: one_var
version: v1
variables:
  - x
---
value = {x}
""",
    )
    out = prompt_loader.render_prompt("one_var.md", x="1", y="ignored")
    assert "value = 1" in out
    assert "ignored" not in out


def test_load_prompt_strips_frontmatter(patched_prompt_dir: Path) -> None:
    _write_tmp_prompt(
        patched_prompt_dir,
        "plain.md",
        """---
name: plain
version: v1
---
Body line 1
Body line 2
""",
    )
    body = prompt_loader.load_prompt("plain.md")
    assert "Body line 1" in body
    assert "---" not in body
    assert "name: plain" not in body


def test_load_prompt_without_frontmatter_is_passthrough(
    patched_prompt_dir: Path,
) -> None:
    _write_tmp_prompt(patched_prompt_dir, "nomatter.md", "Just text.\n")
    body = prompt_loader.load_prompt("nomatter.md")
    assert body == "Just text.\n"


def test_get_prompt_meta_parses_variables(patched_prompt_dir: Path) -> None:
    _write_tmp_prompt(
        patched_prompt_dir,
        "meta.md",
        """---
name: meta
version: v2
description: demo description
variables:
  - foo
  - bar
---
body
""",
    )
    meta = prompt_loader.get_prompt_meta("meta.md")
    assert meta.name == "meta"
    assert meta.version == "v2"
    assert meta.description == "demo description"
    assert meta.variables == ["foo", "bar"]


def test_get_prompt_meta_inline_list(patched_prompt_dir: Path) -> None:
    _write_tmp_prompt(
        patched_prompt_dir,
        "inline.md",
        """---
name: inline
version: v1
variables: [alpha, beta, gamma]
---
body
""",
    )
    meta = prompt_loader.get_prompt_meta("inline.md")
    assert meta.variables == ["alpha", "beta", "gamma"]


def test_prompt_not_found(patched_prompt_dir: Path) -> None:
    with pytest.raises(prompt_loader.PromptNotFound):
        prompt_loader.render_prompt("does_not_exist.md", x=1)


def test_render_prompt_with_brace_escaping(patched_prompt_dir: Path) -> None:
    _write_tmp_prompt(
        patched_prompt_dir,
        "json.md",
        """---
name: json
version: v1
variables:
  - key
---
Reply as JSON: {{ "k": "{key}" }}
""",
    )
    out = prompt_loader.render_prompt("json.md", key="v")
    assert '{ "k": "v" }' in out


def test_no_variables_declared_still_renders(patched_prompt_dir: Path) -> None:
    """A prompt with no declared variables is served as-is even when
    kwargs are supplied — we don't force validation when there's
    nothing to validate."""
    _write_tmp_prompt(
        patched_prompt_dir,
        "static.md",
        """---
name: static
version: v1
---
Static body.
""",
    )
    out = prompt_loader.render_prompt("static.md")
    assert out.strip() == "Static body."


def test_real_prompt_files_have_valid_frontmatter() -> None:
    """Smoke test: the 4 real prompt files the agents depend on all
    parse without errors and declare at least one variable each."""
    for name in (
        "generator_task.md",
        "evaluator_task.md",
        "verifier_task.md",
        "contract_negotiate.md",
    ):
        meta = prompt_loader.get_prompt_meta(name)
        assert meta.name, f"{name} missing frontmatter name"
        assert meta.version, f"{name} missing frontmatter version"
        assert meta.variables, f"{name} must declare at least one variable"


def test_render_generator_task_end_to_end() -> None:
    """Ensure the real generator_task prompt renders with all declared
    variables. Regression guard: if someone adds a variable to the file
    without updating ``generator.py``, this test breaks."""
    out = prompt_loader.render_prompt(
        "generator_task.md",
        dimension="system_design",
        target_difficulty="medium",
        probe_intent="architecture_challenge",
        action="{}",
        refine_mode="False",
        job_title="SWE",
        job_level="mid",
        role_required_skills="[]",
        target_skills="[]",
        highlights="[]",
        resume_anchor="{}",
        self_intro_profile="{}",
        user_material_boundary="USER_MATERIAL_BOUNDARY",
        history_section="RECENT_QA = []",
        retrieval="(no docs)",
        strategy="(no memories)",
        skills="(no relevant interview skills)",
        avoid_patterns="(no historical shallow patterns on this dimension)",
        contract_hints="{}",
    )
    assert "system_design" in out
    assert "TARGET_DIFFICULTY = medium" in out
    assert "PROBE_INTENT = architecture_challenge" in out
    # PLAN_SKILL_INJECTION: the new ``skills`` variable renders into
    # the ``INTERVIEW_SKILLS`` block — regression-guard it here so a
    # future prompt edit cannot silently drop the slot.
    assert "INTERVIEW_SKILLS =" in out
    # PLAN_DRIFT_RAG_FEEDBACK: the new ``avoid_patterns`` variable
    # renders into the ``AVOID_PATTERNS`` block; same regression-guard.
    assert "AVOID_PATTERNS =" in out
    assert "简体中文" in out
    assert "Do not output English" in out


def test_evaluator_task_requires_candidate_visible_feedback_in_chinese() -> None:
    out = prompt_loader.render_prompt(
        "evaluator_task.md",
        dimension="system_design",
        question="Q",
        contract="{}",
        rubric_points="[]",
        answer="A",
        threshold=7.0,
        user_material_boundary="USER_MATERIAL_BOUNDARY",
        video_signals="",
    )

    assert "strengths" in out
    assert "weaknesses" in out
    assert "rationale" in out
    assert "\u7b80\u4f53\u4e2d\u6587" in out
    assert "Do not write English feedback" in out


def test_generator_task_documents_quick_review_positioning() -> None:
    out = prompt_loader.render_prompt(
        "generator_task.md",
        dimension="system_design",
        target_difficulty="medium",
        probe_intent="general",
        action='{"id":"plan_quick_review","plan_template":"quick_review"}',
        refine_mode="False",
        job_title="SWE",
        job_level="mid",
        role_required_skills="[]",
        target_skills="[]",
        highlights="[]",
        resume_anchor="{}",
        self_intro_profile="{}",
        user_material_boundary="USER_MATERIAL_BOUNDARY",
        history_section="RECENT_QA = []",
        retrieval="(no docs)",
        strategy="(no memories)",
        skills="(no relevant interview skills)",
        avoid_patterns="(no historical shallow patterns on this dimension)",
        contract_hints="{}",
    )

    assert "Quick Review positioning" in out
    assert "fast signal check, not a hint" in out
    assert "AI interviewer stance" in out
