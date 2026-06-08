from app.engine.contracts.gate_calibration import build_gate_calibration_summary


def test_high_score_partial_only_gate_failure_is_flagged() -> None:
    summary = build_gate_calibration_summary(
        score=9.0,
        passed=False,
        contract_gate_result={
            "mode": "enforce",
            "status": "failed",
            "eligible_count": 3,
            "satisfied_count": 2,
            "failed_count": 1,
            "partial_count": 1,
            "no_count": 0,
            "missing_count": 0,
            "failed_items": [
                {
                    "check_id": "reviewed:compensation",
                    "text": "Explains compensation boundaries.",
                    "verdict": "partial",
                    "reason": "partial",
                    "result_present": True,
                    "evidence_count": 1,
                }
            ],
        },
    )

    assert summary["present"] is True
    assert summary["mode"] == "audit"
    assert summary["score_band"] == "high"
    assert summary["signals"] == [
        "high_score_gate_failed",
        "partial_only_gate_failed",
    ]
    assert summary["high_score_gate_failed"] is True
    assert summary["partial_only_gate_failed"] is True
    assert summary["hard_failure_gate_failed"] is False
    assert summary["reviewed_core"]["yes"] == 2
    assert summary["reviewed_core"]["partial"] == 1
    assert summary["failed_check_ids"] == ["reviewed:compensation"]
    assert summary["partial_check_ids"] == ["reviewed:compensation"]


def test_no_or_missing_failures_are_hard_failure_signals() -> None:
    summary = build_gate_calibration_summary(
        score=7.2,
        passed=False,
        contract_gate_result={
            "mode": "enforce",
            "status": "failed",
            "eligible_count": 4,
            "satisfied_count": 1,
            "failed_count": 3,
            "partial_count": 1,
            "no_count": 1,
            "missing_count": 1,
            "failed_items": [
                {"check_id": "reviewed:rollback", "verdict": "partial"},
                {"check_id": "reviewed:metrics", "verdict": "no"},
                {
                    "check_id": "reviewed:recovery",
                    "verdict": "",
                    "reason": "missing_result",
                },
            ],
        },
    )

    assert summary["score_band"] == "standard"
    assert summary["signals"] == ["hard_failure_gate_failed"]
    assert summary["partial_only_gate_failed"] is False
    assert summary["hard_failure_gate_failed"] is True
    assert summary["reviewed_core"]["no"] == 1
    assert summary["reviewed_core"]["missing"] == 1
    assert summary["no_check_ids"] == ["reviewed:metrics"]
    assert summary["missing_check_ids"] == ["reviewed:recovery"]


def test_passed_or_not_applicable_gate_is_observed_without_risk_signal() -> None:
    passed = build_gate_calibration_summary(
        score=8.5,
        passed=True,
        contract_gate_result={
            "mode": "enforce",
            "status": "passed",
            "eligible_count": 2,
            "satisfied_count": 2,
            "failed_count": 0,
            "partial_count": 0,
            "no_count": 0,
            "missing_count": 0,
            "failed_items": [],
        },
    )
    not_applicable = build_gate_calibration_summary(
        score=8.5,
        passed=True,
        contract_gate_result={
            "mode": "enforce",
            "status": "not_applicable",
            "eligible_count": 0,
            "satisfied_count": 0,
            "failed_count": 0,
            "partial_count": 0,
            "no_count": 0,
            "missing_count": 0,
            "failed_items": [],
        },
    )

    assert passed["present"] is True
    assert passed["signals"] == []
    assert passed["score_band"] == "high"
    assert not_applicable["present"] is False
    assert not_applicable["signals"] == []
