"""Tests for :mod:`app.memory.skill_store`.

Covers the three layers of the skill registry:

1. Frontmatter parsing (``SkillEntry`` shape coming off disk).
2. Relevance scoring (``retrieve_skills`` filters + ranking).
3. Prompt rendering (``build_skills_block`` / ``build_skills_index``).

The tests pin file-system behaviour by monkey-patching ``_skills_dir``
so they can run against a ``tmp_path`` sandbox and never touch the
real ``knowledge/skills/`` directory.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.memory import skill_store

_SKILL_CARD_A = """\
---
id: senior_backend_ownership
name: Senior Backend Ownership
description: Probe ownership, not buzzwords.
status: active
priority: 7
direction_tags: [internet_tech]
role_tags: [java_backend, architect]
dimensions: [leadership, system_design]
job_levels: [senior, staff]
probe_intents: [architecture_challenge]
failure_categories: [generic_storytelling]
---
Body A goes here.
Longer paragraph that explains the probe strategy in detail so the
Generator can follow.
"""

_SKILL_CARD_B = """\
---
name: Junior Algorithm Warm-up
description: Keep first-turn coding questions approachable.
dimensions: [coding]
job_levels: [junior]
---
Body B describes a warm-up strategy.
"""

_SKILL_CARD_UNIVERSAL = """\
---
name: Ask for Concrete Example
description: Always demand at least one concrete example.
---
Applies everywhere, regardless of dimension or level.
"""


def _write_skill(root: Path, name: str, body: str) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    path = root / name
    path.write_text(body, encoding="utf-8")
    return path


@pytest.fixture
def skills_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Path:
    """Return a ``tmp_path / 'skills'`` root that ``skill_store`` sees.

    Uses ``monkeypatch.setattr`` on the module-local ``_skills_dir``
    so the tests never read the real ``knowledge/skills/`` directory
    and cannot accidentally mutate it.
    """
    root = tmp_path / "skills"
    monkeypatch.setattr(skill_store, "_skills_dir", lambda: root)
    return root


def test_list_skills_empty_when_dir_missing(
    skills_root: Path,
) -> None:
    """No directory → empty list (do not raise, do not create)."""
    assert not skills_root.exists()
    assert skill_store.list_skills() == []


def test_list_skills_parses_frontmatter(skills_root: Path) -> None:
    _write_skill(skills_root, "a.md", _SKILL_CARD_A)
    entries = skill_store.list_skills()

    assert len(entries) == 1
    e = entries[0]
    assert e.name == "Senior Backend Ownership"
    assert e.description == "Probe ownership, not buzzwords."
    assert e.id == "senior_backend_ownership"
    assert e.status == "active"
    assert e.priority == 7
    assert e.direction_tags == ["internet_tech"]
    assert e.role_tags == ["java_backend", "architect"]
    assert e.dimensions == ["leadership", "system_design"]
    assert e.job_levels == ["senior", "staff"]
    assert e.probe_intents == ["architecture_challenge"]
    assert e.failure_categories == ["generic_storytelling"]
    assert "Body A goes here." in e.body
    # Frontmatter must be stripped from the body.
    assert "---" not in e.body.splitlines()[0]


def test_list_skills_ignores_index_file(skills_root: Path) -> None:
    """``SKILL.md`` is the navigation index, not a skill card."""
    _write_skill(skills_root, "SKILL.md", "# SKILL index file")
    _write_skill(skills_root, "a.md", _SKILL_CARD_A)
    entries = skill_store.list_skills()
    assert [e.path.name for e in entries] == ["a.md"]


def test_retrieve_skills_scores_dimension_match_highest(
    skills_root: Path,
) -> None:
    _write_skill(skills_root, "a.md", _SKILL_CARD_A)
    _write_skill(skills_root, "b.md", _SKILL_CARD_B)
    _write_skill(skills_root, "u.md", _SKILL_CARD_UNIVERSAL)

    entries = skill_store.retrieve_skills(
        dimension="system_design",
        job_level="senior",
        direction_tags=["internet_tech"],
        role_tags=["java_backend"],
    )

    # "Senior Backend Ownership" matches both dimension (+2) and
    # level (+1) -> score 3 — ranks first.
    # Universal ("u.md") matches "no dimensions → +1" -> score 1.
    # "Junior Algorithm Warm-up" matches nothing (wrong dim, wrong
    # level) -> score 0 → dropped.
    names = [e.name for e in entries]
    assert names == [
        "Senior Backend Ownership",
        "Ask for Concrete Example",
    ]
    assert entries[0].match_score > entries[1].match_score
    assert "role_tag:java_backend" in entries[0].match_reasons
    assert "direction_tag:internet_tech" in entries[0].match_reasons


def test_retrieve_skills_returns_empty_when_nothing_matches(
    skills_root: Path,
) -> None:
    _write_skill(skills_root, "b.md", _SKILL_CARD_B)
    entries = skill_store.retrieve_skills(
        dimension="system_design", job_level="senior"
    )
    assert entries == []


def test_retrieve_skills_filters_inactive_and_role_mismatch(
    skills_root: Path,
) -> None:
    _write_skill(
        skills_root,
        "inactive.md",
        "---\n"
        "name: Draft Card\n"
        "status: draft\n"
        "dimensions: [system_design]\n"
        "job_levels: [senior]\n"
        "---\nDraft body",
    )
    _write_skill(
        skills_root,
        "frontend.md",
        "---\n"
        "name: Frontend Only\n"
        "status: active\n"
        "direction_tags: [internet_tech]\n"
        "role_tags: [frontend_web]\n"
        "dimensions: [system_design]\n"
        "job_levels: [senior]\n"
        "---\nFrontend body",
    )

    entries = skill_store.retrieve_skills(
        dimension="system_design",
        job_level="senior",
        direction_tags=["internet_tech"],
        role_tags=["java_backend"],
    )

    assert entries == []


def test_retrieve_skills_ranks_probe_and_failure_matches(
    skills_root: Path,
) -> None:
    _write_skill(
        skills_root,
        "generic.md",
        "---\n"
        "id: generic_metric_probe\n"
        "name: Generic Metric Probe\n"
        "priority: 4\n"
        "---\nGeneric body",
    )
    _write_skill(
        skills_root,
        "specific.md",
        "---\n"
        "id: java_incident_debugging\n"
        "name: Java Incident Debugging\n"
        "priority: 1\n"
        "direction_tags: [internet_tech]\n"
        "role_tags: [java_backend]\n"
        "dimensions: [problem_solving]\n"
        "job_levels: [senior]\n"
        "probe_intents: [debugging_probe]\n"
        "failure_categories: [root_cause_missing]\n"
        "---\nSpecific body",
    )

    entries = skill_store.retrieve_skills(
        dimension="problem_solving",
        job_level="senior",
        direction_tags=["internet_tech"],
        role_tags=["java_backend"],
        probe_intent="debugging_probe",
        failure_categories=["root_cause_missing"],
    )

    assert [entry.id for entry in entries] == [
        "java_incident_debugging",
        "generic_metric_probe",
    ]
    assert "probe_intent:debugging_probe" in entries[0].match_reasons
    assert "failure_category:root_cause_missing" in entries[0].match_reasons


def test_retrieve_skills_with_llm_selector_filters_keyword_set(
    skills_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``use_llm_selector=True`` must pipe the keyword-filtered
    candidates through :func:`select_memories_with_llm`; the final
    return order follows the LLM reply rather than the keyword
    score order. LLM is stubbed so the test stays fast and
    deterministic.
    """
    # Three matching skills; keyword score puts them in scan order.
    for i in range(3):
        _write_skill(
            skills_root,
            f"skill_{i}.md",
            f"---\n"
            f"name: Skill {i}\n"
            f"description: desc {i}.\n"
            f"dimensions: [system_design]\n"
            f"job_levels: [senior]\n"
            f"---\nBody {i}",
        )

    import app.memory.skill_store as sstore

    # LLM picks {skill_2, skill_0} in a DIFFERENT order than keyword
    # would have produced — the test proves the LLM reply steers the
    # final selection.
    monkeypatch.setattr(
        sstore,
        "_skills_dir",
        lambda: skills_root,
    )

    def fake_select(candidates, context, *, top_n):
        return ["skill_2.md", "skill_0.md"]

    # The skill_store imports ``select_memories_with_llm`` locally inside
    # the function; patch at the import path used by that function.
    monkeypatch.setattr(
        "app.memory.llm_selector.select_memories_with_llm",
        fake_select,
    )

    entries = skill_store.retrieve_skills(
        dimension="system_design",
        job_level="senior",
        limit=5,
        use_llm_selector=True,
    )
    names = [e.path.name for e in entries]
    assert names == ["skill_2.md", "skill_0.md"]


def test_retrieve_skills_llm_selector_fallback_on_none(
    skills_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """LLM selector returning ``None`` (provider failure / unparsable
    reply) must NOT drop the caller into an empty list — fall back
    to the keyword top-N untouched."""
    _write_skill(skills_root, "a.md", _SKILL_CARD_A)

    monkeypatch.setattr(
        "app.memory.llm_selector.select_memories_with_llm",
        lambda *args, **kwargs: None,
    )

    entries = skill_store.retrieve_skills(
        dimension="system_design",
        job_level="senior",
        limit=3,
        use_llm_selector=True,
        direction_tags=["internet_tech"],
        role_tags=["java_backend"],
    )
    assert [e.path.name for e in entries] == ["a.md"]


def test_retrieve_skills_respects_limit(skills_root: Path) -> None:
    # Seed 5 dimension-matching skill cards; limit=2 keeps top 2.
    for i in range(5):
        _write_skill(
            skills_root,
            f"skill_{i}.md",
            f"---\n"
            f"name: Skill {i}\n"
            f"description: Skill description {i}.\n"
            f"dimensions: [system_design]\n"
            f"job_levels: [senior]\n"
            f"---\nBody {i}",
        )
    entries = skill_store.retrieve_skills(
        dimension="system_design", job_level="senior", limit=2
    )
    assert len(entries) == 2


def test_build_skills_block_empty_input_returns_placeholder(
    skills_root: Path,
) -> None:
    """Empty input list → stable placeholder string. Callers can
    unconditionally forward the result to the Generator prompt."""
    assert skill_store.build_skills_block([]) == (
        "(no relevant interview skills)"
    )


def test_build_skills_block_renders_entries(skills_root: Path) -> None:
    _write_skill(skills_root, "a.md", _SKILL_CARD_A)
    entries = skill_store.list_skills()
    block = skill_store.build_skills_block(entries)

    assert "[Skill 1] Senior Backend Ownership" in block
    assert "dims=leadership, system_design" in block
    assert "levels=senior, staff" in block
    assert "Body A goes here." in block


def test_build_skills_block_truncates_long_body(
    skills_root: Path,
) -> None:
    long_body = "x" * 2000
    _write_skill(
        skills_root,
        "a.md",
        "---\nname: Long\ndescription: .\n---\n" + long_body,
    )
    entries = skill_store.list_skills()
    block = skill_store.build_skills_block(entries, max_body_chars=200)
    assert "truncated" in block
    assert "x" * 2000 not in block


def test_build_skills_index_compact_catalog(skills_root: Path) -> None:
    _write_skill(skills_root, "a.md", _SKILL_CARD_A)
    _write_skill(skills_root, "b.md", _SKILL_CARD_B)
    index = skill_store.build_skills_index()
    assert index.startswith("## Available Interview Skills")
    assert "Senior Backend Ownership" in index
    assert "Junior Algorithm Warm-up" in index


def test_build_skills_index_empty_returns_empty_string(
    skills_root: Path,
) -> None:
    """Empty registry → empty string (caller can unconditionally
    concatenate into ``dynamic_system``)."""
    assert skill_store.build_skills_index() == ""
