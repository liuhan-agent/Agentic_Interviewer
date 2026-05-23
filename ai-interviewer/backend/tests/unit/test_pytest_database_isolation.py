from __future__ import annotations

from app.core.settings import get_settings


def test_pytest_does_not_use_development_database() -> None:
    settings = get_settings()

    assert settings.app_env == "test"
    assert "localhost:5433/interviewer" not in settings.database_url
    assert "interviewer:interviewer" not in settings.database_url
