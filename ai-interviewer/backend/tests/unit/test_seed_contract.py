from __future__ import annotations

from app.engine.contracts.seed_contract import build_locked_core_contract


def _seed_hints() -> dict:
    return {
        "question_seed": {
            "seed_id": "system_design.cache_consistency",
            "variant_id": "system_design.cache_consistency.flash_sale_inventory",
            "seed_version": 3,
            "variant_version": 7,
            "rubric": {
                "must_cover": ["consistency target", "failure window"],
                "minimum_bar": "Explains cache consistency and failure handling.",
                "stretch": "Covers recovery and validation.",
            },
            "rubric_additions": ["mentions invalidation window", "names rollback signal"],
            "expected_signals": ["distinguishes strong and eventual consistency"],
            "anti_patterns": ["only says add Redis lock"],
            "good_answer_hints": ["define consistency target first"],
        }
    }


def test_build_locked_core_contract_from_question_seed_hints() -> None:
    contract = build_locked_core_contract(
        contract_hints=_seed_hints(),
        target_difficulty="hard",
    )

    assert contract is not None
    assert contract["must_cover"] == ["consistency target", "failure window"]
    assert contract["minimum_bar"] == (
        "Explains cache consistency and failure handling."
    )
    assert contract["locked_rubric_additions"] == [
        "mentions invalidation window",
        "names rollback signal",
    ]
    assert contract["bar_level"] == "deep_probe"
    assert contract["seed_ref"] == {
        "seed_id": "system_design.cache_consistency",
        "variant_id": "system_design.cache_consistency.flash_sale_inventory",
        "seed_version": 3,
        "variant_version": 7,
    }


def test_build_locked_core_contract_returns_none_without_seed_rubric_or_must_cover() -> None:
    assert build_locked_core_contract(contract_hints={}, target_difficulty="medium") is None
    assert (
        build_locked_core_contract(
            contract_hints={"question_seed": {"rubric": {}}},
            target_difficulty="medium",
        )
        is None
    )
    assert (
        build_locked_core_contract(
            contract_hints={"question_seed": {"rubric": {"must_cover": []}}},
            target_difficulty="medium",
        )
        is None
    )


def test_build_locked_core_contract_maps_target_difficulty_to_bar_level() -> None:
    assert (
        build_locked_core_contract(
            contract_hints=_seed_hints(),
            target_difficulty="easy",
        )["bar_level"]
        == "intro"
    )
    assert (
        build_locked_core_contract(
            contract_hints=_seed_hints(),
            target_difficulty="medium",
        )["bar_level"]
        == "standard"
    )
    assert (
        build_locked_core_contract(
            contract_hints=_seed_hints(),
            target_difficulty="unknown",
        )["bar_level"]
        == "standard"
    )
