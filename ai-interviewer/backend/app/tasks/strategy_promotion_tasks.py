"""Task entrypoints for strategy signal promotion."""
from __future__ import annotations

from dataclasses import asdict

from app.models import get_session
from app.services.strategy_promotion import (
    apply_strategy_quality_transitions,
    promote_strategy_signals,
)
from app.services.strategy_memory_stats import refresh_strategy_memory_stats


def run_strategy_promotion_now() -> dict[str, int]:
    """Run one promotion pass and return simple counters."""
    with get_session() as session:
        refresh_strategy_memory_stats(session=session)
        promotion = asdict(promote_strategy_signals(session=session))
        quality = asdict(apply_strategy_quality_transitions(session=session))
    return {
        "promoted": promotion["promoted"],
        "unchanged": promotion["unchanged"] + quality["unchanged"],
        "skipped": promotion["skipped"] + quality["skipped"],
        "disabled": quality["disabled"],
        "stabilized": quality["stabilized"],
    }
