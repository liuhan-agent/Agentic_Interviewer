from types import SimpleNamespace

from app.engine.contracts.contract_gate import (
    apply_contract_gate_enforcement,
    build_contract_gate_result,
    resolve_contract_gate_mode,
)


def _item(
    *,
    source: str = "reviewed",
    severity: str = "core",
    verdict: str = "yes",
    result_present: bool = True,
    check_id: str = "reviewed:one",
    text: str = "Explains the reviewed core point.",
    evidence: list[str] | None = None,
) -> dict[str, object]:
    return {
        "check_id": check_id,
        "text": text,
        "source": source,
        "severity": severity,
        "verdict": verdict,
        "result_present": result_present,
        "evidence": evidence if evidence is not None else ["quote"],
    }


def test_reviewed_core_all_yes_passes_shadow_gate() -> None:
    result = build_contract_gate_result(
        [
            _item(check_id="reviewed:one", text="Core one", verdict="yes"),
            _item(check_id="reviewed:two", text="Core two", verdict="YES"),
            _item(source="adaptive_context", severity="supporting", verdict="no"),
        ]
    )

    assert result["gate_id"] == "reviewed_core_acceptance"
    assert result["mode"] == "shadow"
    assert result["status"] == "passed"
    assert result["would_pass"] is True
    assert result["eligible_count"] == 2
    assert result["satisfied_count"] == 2
    assert result["failed_count"] == 0
    assert result["failed_items"] == []


def test_reviewed_core_partial_no_and_missing_fail_shadow_gate() -> None:
    result = build_contract_gate_result(
        [
            _item(check_id="reviewed:partial", text="Partial core", verdict="partial"),
            _item(check_id="reviewed:no", text="No core", verdict="no", evidence=[]),
            _item(
                check_id="reviewed:missing",
                text="Missing core",
                verdict="",
                result_present=False,
            ),
            _item(check_id="reviewed:empty", text="Empty verdict", verdict=""),
        ]
    )

    assert result["status"] == "failed"
    assert result["would_pass"] is False
    assert result["eligible_count"] == 4
    assert result["satisfied_count"] == 0
    assert result["failed_count"] == 4
    assert result["partial_count"] == 1
    assert result["no_count"] == 1
    assert result["missing_count"] == 2
    assert [item["reason"] for item in result["failed_items"]] == [
        "partial",
        "no",
        "missing_result",
        "missing_result",
    ]
    assert result["failed_items"][0]["check_id"] == "reviewed:partial"
    assert result["failed_items"][0]["evidence_count"] == 1


def test_non_reviewed_core_items_are_ignored() -> None:
    result = build_contract_gate_result(
        [
            _item(source="adaptive_context", severity="core", verdict="no"),
            _item(source="reviewed", severity="supporting", verdict="no"),
            _item(source="evaluator_extra", severity="supporting", verdict="no"),
        ]
    )

    assert result["status"] == "not_applicable"
    assert result["would_pass"] is None
    assert result["eligible_count"] == 0
    assert result["failed_items"] == []


def test_empty_or_invalid_items_are_not_applicable() -> None:
    assert build_contract_gate_result([])["status"] == "not_applicable"
    assert build_contract_gate_result(None)["status"] == "not_applicable"
    assert build_contract_gate_result(["not-a-dict"])["status"] == "not_applicable"


def test_resolve_contract_gate_mode_prefers_runtime_config() -> None:
    mode, warnings = resolve_contract_gate_mode(
        runtime_config={"contract_gate_mode": "enforce"},
        settings=SimpleNamespace(contract_gate_mode="shadow"),
    )

    assert mode == "enforce"
    assert warnings == []


def test_resolve_contract_gate_mode_invalid_value_falls_back_to_shadow() -> None:
    mode, warnings = resolve_contract_gate_mode(
        runtime_config={"contract_gate_mode": "loud"},
        settings=SimpleNamespace(contract_gate_mode="enforce"),
    )

    assert mode == "shadow"
    assert warnings == ["invalid_contract_gate_mode_fallback"]


def test_shadow_mode_does_not_enforce_failed_gate() -> None:
    evaluation = {
        "score": 9.0,
        "passed": True,
        "recommended_next": "advance",
        "recommended_next_plan": None,
    }
    gate = build_contract_gate_result(
        [_item(check_id="reviewed:rollback", text="Mentions rollback.", verdict="no")],
        mode="shadow",
    )

    updated = apply_contract_gate_enforcement(evaluation, gate, mode="shadow")

    assert updated == evaluation
    assert "contract_gate_enforced" not in updated


def test_enforce_mode_forces_failed_reviewed_core_to_deep_probe() -> None:
    evaluation = {
        "score": 9.0,
        "passed": True,
        "recommended_next": "advance",
        "recommended_next_plan": None,
        "weaknesses": ["existing gap"],
        "failure_categories": ["existing_category"],
    }
    gate = build_contract_gate_result(
        [
            _item(
                check_id="reviewed:rollback",
                text="Mentions rollback plan.",
                verdict="partial",
            ),
            _item(
                check_id="reviewed:risk",
                text="Names a concrete risk.",
                verdict="no",
                evidence=[],
            ),
        ],
        mode="enforce",
    )

    updated = apply_contract_gate_enforcement(evaluation, gate, mode="enforce")

    assert updated["score"] == 9.0
    assert updated["passed"] is False
    assert updated["recommended_next"] == "refine"
    assert updated["recommended_next_plan"] == "deep_probe"
    assert updated["contract_gate_enforced"] is True
    assert updated["contract_gate_enforcement_reason"] == "reviewed_core_failed"
    assert updated["contract_gate_failed_count"] == 2
    assert updated["contract_gate_failed_check_ids"] == [
        "reviewed:rollback",
        "reviewed:risk",
    ]
    assert "contract_gate_reviewed_core_failed" in updated["failure_categories"]
    assert any("Mentions rollback plan." in item for item in updated["weaknesses"])
    assert any("Names a concrete risk." in item for item in updated["weaknesses"])


def test_enforce_mode_does_not_change_passed_or_not_applicable_gate() -> None:
    evaluation = {
        "score": 8.0,
        "passed": True,
        "recommended_next": "advance",
    }

    passed_gate = build_contract_gate_result([_item()], mode="enforce")
    not_applicable_gate = build_contract_gate_result(
        [_item(source="adaptive_context", severity="supporting", verdict="no")],
        mode="enforce",
    )

    assert apply_contract_gate_enforcement(
        evaluation, passed_gate, mode="enforce"
    ) == evaluation
    assert apply_contract_gate_enforcement(
        evaluation, not_applicable_gate, mode="enforce"
    ) == evaluation
