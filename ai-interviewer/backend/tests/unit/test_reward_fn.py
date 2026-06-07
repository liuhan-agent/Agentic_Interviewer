from __future__ import annotations

from types import SimpleNamespace


def _settings(**overrides: object) -> SimpleNamespace:
    values: dict[str, object] = {
        "reward_passed_bonus": 0.10,
        "reward_coverage_bonus": 0.10,
        "reward_contract_unsigned_penalty": 0.10,
        "reward_acceptance_no_rate_threshold": 0.5,
        "reward_acceptance_no_penalty": 0.10,
        "reward_verifier_forced_refine_penalty": 0.15,
        "reward_contract_gate_enforced_cap": 0.5,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_settings_exposes_contract_gate_enforced_reward_cap() -> None:
    from app.core.settings import Settings

    assert Settings.model_fields["reward_contract_gate_enforced_cap"].default == 0.5


def test_immediate_reward_caps_gate_enforced_high_score(monkeypatch) -> None:
    from app.ml.rl import reward_fn

    monkeypatch.setattr(reward_fn, "get_settings", lambda: _settings())

    reward = reward_fn.immediate_reward(
        evaluation={
            "score": 9.0,
            "passed": False,
            "contract_gate_enforced": True,
            "contract_gate_enforcement_reason": "reviewed_core_failed",
        },
        contract={"signed_by": ["generator", "evaluator"]},
    )

    assert reward == 0.5


def test_immediate_reward_does_not_cap_regular_high_score(monkeypatch) -> None:
    from app.ml.rl import reward_fn

    monkeypatch.setattr(reward_fn, "get_settings", lambda: _settings())

    reward = reward_fn.immediate_reward(
        evaluation={"score": 9.0, "passed": False},
        contract={"signed_by": ["generator", "evaluator"]},
    )

    assert reward == 0.9
