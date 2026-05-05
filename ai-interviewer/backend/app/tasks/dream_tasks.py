"""Periodic strategy consolidation ("autoDream") scheduling.

Gate conditions mirror Claude Code's ``autoDream``:
  - At least ``dream_interval_hours`` since the last dream.
  - At least ``dream_min_sessions`` new sessions accumulated.

State is tracked in a small JSON sidecar next to the strategy
directory so it survives process restarts without requiring the
database.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler

from app.core.logging import get_logger
from app.core.settings import get_settings
from app.memory.strategy_dream import run_dream

log = get_logger(__name__)


def _state_path() -> Path:
    return get_settings().knowledge_dir / "strategy" / ".dream_state.json"


def _load_state() -> dict:
    path = _state_path()
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {"last_dream_at": None, "sessions_since_dream": 0}


def _save_state(state: dict) -> None:
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, default=str), encoding="utf-8")


def increment_session_count() -> None:
    """Call after each completed interview session."""
    state = _load_state()
    state["sessions_since_dream"] = state.get("sessions_since_dream", 0) + 1
    _save_state(state)


def _should_dream() -> bool:
    settings = get_settings()
    if not settings.enable_strategy_dream:
        return False
    state = _load_state()

    min_sessions = settings.dream_min_sessions
    if state.get("sessions_since_dream", 0) < min_sessions:
        return False

    last = state.get("last_dream_at")
    if last:
        try:
            last_dt = datetime.fromisoformat(last)
            if last_dt.tzinfo is None:
                last_dt = last_dt.replace(tzinfo=UTC)
            hours_since = (datetime.now(UTC) - last_dt).total_seconds() / 3600
            if hours_since < settings.dream_interval_hours:
                return False
        except (ValueError, TypeError):
            pass

    return True


def _dream_tick() -> None:
    """Called by the scheduler on each interval. Checks gates then runs."""
    if not _should_dream():
        return
    log.info("dream gate passed — starting strategy consolidation")
    result = run_dream()
    # If the dream was skipped (e.g. stub LLM), do NOT reset the gates:
    # otherwise CI / dev environments silently consume every scheduled
    # cycle and nothing is ever actually consolidated. The gates remain
    # open until a real run actually performs work.
    if result.get("skipped"):
        log.info("dream skipped (%s); keeping gate state unchanged", result.get("summary"))
        return
    state = _load_state()
    state["last_dream_at"] = datetime.now(UTC).isoformat()
    state["sessions_since_dream"] = 0
    state["last_result"] = result
    _save_state(state)
    log.info("dream completed: %s", result.get("summary", ""))


def start_dream_scheduler(check_interval_minutes: int = 30) -> BackgroundScheduler:
    """Start a background scheduler that periodically checks dream gates."""
    scheduler = BackgroundScheduler(daemon=True)
    scheduler.add_job(
        _dream_tick,
        "interval",
        minutes=check_interval_minutes,
        id="strategy_dream",
        replace_existing=True,
    )
    scheduler.start()
    log.info("strategy dream scheduler started (check every %d min)", check_interval_minutes)
    return scheduler


def run_dream_now() -> dict:
    """One-shot for scripts / admin endpoints."""
    result = run_dream()
    if result.get("skipped"):
        # Same reasoning as ``_dream_tick``: a skip must not alter the
        # gate state. The caller still gets the diagnostic payload so
        # it can surface why nothing happened.
        return result
    state = _load_state()
    state["last_dream_at"] = datetime.now(UTC).isoformat()
    state["sessions_since_dream"] = 0
    state["last_result"] = result
    _save_state(state)
    return result
