"""Task entrypoints for strategy signal promotion."""
from __future__ import annotations

from dataclasses import asdict

from app.models import get_session
from app.services.strategy_promotion import promote_strategy_signals


def run_strategy_promotion_now() -> dict[str, int]:
    """Run one promotion pass and return simple counters."""
    with get_session() as session:
        result = promote_strategy_signals(session=session)
    return asdict(result)
