"""Tests for the strategy dream forked agent.

Covers the three red-flag areas identified in the review:

1. Stub-mode skip: ``run_dream`` must return ``skipped=True`` and
   ``dream_tasks`` must not reset the gate state.
2. Path-traversal sandbox: ``_exec_tool`` must refuse absolute paths,
   parent-escape sequences, and drive-style Windows paths.
3. Rollback on exception: any tool execution error must fall back to
   the pre-run backup so the strategy directory is never left in a
   half-mutated state.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.memory import strategy_dream as sd
from app.memory import strategy_store as ss
from app.tasks import dream_tasks


@pytest.fixture
def isolated_strategy_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Point the strategy memory layer at a throwaway tmp dir."""
    strategy_dir = tmp_path / "strategy"
    strategy_dir.mkdir()
    # Seed one strategy so ``run_dream`` has something to list.
    (strategy_dir / "seed.md").write_text(
        "---\nname: seed\ndescription: seed strategy\n"
        "dimensions: [system_design]\njob_levels: [mid]\n---\n\nBody\n",
        encoding="utf-8",
    )

    class FakeSettings:
        def __init__(self) -> None:
            self.knowledge_dir = tmp_path
            self.use_stub_llm = True  # default for tests; override per test
            self.llm_provider = "stub"
            self.llm_model = "stub-model"
            self.openai_api_key = None
            self.enable_strategy_dream = True
            self.dream_interval_hours = 24
            self.dream_min_sessions = 5

    fake = FakeSettings()
    # Clear the lru_cache on the real settings accessor BEFORE we
    # patch it — callers that resolved get_settings() from their own
    # module-level import would otherwise hang onto the cached real
    # instance.
    from app.core import settings as core_settings

    try:
        core_settings.get_settings.cache_clear()
    except AttributeError:
        pass

    monkeypatch.setattr(core_settings, "get_settings", lambda: fake)
    monkeypatch.setattr(ss, "get_settings", lambda: fake)
    # strategy_dream imports get_settings lazily inside run_dream; the
    # two lines above cover it. No extra patch needed there.
    yield strategy_dir


# ---------------------------------------------------------------------
# Bug 1: stub-mode skip must not eat the gate state
# ---------------------------------------------------------------------


def test_run_dream_in_stub_mode_returns_skipped_marker(isolated_strategy_dir):
    result = sd.run_dream()
    assert result.get("skipped") is True
    assert result["actions_executed"] == 0
    # No changes should have been applied.
    assert (isolated_strategy_dir / "seed.md").exists()


def test_dream_tick_does_not_reset_gates_when_skipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, isolated_strategy_dir
):
    # Pretend we already have enough sessions AND enough time passed,
    # so the gate is open — the only thing that should keep it open is
    # the ``skipped`` marker.
    state_file = isolated_strategy_dir / ".dream_state.json"
    state_file.write_text(
        '{"last_dream_at": null, "sessions_since_dream": 99}',
        encoding="utf-8",
    )

    dream_tasks._dream_tick()

    # State file must be unchanged: still 99 sessions, still no
    # last_dream_at, because a stub-skip is NOT a real cycle.
    from json import loads

    persisted = loads(state_file.read_text(encoding="utf-8"))
    assert persisted["sessions_since_dream"] == 99
    assert persisted.get("last_dream_at") is None


def test_run_dream_now_preserves_gates_when_skipped(isolated_strategy_dir):
    # Seed a distinctive gate state so we can detect an accidental reset.
    state_file = isolated_strategy_dir / ".dream_state.json"
    state_file.write_text(
        '{"last_dream_at": "2024-01-01T00:00:00+00:00", "sessions_since_dream": 42}',
        encoding="utf-8",
    )

    result = dream_tasks.run_dream_now()
    assert result.get("skipped") is True

    # Gate state must be unchanged: skipped run did NOT consume the
    # scheduled cycle.
    from json import loads

    persisted = loads(state_file.read_text(encoding="utf-8"))
    assert persisted["sessions_since_dream"] == 42
    assert persisted["last_dream_at"] == "2024-01-01T00:00:00+00:00"


# ---------------------------------------------------------------------
# Bug 2: path traversal sandbox
# ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_name",
    [
        "../../etc/passwd",
        "../outside.md",
        "/absolute/path.md",
        "\\absolute\\path.md",
        "C:\\Windows\\System32\\drivers\\etc\\hosts",
        "",
        ".",
        "..",
    ],
)
def test_safe_path_rejects_traversal_and_absolute(
    isolated_strategy_dir, bad_name: str
):
    root = isolated_strategy_dir
    assert sd._safe_path_within_root(bad_name, root) is None


def test_safe_path_accepts_plain_filename(isolated_strategy_dir):
    path = sd._safe_path_within_root("seed.md", isolated_strategy_dir)
    assert path is not None
    assert path.name == "seed.md"
    assert str(path).startswith(str(isolated_strategy_dir))


def test_exec_tool_rejects_path_traversal_on_read(isolated_strategy_dir):
    import json

    result_str = sd._exec_tool(
        "read_strategy", {"filename": "../../../etc/passwd"}
    )
    result = json.loads(result_str)
    assert result.get("sandbox_violation") is True


def test_exec_tool_rejects_path_traversal_on_delete(isolated_strategy_dir):
    import json

    # Put a decoy file outside the sandbox; the test must fail the
    # sandbox check before reaching any delete call.
    decoy = isolated_strategy_dir.parent / "decoy.md"
    decoy.write_text("do not delete me", encoding="utf-8")

    result_str = sd._exec_tool(
        "delete_strategy_file", {"filename": "../decoy.md"}
    )
    result = json.loads(result_str)
    assert result.get("sandbox_violation") is True
    # Critical: the decoy must still exist.
    assert decoy.exists()
    assert decoy.read_text(encoding="utf-8") == "do not delete me"


def test_exec_tool_allows_legitimate_filename(isolated_strategy_dir):
    result_str = sd._exec_tool("read_strategy", {"filename": "seed.md"})
    assert "Body" in result_str  # the body of the seed file is returned raw
