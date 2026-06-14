from types import SimpleNamespace

from app.engine.contracts.contract_score import (
    build_contract_pass_shadow,
    build_contract_score_shadow,
    resolve_evaluator_score_mode,
)


def _item(
    *,
    source: str,
    severity: str,
    verdict: str,
    evidence: list[str] | None = None,
    result_present: bool = True,
) -> dict:
    return {
        "check_id": f"{source}:{severity}:{verdict}",
        "text": f"{source} {severity} {verdict}",
        "source": source,
        "severity": severity,
        "verdict": verdict,
        "evidence": list(evidence or []),
        "result_present": result_present,
    }


def test_contract_score_shadow_weights_reviewed_and_dynamic_checks() -> None:
    result = build_contract_score_shadow(
        {
            "score": 8.5,
            "acceptance_check_result_items": [
                _item(
                    source="reviewed",
                    severity="core",
                    verdict="yes",
                    evidence=["事务边界"],
                ),
                _item(
                    source="reviewed",
                    severity="core",
                    verdict="partial",
                    evidence=["幂等键"],
                ),
                _item(source="reviewed", severity="core", verdict="no"),
                _item(
                    source="reviewed",
                    severity="supporting",
                    verdict="yes",
                    evidence=["核心不变量"],
                ),
                _item(
                    source="adaptive_context",
                    severity="supporting",
                    verdict="partial",
                    evidence=["支付项目"],
                ),
            ],
        }
    )

    assert result["score_source"] == "llm"
    assert result["llm_score"] == 8.5
    assert result["final_score"] == 8.5
    assert result["contract_score"] == 6.5
    assert result["contract_score_mode"] == "shadow"
    assert result["contract_score_breakdown"]["reviewed_core"]["raw_score"] == 0.5
    assert result["contract_score_breakdown"]["reviewed_supporting"]["raw_score"] == 1.0
    assert result["contract_score_breakdown"]["adaptive_context"]["raw_score"] == 0.5
    assert result["contract_score_breakdown"]["evidence_quality"]["raw_score"] == 1.0


def test_contract_score_shadow_uses_compiled_fallback_when_reviewed_missing() -> None:
    result = build_contract_score_shadow(
        {
            "score": 7.0,
            "acceptance_check_result_items": [
                _item(
                    source="compiled_fallback",
                    severity="core",
                    verdict="yes",
                    evidence=["事务边界"],
                ),
                _item(
                    source="compiled_fallback",
                    severity="supporting",
                    verdict="partial",
                    evidence=["补偿修复"],
                ),
            ],
        }
    )

    assert result["contract_score"] == 8.89
    assert result["contract_score_breakdown"]["structured_source"] == (
        "compiled_fallback"
    )
    assert result["contract_score_breakdown"]["reviewed_core"]["available"] is False
    assert result["contract_score_breakdown"]["fallback_core"]["raw_score"] == 1.0
    assert result["contract_score_breakdown"]["fallback_supporting"]["raw_score"] == 0.5


def test_contract_score_shadow_is_unavailable_without_acceptance_items() -> None:
    result = build_contract_score_shadow({"score": 6.0})

    assert result["score_source"] == "llm"
    assert result["llm_score"] == 6.0
    assert result["final_score"] == 6.0
    assert result["contract_score"] is None
    assert result["contract_score_mode"] == "unavailable"
    assert result["contract_score_breakdown"]["available"] is False


def test_contract_score_uses_rubric_coverage_as_core_fallback() -> None:
    result = build_contract_score_shadow(
        {
            "score": 7.0,
            "rubric_coverage": {
                "事务边界": "covered",
                "幂等控制": "partial",
                "异步补偿": "missing",
            },
        }
    )

    breakdown = result["contract_score_breakdown"]

    assert result["contract_score"] == 5.0
    assert breakdown["available"] is True
    assert breakdown["structured_source"] == "rubric_coverage"
    assert breakdown["rubric_core"]["raw_score"] == 0.5
    assert breakdown["rubric_core"]["covered"] == 1
    assert breakdown["rubric_core"]["partial"] == 1
    assert breakdown["rubric_core"]["missing"] == 1
    assert breakdown["active_buckets"]["structured_core"] == breakdown["rubric_core"]


def test_contract_score_prefers_structured_core_over_rubric_coverage() -> None:
    result = build_contract_score_shadow(
        {
            "score": 7.0,
            "rubric_coverage": {
                "事务边界": "missing",
                "幂等控制": "missing",
            },
            "acceptance_check_result_items": [
                _item(
                    source="reviewed",
                    severity="core",
                    verdict="yes",
                    evidence=["事务边界"],
                ),
            ],
        }
    )

    breakdown = result["contract_score_breakdown"]

    assert result["contract_score"] == 10.0
    assert breakdown["structured_source"] == "reviewed"
    assert breakdown["rubric_core"]["available"] is False
    assert breakdown["active_buckets"]["structured_core"] == breakdown["reviewed_core"]


def test_contract_score_hybrid_mode_can_take_over_score_field() -> None:
    result = build_contract_score_shadow(
        {
            "score": 8.5,
            "acceptance_check_result_items": [
                _item(
                    source="reviewed",
                    severity="core",
                    verdict="yes",
                    evidence=["事务边界"],
                ),
                _item(
                    source="reviewed",
                    severity="core",
                    verdict="partial",
                    evidence=["幂等键"],
                ),
            ],
        },
        evaluator_score_mode="hybrid",
    )

    assert result["evaluator_score_mode"] == "hybrid"
    assert result["llm_score"] == 8.5
    assert result["contract_score"] == 7.86
    assert result["score"] == 8.05
    assert result["final_score"] == 8.05
    assert result["score_source"] == "hybrid"
    assert result["score_mode_warnings"] == []


def test_contract_score_contract_mode_can_take_over_score_field() -> None:
    result = build_contract_score_shadow(
        {
            "score": 8.5,
            "acceptance_check_result_items": [
                _item(
                    source="reviewed",
                    severity="core",
                    verdict="yes",
                    evidence=["事务边界"],
                ),
                _item(
                    source="reviewed",
                    severity="core",
                    verdict="partial",
                    evidence=["幂等键"],
                ),
            ],
        },
        evaluator_score_mode="contract",
    )

    assert result["evaluator_score_mode"] == "contract"
    assert result["llm_score"] == 8.5
    assert result["contract_score"] == 7.86
    assert result["score"] == 7.86
    assert result["final_score"] == 7.86
    assert result["score_source"] == "contract"
    assert result["score_mode_warnings"] == []


def test_contract_score_mode_falls_back_to_llm_when_contract_score_unavailable() -> None:
    result = build_contract_score_shadow(
        {"score": 6.0},
        evaluator_score_mode="contract",
    )

    assert result["evaluator_score_mode"] == "llm"
    assert result["score"] == 6.0
    assert result["final_score"] == 6.0
    assert result["score_source"] == "llm"
    assert result["contract_score"] is None
    assert "contract_score_unavailable_fallback_llm" in result["score_mode_warnings"]


def test_contract_score_reuses_existing_llm_score_when_recomputed() -> None:
    first = build_contract_score_shadow(
        {
            "score": 8.5,
            "acceptance_check_result_items": [
                _item(
                    source="reviewed",
                    severity="core",
                    verdict="yes",
                    evidence=["事务边界"],
                ),
                _item(
                    source="reviewed",
                    severity="core",
                    verdict="partial",
                    evidence=["幂等键"],
                ),
            ],
        },
        evaluator_score_mode="hybrid",
    )
    second = build_contract_score_shadow(
        {
            **first,
            "acceptance_check_result_items": [
                _item(
                    source="reviewed",
                    severity="core",
                    verdict="yes",
                    evidence=["事务边界"],
                ),
                _item(
                    source="reviewed",
                    severity="core",
                    verdict="partial",
                    evidence=["幂等键"],
                ),
            ],
        },
        evaluator_score_mode="hybrid",
    )

    assert first["score"] == 8.05
    assert second["llm_score"] == 8.5
    assert second["score"] == 8.05


def test_contract_pass_shadow_flags_pass_and_routing_diff_without_mutating() -> None:
    result = build_contract_pass_shadow(
        {
            "passed": True,
            "recommended_next": "advance",
            "recommended_next_plan": None,
            "contract_score": 5.71,
        },
        quality_threshold=7.5,
    )

    assert result["contract_passed_shadow"] is False
    assert result["contract_recommended_next_shadow"] == "refine"
    assert result["contract_recommended_next_plan_shadow"] == "deep_probe"
    assert result["contract_pass_shadow_reason"] == "contract_score_below_threshold"
    assert result["contract_pass_shadow_diff"] is True
    assert result["contract_routing_signal_shadow_diff"] is True
    assert result["contract_pass_shadow"]["legacy_passed"] is True


def test_contract_pass_shadow_keeps_gate_failure_from_passing_high_score() -> None:
    result = build_contract_pass_shadow(
        {
            "passed": False,
            "recommended_next": "refine",
            "recommended_next_plan": "deep_probe",
            "contract_score": 8.92,
            "contract_gate_result": {
                "mode": "enforce",
                "status": "failed",
                "failed_items": [{"check_id": "reviewed:core:async_compensation:v1"}],
            },
            "contract_gate_enforced": True,
            "contract_gate_failed_check_ids": [
                "reviewed:core:async_compensation:v1",
            ],
        },
        quality_threshold=7.0,
    )

    assert result["contract_passed_shadow"] is False
    assert result["contract_recommended_next_shadow"] == "refine"
    assert result["contract_recommended_next_plan_shadow"] == "deep_probe"
    assert result["contract_pass_shadow_reason"] == "contract_gate_failed"
    assert result["contract_pass_shadow_diff"] is False
    assert result["contract_routing_signal_shadow_diff"] is False
    assert result["contract_pass_shadow"]["gate_status"] == "failed"
    assert result["contract_pass_shadow"]["gate_failed_check_ids"] == [
        "reviewed:core:async_compensation:v1",
    ]


def test_contract_pass_shadow_is_unavailable_without_contract_score() -> None:
    result = build_contract_pass_shadow(
        {"passed": True, "recommended_next": "advance"},
        quality_threshold=7.5,
    )

    assert result["contract_pass_shadow"]["available"] is False
    assert result["contract_passed_shadow"] is None
    assert result["contract_pass_shadow_reason"] == "contract_score_unavailable"


def test_resolve_evaluator_score_mode_prefers_runtime_and_falls_back() -> None:
    mode, warnings = resolve_evaluator_score_mode(
        runtime_config={"evaluator_score_mode": "hybrid"},
        settings=SimpleNamespace(evaluator_score_mode="contract"),
    )

    assert mode == "hybrid"
    assert warnings == []

    mode, warnings = resolve_evaluator_score_mode(
        runtime_config={"evaluator_score_mode": "surprise"},
        settings=SimpleNamespace(evaluator_score_mode="contract"),
    )

    assert mode == "llm"
    assert warnings == ["invalid_evaluator_score_mode_fallback"]
