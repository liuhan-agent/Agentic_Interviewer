from __future__ import annotations

from app.engine.contracts.acceptance_compiler import compile_locked_acceptance_checks


def _locked_core() -> dict:
    return {
        "must_cover": ["consistency target", "failure window"],
        "minimum_bar": "Explains cache consistency and failure handling.",
        "locked_rubric_additions": [
            "mentions invalidation window",
            "names rollback signal",
        ],
        "bar_level": "deep_probe",
        "seed_ref": {
            "seed_id": "system_design.cache_consistency",
            "variant_id": "system_design.cache_consistency.flash_sale_inventory",
            "seed_version": 3,
            "variant_version": 7,
        },
    }


def test_compile_locked_acceptance_checks_from_core_and_supporting_items() -> None:
    checks = compile_locked_acceptance_checks(_locked_core())

    assert [check["source"] for check in checks] == [
        "must_cover",
        "must_cover",
        "rubric_addition",
        "rubric_addition",
    ]
    assert [check["severity"] for check in checks] == [
        "core",
        "core",
        "supporting",
        "supporting",
    ]
    assert checks[0]["source_text"] == "consistency target"
    assert checks[0]["acceptance_check"] == (
        "Answer explicitly covers consistency target."
    )
    assert checks[2]["acceptance_check"] == (
        "Answer provides evidence for mentions invalidation window."
    )
    assert checks[0]["seed_ref"] == _locked_core()["seed_ref"]


def test_compile_locked_acceptance_checks_handles_empty_inputs() -> None:
    assert compile_locked_acceptance_checks(None) == []
    assert compile_locked_acceptance_checks({}) == []
    assert (
        compile_locked_acceptance_checks(
            {
                "must_cover": ["core item"],
                "locked_rubric_additions": [],
                "seed_ref": {"seed_id": "seed"},
            }
        )[0]["acceptance_check"]
        == "Answer explicitly covers core item."
    )


def test_compile_locked_acceptance_checks_deduplicates_and_keeps_stable_ids() -> None:
    locked_core = _locked_core()
    locked_core["must_cover"] = ["consistency target", " consistency target "]
    locked_core["locked_rubric_additions"] = [
        "说明降级策略",
        "说明降级策略",
    ]

    first = compile_locked_acceptance_checks(locked_core)
    second = compile_locked_acceptance_checks(locked_core)

    assert len(first) == 2
    assert [check["check_id"] for check in first] == [
        check["check_id"] for check in second
    ]
    assert first[1]["acceptance_check"] == "回答需要说明降级策略。"
    assert first[1]["seed_ref"]["variant_version"] == 7
