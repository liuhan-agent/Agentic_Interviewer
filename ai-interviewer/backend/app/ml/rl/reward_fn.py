"""Immediate reward shaping for Thompson Sampling updates.

Real outcomes (offer acceptance, on-the-job performance) are only
available weeks later and get applied via ``outcome_reward_bridge``. In
the meantime the bandit needs *some* signal so we compute an immediate,
heuristic reward from the evaluator output.

Two classes of signal are fused:

1. *Positive* — evaluator score, ``passed``, rubric coverage.
2. *Negative* (contract-hygiene penalties) — apply when the generator /
   evaluator pipeline coasted past its own contract.  This discourages
   actions that inflate scores without actually enforcing the rubric.

Tunable knobs live in :mod:`app.core.settings`::

    reward_passed_bonus                    (default 0.10)
    reward_coverage_bonus                  (default 0.10)
    reward_contract_unsigned_penalty       (default 0.10)
    reward_acceptance_no_rate_threshold    (default 0.5)
    reward_acceptance_no_penalty           (default 0.10)
    reward_verifier_forced_refine_penalty  (default 0.15)
    reward_contract_gate_enforced_cap      (default 0.50)

Defaults preserve the historic hard-coded behaviour *when no contract
metadata is present*, so existing bandit checkpoints keep their
meaning after rollout; penalties only engage for new turns that
actually produced the structured fields below.
"""
from __future__ import annotations

from typing import Any

from app.core.settings import get_settings

MAX_SCORE = 10.0


def _no_rate(acceptance: dict[str, Any]) -> float:
    """Fraction of acceptance_check_results whose verdict is ``no``.

    Supports both the legacy ``{key: "yes|partial|no"}`` shape and the
    canonical ``{key: {"verdict": ..., "evidence": [...]}}`` shape
    introduced with the evidence-spans upgrade.
    """
    if not acceptance:
        return 0.0
    total = 0
    no_count = 0
    for v in acceptance.values():
        total += 1
        verdict = ""
        if isinstance(v, dict):
            verdict = str(v.get("verdict", "")).strip().lower()
        else:
            verdict = str(v).strip().lower()
        if verdict == "no":
            no_count += 1
    if total == 0:
        return 0.0
    return no_count / total


def immediate_reward(
    *,
    evaluation: dict[str, Any],
    contract: dict[str, Any] | None = None,
) -> float:
    """Return a reward in [0, 1].

    Positive signal:

    - Rubric score contributes the bulk of the signal, normalised to
      ``score / 10``.
    - ``reward_passed_bonus`` is added when ``passed`` is true.
    - Up to ``reward_coverage_bonus`` for rubric coverage.

    Negative signal (contract hygiene):

    - ``reward_contract_unsigned_penalty`` when the signed contract is
      missing the evaluator's co-signature (indicating the generator
      asked without negotiation).
    - ``reward_acceptance_no_penalty`` when more than
      ``reward_acceptance_no_rate_threshold`` of the
      acceptance_check_results came back as ``no``.
    - ``reward_verifier_forced_refine_penalty`` when the Verifier
      flipped a pass into a refine (the evaluator was overly
      generous).
    - ``reward_contract_gate_enforced_cap`` caps the reward when a
      reviewed-core contract gate forced the turn to refine even if the
      raw score stayed high.
    """
    s = get_settings()
    score = float(evaluation.get("score", 0.0))
    base = max(0.0, min(1.0, score / MAX_SCORE))
    if evaluation.get("passed"):
        base = min(1.0, base + s.reward_passed_bonus)

    coverage = evaluation.get("rubric_coverage") or {}
    if coverage:
        covered = sum(1 for v in coverage.values() if v in {"covered", "partial"})
        cov_bonus = (covered / len(coverage)) * s.reward_coverage_bonus
        base = min(1.0, base + cov_bonus)

    # Contract-hygiene penalties only engage when the caller passed a
    # contract (new path).  Old call sites that don't pass one keep
    # bit-identical behaviour with the pre-rollout reward_fn.
    penalty = 0.0
    if contract is not None:
        signed_by = set(contract.get("signed_by") or [])
        if "evaluator" not in signed_by:
            penalty += float(s.reward_contract_unsigned_penalty)

    acceptance = evaluation.get("acceptance_check_results") or {}
    if isinstance(acceptance, dict):
        rate = _no_rate(acceptance)
        if rate > float(s.reward_acceptance_no_rate_threshold):
            penalty += float(s.reward_acceptance_no_penalty)

    if evaluation.get("verifier_forced_refine"):
        penalty += float(s.reward_verifier_forced_refine_penalty)

    reward = max(0.0, min(1.0, base - penalty))
    if evaluation.get("contract_gate_enforced"):
        cap = max(0.0, min(1.0, float(s.reward_contract_gate_enforced_cap)))
        reward = min(reward, cap)
    return reward
