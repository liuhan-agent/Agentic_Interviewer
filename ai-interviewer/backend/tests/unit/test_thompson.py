"""Unit tests for the Thompson Sampling bandit."""
from __future__ import annotations

import random

from app.ml.rl.action_space import ACTIONS, DEEPEN_TECHNICAL, SWITCH_DIMENSION
from app.ml.rl.thompson import BetaParams, ThompsonBandit


def _deterministic_bandit(exploration_rate: float = 0.0) -> ThompsonBandit:
    """Fixed-seed bandit for reproducible assertions."""
    return ThompsonBandit(exploration_rate=exploration_rate, rng=random.Random(42))


def test_beta_params_mean_and_sample_in_unit_interval():
    p = BetaParams(alpha=2.0, beta=3.0)
    assert abs(p.mean() - 0.4) < 1e-9
    rng = random.Random(0)
    for _ in range(100):
        s = p.sample(rng)
        assert 0.0 <= s <= 1.0


def test_bandit_returns_one_of_known_actions():
    bandit = _deterministic_bandit()
    action, diag = bandit.select("senior:technical_depth")
    assert action in ACTIONS
    assert diag["chosen"] == action.id


def test_bandit_respects_mask():
    bandit = _deterministic_bandit()
    allowed = {SWITCH_DIMENSION.id}
    action, _ = bandit.select("senior:system_design", mask=allowed)
    assert action.id == SWITCH_DIMENSION.id


def test_bandit_update_shifts_posterior_towards_winning_arm():
    bandit = _deterministic_bandit(exploration_rate=0.0)
    ctx = "senior:technical_depth"

    for _ in range(50):
        bandit.update(ctx, DEEPEN_TECHNICAL.id, reward=1.0)
    for _ in range(50):
        bandit.update(ctx, SWITCH_DIMENSION.id, reward=0.0)

    winning = bandit._params(ctx, DEEPEN_TECHNICAL.id)
    losing = bandit._params(ctx, SWITCH_DIMENSION.id)
    assert winning.mean() > losing.mean()
    assert winning.alpha > winning.beta
    assert losing.beta > losing.alpha


def test_exploration_mode_triggers_on_high_rate():
    bandit = ThompsonBandit(exploration_rate=1.0, rng=random.Random(1))
    _, diag = bandit.select("senior:technical_depth")
    assert diag["mode"] == "explore"


def test_snapshot_shape():
    bandit = _deterministic_bandit()
    bandit.update("senior:technical_depth", DEEPEN_TECHNICAL.id, reward=1.0)
    snap = bandit.snapshot()
    assert "senior:technical_depth::deepen_technical" in snap
    assert snap["senior:technical_depth::deepen_technical"]["alpha"] > 1.0
