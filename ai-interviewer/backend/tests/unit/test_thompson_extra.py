"""Additional Thompson bandit invariants introduced in Step 6.

Scope: tie-breaking, ``decay``, and the ``get_bandit`` double-checked
singleton lock.  The pre-existing ``test_thompson.py`` covers
posterior mechanics and is not duplicated here.
"""
from __future__ import annotations

import random
import threading
from collections import Counter

from app.ml.rl.action_space import DEEPEN_TECHNICAL, SWITCH_DIMENSION
from app.ml.rl.thompson import (
    BetaParams,
    ThompsonBandit,
    get_bandit,
    reset_bandit_for_tests,
)


class _FixedSampleRng:
    """Deterministic ``rng`` stand-in that returns a scripted sequence
    of ``betavariate`` outputs.  ``choice`` delegates to a real
    ``random.Random`` so tie-break assertions still exercise real
    uniform behaviour."""

    def __init__(self, beta_values: list[float], seed: int = 0) -> None:
        self._values = list(beta_values)
        self._idx = 0
        self._real = random.Random(seed)

    def betavariate(self, _a: float, _b: float) -> float:
        v = self._values[self._idx % len(self._values)]
        self._idx += 1
        return v

    def random(self) -> float:
        return self._real.random()

    def choice(self, seq):  # type: ignore[no-untyped-def]
        return self._real.choice(list(seq))


def test_select_breaks_ties_with_uniform_choice():
    """When two arms sample the exact same Beta value the bandit
    must not default to dict iteration order - it must actually
    coin-flip.  We rig a tie and run many trials."""
    counts: Counter[str] = Counter()
    trials = 400
    for seed in range(trials):
        bandit = ThompsonBandit(
            exploration_rate=0.0,
            # Always return 0.5 so every candidate arm samples the
            # same value; the rng.choice path must decide.
            rng=_FixedSampleRng([0.5], seed=seed),
        )
        action, _ = bandit.select(
            "senior:tech",
            mask={DEEPEN_TECHNICAL.id, SWITCH_DIMENSION.id},
        )
        counts[action.id] += 1
    # Expect roughly 50/50.  Tolerate sampling noise generously.
    a = counts.get(DEEPEN_TECHNICAL.id, 0)
    b = counts.get(SWITCH_DIMENSION.id, 0)
    assert a + b == trials
    assert abs(a - b) < trials * 0.20, (
        f"tie-breaking looks biased: a={a}, b={b}, trials={trials}"
    )


def test_decay_shrinks_params_toward_floor():
    bandit = ThompsonBandit()
    bandit.priors[("senior:tech", DEEPEN_TECHNICAL.id)] = BetaParams(
        alpha=10.0, beta=4.0
    )
    bandit.priors[("senior:tech", SWITCH_DIMENSION.id)] = BetaParams(
        alpha=1.0, beta=1.0
    )
    bandit.decay(factor=0.5, floor=1.0)
    a = bandit.priors[("senior:tech", DEEPEN_TECHNICAL.id)]
    b = bandit.priors[("senior:tech", SWITCH_DIMENSION.id)]
    # 10 * 0.5 = 5, 4 * 0.5 = 2 -> both above floor so unchanged by
    # the floor clamp.
    assert a.alpha == 5.0
    assert a.beta == 2.0
    # 1 * 0.5 = 0.5 -> clamped back up to floor=1.0.
    assert b.alpha == 1.0
    assert b.beta == 1.0


def test_decay_noop_when_factor_geq_one():
    bandit = ThompsonBandit()
    bandit.priors[("senior:tech", DEEPEN_TECHNICAL.id)] = BetaParams(
        alpha=7.5, beta=3.0
    )
    bandit.decay(factor=1.0, floor=1.0)
    p = bandit.priors[("senior:tech", DEEPEN_TECHNICAL.id)]
    assert p.alpha == 7.5
    assert p.beta == 3.0


def test_get_bandit_is_singleton_under_concurrency():
    """Double-checked lock must prevent concurrent ``get_bandit`` calls
    from producing two separate instances."""
    reset_bandit_for_tests()

    instances: list[object] = []

    def _worker() -> None:
        instances.append(get_bandit())

    threads = [threading.Thread(target=_worker) for _ in range(16)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # All threads must see the same object.
    assert len(instances) == 16
    first = instances[0]
    assert all(x is first for x in instances)

    reset_bandit_for_tests()
