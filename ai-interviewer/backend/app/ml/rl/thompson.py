"""Thompson Sampling bandit over the interview action space.

State layout
------------
Per-context Beta parameters, keyed by ``(context_key, action_id)`` where
``context_key`` is typically ``f"{job_level}:{dimension}"``. Alpha/beta
start at 1 (Jeffreys-style prior) so every arm gets explored.

This is a single-process, in-memory implementation for MVP. In Phase 2
the updates are persisted via the tracer + reward bridge, but the
sampling loop itself needs no changes: we just rehydrate priors from
the database on boot.
"""
from __future__ import annotations

import random
import threading
from dataclasses import dataclass, field
from typing import Any

from app.core.logging import get_logger

from .action_space import ACTIONS, ACTIONS_BY_ID, InterviewAction

log = get_logger(__name__)


@dataclass
class BetaParams:
    alpha: float = 1.0
    beta: float = 1.0

    def mean(self) -> float:
        return self.alpha / (self.alpha + self.beta)

    def sample(self, rng: random.Random) -> float:
        return rng.betavariate(self.alpha, self.beta)


@dataclass
class ThompsonBandit:
    exploration_rate: float = 0.15
    rng: random.Random = field(default_factory=random.Random)
    priors: dict[tuple[str, str], BetaParams] = field(default_factory=dict)
    _default_alpha: float = field(default=1.0, repr=False)
    _default_beta: float = field(default=1.0, repr=False)

    def _params(self, context_key: str, action_id: str) -> BetaParams:
        key = (context_key, action_id)
        if key not in self.priors:
            self.priors[key] = BetaParams(
                alpha=self._default_alpha,
                beta=self._default_beta,
            )
        return self.priors[key]

    def select(
        self,
        context_key: str,
        *,
        mask: set[str] | None = None,
    ) -> tuple[InterviewAction, dict[str, Any]]:
        """Sample an arm.

        ``mask`` is an optional set of action ids that are allowed in
        the current context (for example, ``SWITCH_DIMENSION`` is
        disabled when every dimension has already been visited).
        ``exploration_rate`` gives pure random exploration probability
        regardless of posterior, to avoid early lock-in.

        The candidate universe is:
        - ``mask``-based when a mask is supplied (any id in
          :data:`ACTIONS_BY_ID` is honoured, so callers can pass
          template-arm ids without subclassing the bandit);
        - the legacy 4-arm ``ACTIONS`` tuple otherwise (backwards
          compatible with callers that never pass a mask).
        """
        if mask is not None:
            candidates = [
                ACTIONS_BY_ID[aid] for aid in mask if aid in ACTIONS_BY_ID
            ]
            if not candidates:
                candidates = list(ACTIONS)
        else:
            candidates = list(ACTIONS)

        if self.rng.random() < self.exploration_rate:
            chosen = self.rng.choice(candidates)
            diagnostics = {
                "mode": "explore",
                "exploration_rate": self.exploration_rate,
                "chosen": chosen.id,
            }
            return chosen, diagnostics

        samples: dict[str, float] = {}
        for a in candidates:
            samples[a.id] = self._params(context_key, a.id).sample(self.rng)
        # Beta samples are continuous, so exact ties are rare in
        # practice - but when they do happen (e.g. early turns where
        # every arm is still on the Jeffreys prior) ``max(..., key=...)``
        # resolves ties by dict iteration order, which is the order
        # arms were registered.  That introduces a small but real
        # bias toward earlier-declared arms.  Break the tie with a
        # uniform choice instead.
        max_val = max(samples.values())
        top = [aid for aid, v in samples.items() if v == max_val]
        chosen_id = self.rng.choice(top) if len(top) > 1 else top[0]
        chosen = next(a for a in candidates if a.id == chosen_id)
        diagnostics = {
            "mode": "thompson",
            "context_key": context_key,
            "samples": samples,
            "posteriors": {
                a.id: {
                    "alpha": self._params(context_key, a.id).alpha,
                    "beta": self._params(context_key, a.id).beta,
                }
                for a in candidates
            },
            "chosen": chosen.id,
        }
        return chosen, diagnostics

    def update(self, context_key: str, action_id: str, reward: float) -> None:
        """Bernoulli-style update with clipped reward in [0, 1].

        Continuous rewards are translated to a fractional success/failure
        split so the Beta posterior stays well-defined.
        """
        reward = max(0.0, min(1.0, reward))
        p = self._params(context_key, action_id)
        p.alpha += reward
        p.beta += 1.0 - reward
        log.debug(
            "bandit update ctx=%s action=%s reward=%.3f -> a=%.2f b=%.2f",
            context_key,
            action_id,
            reward,
            p.alpha,
            p.beta,
        )

    def observation_count(
        self,
        context_key: str,
        *,
        mask: set[str] | None = None,
    ) -> float:
        """Approximate number of updates already seen for a context."""
        action_ids = mask or {
            action_id
            for ctx, action_id in self.priors.keys()
            if ctx == context_key
        }
        total = 0.0
        for action_id in action_ids:
            params = self.priors.get((context_key, action_id))
            if params is None:
                continue
            total += max(0.0, params.alpha + params.beta - 2.0)
        return total

    def snapshot(self) -> dict[str, dict[str, float]]:
        out: dict[str, dict[str, float]] = {}
        for (ctx, aid), p in self.priors.items():
            out.setdefault(f"{ctx}::{aid}", {})["alpha"] = p.alpha
            out[f"{ctx}::{aid}"]["beta"] = p.beta
        return out

    def decay(self, factor: float = 0.99, floor: float = 1.0) -> None:
        """Geometric decay of every posterior toward the prior.

        Interview outcomes are non-stationary: job requirements drift,
        evaluator rubrics get retuned, and candidate populations shift
        month over month.  An unbounded Beta posterior means early
        evidence dominates forever, so a weekly/daily decay is a
        standard way to keep the bandit responsive without throwing
        away information.

        ``factor`` should lie in (0, 1].  A value of 1.0 is a no-op
        (returns immediately).  ``floor`` prevents any arm's alpha/
        beta from shrinking below the Jeffreys-like prior - without it
        the bandit could collapse to a degenerate Beta after enough
        decay passes with no fresh rewards.

        Recommended starting point: ``factor=0.99`` called once per
        day gives a half-life of ~69 days, which matches quarterly
        hiring-signal drift in practice.
        """
        if factor >= 1.0:
            return
        for p in self.priors.values():
            p.alpha = max(floor, p.alpha * factor)
            p.beta = max(floor, p.beta * factor)
        log.info(
            "bandit decay applied (factor=%.3f floor=%.2f arms=%d)",
            factor,
            floor,
            len(self.priors),
        )

    def rehydrate_from_db(self) -> int:
        """Rebuild posteriors from already-applied generation traces.

        Two kinds of rows contribute to the rebuild, and both are
        idempotent per-row thanks to dedicated "applied" flags on
        :class:`GenerationTrace`:

        - ``immediate_reward_applied=True`` rows are evaluator-time
          rewards that were already fused via ``bandit.update`` in
          memory. Replaying them restores the pre-crash posterior
          before any outcome has been back-filled.
        - ``applied_to_bandit=True`` rows are delayed-reward outcomes
          written by the ``outcome_reward_bridge`` after hiring
          signals arrive. Replaying them carries the long-horizon
          signal forward across restarts.

        We treat each reward as a single Bernoulli-ish update with a
        clipped reward in ``[0, 1]`` to stay consistent with
        :meth:`update`. Returns the total number of rows that
        contributed to the rebuild, which is useful for startup logs
        and for test-driving the path.
        """
        try:
            from sqlalchemy import or_, select
            from sqlalchemy.exc import SQLAlchemyError

            from app.models import GenerationTrace, get_session
        except Exception as e:  # pragma: no cover - defensive
            log.warning("bandit rehydrate skipped (imports failed: %s)", e)
            return 0

        applied = 0
        try:
            with get_session() as sess:
                # Pull both reward columns so we can fuse them in a
                # single pass without issuing two queries.  The filter
                # keeps rows where at least one of the two flags fired.
                stmt = (
                    select(
                        GenerationTrace.context_key,
                        GenerationTrace.policy_context_keys,
                        GenerationTrace.action_id,
                        GenerationTrace.immediate_reward,
                        GenerationTrace.delayed_reward,
                        GenerationTrace.immediate_reward_applied,
                        GenerationTrace.applied_to_bandit,
                    )
                    .where(
                        or_(
                            GenerationTrace.immediate_reward_applied.is_(True),
                            GenerationTrace.applied_to_bandit.is_(True),
                        )
                    )
                    .where(GenerationTrace.context_key.is_not(None))
                    .where(GenerationTrace.action_id.is_not(None))
                    .order_by(GenerationTrace.id.asc())
                )
                from .action_space import ALIAS_MAP

                for (
                    ctx_key,
                    policy_keys,
                    action_id,
                    imm,
                    delayed,
                    imm_app,
                    del_app,
                ) in sess.execute(stmt):
                    if ctx_key is None or action_id is None:
                        continue
                    ctx_keys = _policy_keys(policy_keys, str(ctx_key))
                    act_str = str(action_id)
                    alias = ALIAS_MAP.get(act_str)

                    if imm_app and imm is not None:
                        r = float(imm)
                        for ctx_str in ctx_keys:
                            self.update(ctx_str, act_str, r)
                            if alias and alias != act_str:
                                self.update(ctx_str, alias, r)
                            applied += 1

                    if del_app and delayed is not None:
                        r = float(delayed)
                        for ctx_str in ctx_keys:
                            self.update(ctx_str, act_str, r)
                            if alias and alias != act_str:
                                self.update(ctx_str, alias, r)
                            applied += 1
        except SQLAlchemyError as e:
            log.warning("bandit rehydrate db error: %s", e)
            return applied
        except Exception as e:  # pragma: no cover - unexpected
            log.warning("bandit rehydrate failed: %s", e)
            return applied
        if applied:
            log.info("bandit rehydrated from %d applied traces", applied)
        return applied


_singleton: ThompsonBandit | None = None
_singleton_lock = threading.Lock()


def _policy_keys(value: Any, fallback: str) -> list[str]:
    if isinstance(value, list):
        keys = [str(item) for item in value if str(item or "").strip()]
    else:
        keys = []
    if not keys:
        keys = [fallback]
    deduped: list[str] = []
    seen: set[str] = set()
    for key in keys:
        if key not in seen:
            deduped.append(key)
            seen.add(key)
    return deduped


def get_bandit() -> ThompsonBandit:
    """Return the process-wide bandit, constructing it lazily.

    The double-checked-locking pattern keeps the hot path lock-free
    while preventing two concurrent callers (e.g. uvicorn worker
    boot in parallel with the outcome-sync scheduler) from ever
    constructing two separate instances and splitting the posteriors
    across them.
    """
    global _singleton
    if _singleton is None:
        with _singleton_lock:
            if _singleton is None:
                from app.core.settings import get_settings

                s = get_settings()
                _singleton = ThompsonBandit(
                    exploration_rate=s.thompson_exploration_rate,
                    _default_alpha=s.bandit_default_alpha,
                    _default_beta=s.bandit_default_beta,
                )
    return _singleton


def reset_bandit_for_tests() -> None:
    """Drop the module-level singleton; used by unit tests only."""
    global _singleton
    with _singleton_lock:
        _singleton = None
