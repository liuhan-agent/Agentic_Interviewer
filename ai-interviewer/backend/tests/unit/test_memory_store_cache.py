from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.memory import skill_store, strategy_store


def test_list_strategies_reuses_cache_when_directory_signature_is_unchanged(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "knowledge"
    strategy_dir = root / "strategy"
    strategy_dir.mkdir(parents=True)
    (strategy_dir / "backend.md").write_text(
        "---\n"
        "name: Backend Depth\n"
        "description: Probe depth.\n"
        "dimensions: [technical_depth]\n"
        "job_levels: [senior]\n"
        "---\n\n"
        "Ask for trade-offs.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        strategy_store,
        "get_settings",
        lambda: SimpleNamespace(knowledge_dir=root),
    )
    strategy_store.clear_strategy_cache_for_tests()

    first = strategy_store.list_strategies()
    assert [entry.name for entry in first] == ["Backend Depth"]

    def fail_read_text(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("cached strategy listing should not re-read files")

    monkeypatch.setattr(strategy_store.Path, "read_text", fail_read_text)

    second = strategy_store.list_strategies()
    assert [entry.name for entry in second] == ["Backend Depth"]


def test_list_skills_reuses_cache_when_directory_signature_is_unchanged(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "knowledge"
    skills_dir = root / "skills"
    skills_dir.mkdir(parents=True)
    (skills_dir / "backend.md").write_text(
        "---\n"
        "name: Backend Skill\n"
        "description: Probe backend skill.\n"
        "dimensions: [system_design]\n"
        "job_levels: [staff]\n"
        "---\n\n"
        "Ask about operability.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        skill_store,
        "get_settings",
        lambda: SimpleNamespace(knowledge_dir=root),
    )
    skill_store.clear_skill_cache_for_tests()

    first = skill_store.list_skills()
    assert [entry.name for entry in first] == ["Backend Skill"]

    def fail_read_text(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("cached skill listing should not re-read files")

    monkeypatch.setattr(skill_store.Path, "read_text", fail_read_text)

    second = skill_store.list_skills()
    assert [entry.name for entry in second] == ["Backend Skill"]
