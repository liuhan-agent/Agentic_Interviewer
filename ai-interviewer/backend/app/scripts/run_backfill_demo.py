"""Show the full RL loop end-to-end:

1. Run a mock interview (text mode) to produce traces.
2. Insert a fake OutcomeRecord saying the candidate was hired with a
   high performance score.
3. Run the outcome-reward bridge. Traces are back-filled and the
   bandit's Beta posteriors shift.
4. Dump the bandit snapshot before and after.

Run::

    python -m app.scripts.run_backfill_demo
"""
from __future__ import annotations

import json

from app.core.logging import get_logger
from app.ml.rl.outcome_reward_bridge import backfill_once
from app.ml.rl.thompson import get_bandit
from app.models import OutcomeRecord, get_session, init_db
from app.scripts.run_demo import run

log = get_logger(__name__)


def _inject_outcome(session_id: str, *, outcome: str = "hired", perf: float | None = 0.9) -> None:
    init_db()
    with get_session() as sess:
        sess.merge(
            OutcomeRecord(
                session_id=session_id,
                outcome=outcome,
                performance_score=perf,
                notes="injected by run_backfill_demo",
            )
        )


def main() -> None:
    result = run(max_turns=4, quality_threshold=7.0, turn_budget=6)
    session_id = result["session_id"]

    bandit = get_bandit()
    before = bandit.snapshot()
    _inject_outcome(session_id, outcome="hired", perf=0.9)
    counters = backfill_once()
    after = bandit.snapshot()

    print("\n\n====== BACKFILL SUMMARY ======")
    print(f"Session: {session_id}")
    print(f"Counters: {counters}")
    print("\nBandit posterior diff (only keys that moved):")
    diff = {}
    for k in set(before) | set(after):
        b = before.get(k, {"alpha": 1.0, "beta": 1.0})
        a = after.get(k, {"alpha": 1.0, "beta": 1.0})
        if b != a:
            diff[k] = {"before": b, "after": a}
    print(json.dumps(diff, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
