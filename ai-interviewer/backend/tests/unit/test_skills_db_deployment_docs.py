from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_backend_readme_documents_structured_question_and_skill_imports() -> None:
    readme = _read("backend/README.md")

    assert "QUESTION_SELECTOR_MODE=structured_primary" in readme
    assert "ENABLE_SKILL_INJECTION=true" in readme
    assert "SKILL_PLAYBOOK_BACKEND=db_with_file_fallback" in readme
    assert "python -m app.scripts.import_question_seeds --archive-missing" in readme
    assert "python -m app.scripts.import_skill_playbooks --archive-missing" in readme
    assert "QUESTION_SELECTOR_MODE=structured_shadow" in readme
    assert "QUESTION_SELECTOR_MODE=vector" in readme
    assert "SKILL_PLAYBOOK_BACKEND=file" in readme
    assert "ENABLE_SKILL_INJECTION=false" in readme
    assert "startup does not auto-import" in readme
    assert "RAG no longer owns question-bank or skills playbook content" in readme


def test_local_command_guide_documents_import_and_admin_verification() -> None:
    guide = _read("docs/本地开发命令速查.md")

    assert "python -m app.scripts.import_question_seeds --archive-missing" in guide
    assert "python -m app.scripts.import_skill_playbooks --archive-missing" in guide
    assert "Question Bank" in guide
    assert "Skills Playbook" in guide
    assert "active" in guide
    assert "Admin" in guide
