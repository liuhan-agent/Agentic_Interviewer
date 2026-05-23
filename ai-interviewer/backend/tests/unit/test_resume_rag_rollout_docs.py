from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
README = ROOT / "README.md"
RUNBOOK = ROOT.parent / "docs" / "RESUME_RAG_ROLLOUT.md"
SETTINGS = ROOT / "app" / "core" / "settings.py"


def test_settings_default_resume_rag_mode_is_primary() -> None:
    text = SETTINGS.read_text(encoding="utf-8")
    assert 'resume_rag_mode: Literal["off", "shadow", "primary"] = "primary"' in text


def test_readme_contains_pgvector_image() -> None:
    assert "pgvector/pgvector" in README.read_text(encoding="utf-8")


def test_readme_contains_resume_rag_mode_rollback() -> None:
    text = README.read_text(encoding="utf-8")
    assert "RESUME_RAG_MODE=primary" in text
    assert "RESUME_RAG_MODE=off" in text
    assert "RESUME_RAG_MODE=shadow" in text


def test_readme_contains_session_anchor_cleanup_cron() -> None:
    text = README.read_text(encoding="utf-8")
    assert "python -m app.scripts.cleanup_session_anchor_chunks" in text


def test_rollout_doc_lists_per_mode_thresholds() -> None:
    text = RUNBOOK.read_text(encoding="utf-8")
    assert "Mode A" in text and ">= 70%" in text
    assert "Mode B" in text and ">= 55%" in text
    assert "Mode C" in text and ">= 40%" in text
    assert "Mode SI" in text and ">= 50%" in text


def test_rollout_doc_includes_duplicate_rewrite_gate() -> None:
    """High hit-rate alone is insufficient to promote a mode to primary."""

    text = RUNBOOK.read_text(encoding="utf-8").lower()
    assert "duplicate-rewrite" in text
    assert "baseline" in text


def test_rollout_doc_includes_sampling_ramp_and_rollback() -> None:
    text = RUNBOOK.read_text(encoding="utf-8")
    assert "RESUME_RAG_MODE=primary" in text
    assert "resume_rag_session_sample_rate" in text
    assert "0.05" in text and "0.3" in text and "1.0" in text
    assert "RESUME_RAG_MODE=off" in text
