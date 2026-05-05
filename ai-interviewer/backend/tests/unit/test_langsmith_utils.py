"""Tests for ``app.core.langsmith_utils`` and the env-bucketed
``Settings.effective_langsmith_project`` helper.

Scope
-----
These are pure-function tests: no network, no LangSmith SDK calls, no
graph invocations. The goal is to pin the shape contract the downstream
``session_manager._graph_config`` / ``run_demo.py`` paths rely on so a
refactor of the inner helpers can be caught before it silently drops
metadata that operators consume in the LangSmith dashboard.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

from app.core.langsmith_utils import build_langsmith_config, candidate_hash
from app.core.settings import Settings


def test_fastapi_app_uses_lifespan_instead_of_on_event() -> None:
    source = (
        Path(__file__).resolve().parents[2] / "app" / "main.py"
    ).read_text(encoding="utf-8")

    assert "@app.on_event" not in source
    assert "lifespan=" in source

# ---------------------------------------------------------------------------
# candidate_hash
# ---------------------------------------------------------------------------


def test_candidate_hash_returns_12_char_hex_for_normal_input() -> None:
    h = candidate_hash("Alice Zhang")
    assert h is not None
    assert len(h) == 12
    assert re.fullmatch(r"[0-9a-f]{12}", h)


def test_candidate_hash_is_stable_for_same_input() -> None:
    assert candidate_hash("Alice Zhang") == candidate_hash("Alice Zhang")


def test_candidate_hash_differs_across_inputs() -> None:
    assert candidate_hash("Alice Zhang") != candidate_hash("Bob Li")


def test_candidate_hash_strips_whitespace_but_is_case_sensitive() -> None:
    """Whitespace is cosmetic; casing is a real identity signal."""
    assert candidate_hash("  Alice Zhang  ") == candidate_hash("Alice Zhang")
    assert candidate_hash("alice zhang") != candidate_hash("Alice Zhang")


@pytest.mark.parametrize("value", [None, "", "   ", "\t\n"])
def test_candidate_hash_empty_like_returns_none(value: str | None) -> None:
    """Empty-ish names collapse to ``None`` so the metadata key drops."""
    assert candidate_hash(value) is None


# ---------------------------------------------------------------------------
# build_langsmith_config
# ---------------------------------------------------------------------------


def test_build_langsmith_config_returns_empty_dict_when_tracing_off() -> None:
    """The callers rely on a truthy-check to merge; empty is the signal."""
    cfg = build_langsmith_config(
        tracing_enabled=False,
        session_id="sess-xyz",
        trace_id="trace-xyz",
        app_env="dev",
        candidate_name="Alice",
        job_level="senior",
        mode="mixed",
    )
    assert cfg == {}


def test_build_langsmith_config_full_happy_path() -> None:
    cfg = build_langsmith_config(
        tracing_enabled=True,
        session_id="sess-abcd1234",
        trace_id="trace-abcd",
        app_env="prod",
        candidate_name="Alice Zhang",
        job_level="senior",
        job_title="Backend Engineer",
        mode="mixed",
        turn_idx=3,
    )

    md = cfg["metadata"]
    assert md["session_id"] == "sess-abcd1234"
    assert md["trace_id"] == "trace-abcd"
    assert md["app_env"] == "prod"
    assert md["job_level"] == "senior"
    assert md["job_title"] == "Backend Engineer"
    assert md["mode"] == "mixed"
    assert md["turn_idx"] == 3
    # PII contract: hashed, never plain
    assert md["candidate_hash"] == candidate_hash("Alice Zhang")
    assert "candidate_name" not in md

    # Tags carry the drill-down filters the dashboard exposes.
    assert "env:prod" in cfg["tags"]
    assert "level:senior" in cfg["tags"]
    assert "mode:mixed" in cfg["tags"]

    assert cfg["run_name"] == "interview.sess-abc.turn3"


def test_build_langsmith_config_omits_empty_optionals() -> None:
    """None / empty optionals should not appear as blank metadata
    columns in the LangSmith UI."""
    cfg = build_langsmith_config(
        tracing_enabled=True,
        session_id="sess-xyz",
        trace_id="trace-xyz",
        app_env="dev",
    )
    md = cfg["metadata"]
    assert set(md.keys()) == {"session_id", "trace_id", "app_env"}
    assert cfg["tags"] == ["env:dev"]
    # Turn index unknown -> run_name is readable without "turnNone"
    assert cfg["run_name"].endswith(".turn?")


def test_build_langsmith_config_extra_metadata_does_not_override_core() -> None:
    """Caller-supplied extras must not clobber reserved keys so the
    core metadata (session_id / trace_id / app_env) stays trustworthy."""
    cfg = build_langsmith_config(
        tracing_enabled=True,
        session_id="real",
        trace_id="real-trace",
        app_env="dev",
        extra_metadata={"session_id": "nope", "custom_field": "keep"},
    )
    md = cfg["metadata"]
    assert md["session_id"] == "real"  # reserved key protected
    assert md["custom_field"] == "keep"


def test_build_langsmith_config_extra_tags_dedupe() -> None:
    """Tag list should stay stable under idempotent merges (the caller
    may union defaults with per-turn tags)."""
    cfg = build_langsmith_config(
        tracing_enabled=True,
        session_id="s",
        trace_id="t",
        app_env="dev",
        job_level="senior",
        extra_tags=["level:senior", "source:run_demo", ""],
    )
    # Duplicate "level:senior" collapsed, empty string dropped.
    assert cfg["tags"].count("level:senior") == 1
    assert "source:run_demo" in cfg["tags"]
    assert "" not in cfg["tags"]


def test_build_langsmith_config_run_name_truncates_long_session_id() -> None:
    """The run_name must stay terse so the LangSmith run list is
    readable even with UUID session ids."""
    cfg = build_langsmith_config(
        tracing_enabled=True,
        session_id="sess-" + "a" * 40,
        trace_id="t",
        app_env="dev",
        turn_idx=7,
    )
    assert cfg["run_name"] == "interview.sess-aaa.turn7"


def test_configure_langsmith_sets_traceable_v2_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.main import _configure_langsmith

    keys = (
        "LANGSMITH_TRACING",
        "LANGSMITH_TRACING_V2",
        "LANGCHAIN_TRACING_V2",
        "LANGSMITH_API_KEY",
        "LANGCHAIN_API_KEY",
        "LANGSMITH_PROJECT",
        "LANGCHAIN_PROJECT",
    )
    for key in keys:
        monkeypatch.delenv(key, raising=False)

    try:
        _configure_langsmith(
            _settings(
                langsmith_tracing=True,
                langsmith_api_key="ls-test-key",
                app_env="dev",
            )
        )

        assert os.environ["LANGSMITH_TRACING"] == "true"
        assert os.environ["LANGSMITH_TRACING_V2"] == "true"
        assert os.environ["LANGCHAIN_TRACING_V2"] == "true"
    finally:
        for key in keys:
            os.environ.pop(key, None)


# ---------------------------------------------------------------------------
# Settings.effective_langsmith_project
# ---------------------------------------------------------------------------


def _settings(**overrides: object) -> Settings:
    """Instantiate ``Settings`` explicitly instead of via ``get_settings``
    so the ``lru_cache`` in production does not bleed between tests."""
    return Settings(**overrides)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "env,expected",
    [
        ("dev", "agentic-interviewer-dev"),
        ("prod", "agentic-interviewer-prod"),
        ("test", "agentic-interviewer-test"),
    ],
)
def test_effective_langsmith_project_splits_by_env(env: str, expected: str) -> None:
    s = _settings(app_env=env)
    assert s.effective_langsmith_project == expected


def test_effective_langsmith_project_honours_custom_base() -> None:
    s = _settings(app_env="prod", langsmith_project="my-bespoke")
    assert s.effective_langsmith_project == "my-bespoke-prod"


def test_effective_langsmith_project_falls_back_when_base_empty() -> None:
    """Empty / whitespace base should not produce a leading dash."""
    s = _settings(app_env="dev", langsmith_project="   ")
    assert s.effective_langsmith_project == "agentic-interviewer-dev"


def test_effective_langsmith_project_split_can_be_disabled() -> None:
    """Operators migrating legacy dashboards need a kill-switch."""
    s = _settings(app_env="prod", langsmith_project_split_by_env=False)
    assert s.effective_langsmith_project == "agentic-interviewer"
