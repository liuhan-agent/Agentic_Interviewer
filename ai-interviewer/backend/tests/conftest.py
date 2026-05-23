from __future__ import annotations

import os
from pathlib import Path


_BACKEND_ROOT = Path(__file__).resolve().parents[1]
_TEST_DB = _BACKEND_ROOT / ".pytest_cache" / f"pytest-{os.getpid()}.sqlite3"
_TEST_DB.parent.mkdir(exist_ok=True)

# Keep ORM-based unit tests away from the developer's live Postgres DB.
os.environ["APP_ENV"] = "test"
os.environ["DATABASE_URL"] = os.environ.get(
    "PYTEST_DATABASE_URL",
    f"sqlite:///{_TEST_DB.as_posix()}",
)
os.environ.setdefault("CHECKPOINT_BACKEND", "memory")


def pytest_configure() -> None:
    try:
        from app.core.settings import get_settings

        get_settings.cache_clear()
    except Exception:
        pass
