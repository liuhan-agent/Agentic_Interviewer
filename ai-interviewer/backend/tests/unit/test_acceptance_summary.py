from __future__ import annotations

from app.engine.contracts.acceptance_summary import build_contract_semantics_summary


def _item(
    *,
    text: str,
    source: str,
    severity: str,
    verdict: str = "",
    result_present: bool = True,
    check_id: str | None = None,
) -> dict:
    return {
        "check_id": check_id or f"{source}:{severity}:{text}",
        "text": text,
        "source": source,
        "severity": severity,
        "verdict": verdict,
        "result_present": result_present,
        "evidence": ["quote"] if verdict else [],
    }


def test_contract_semantics_summary_groups_hard_soft_and_context_gaps() -> None:
    summary = build_contract_semantics_summary(
        [
            _item(
                text="core yes",
                source="reviewed",
                severity="core",
                verdict="yes",
            ),
            _item(
                text="core partial",
                source="reviewed",
                severity="core",
                verdict="partial",
            ),
            _item(
                text="core no",
                source="reviewed",
                severity="core",
                verdict="no",
            ),
            _item(
                text="core missing",
                source="reviewed",
                severity="core",
                verdict="",
                result_present=False,
            ),
            _item(
                text="supporting partial",
                source="reviewed",
                severity="supporting",
                verdict="partial",
            ),
            _item(
                text="supporting no",
                source="reviewed",
                severity="supporting",
                verdict="no",
            ),
            _item(
                text="context no",
                source="adaptive_context",
                severity="supporting",
                verdict="no",
            ),
            _item(
                text="extra observation",
                source="evaluator_extra",
                severity="supporting",
                verdict="no",
            ),
        ]
    )

    assert summary["reviewed_core"]["total"] == 4
    assert summary["reviewed_core"]["yes"] == 1
    assert summary["reviewed_core"]["partial"] == 1
    assert summary["reviewed_core"]["no"] == 1
    assert summary["reviewed_core"]["missing"] == 1
    assert [item["text"] for item in summary["reviewed_core"]["failed_items"]] == [
        "core partial",
        "core no",
        "core missing",
    ]
    assert summary["hard_gap_count"] == 3

    assert summary["reviewed_supporting"]["total"] == 2
    assert summary["reviewed_supporting"]["partial"] == 1
    assert summary["reviewed_supporting"]["no"] == 1
    assert [item["text"] for item in summary["reviewed_supporting"]["gap_items"]] == [
        "supporting partial",
        "supporting no",
    ]
    assert summary["soft_quality_gap_count"] == 2

    assert summary["adaptive_context"]["total"] == 1
    assert summary["adaptive_context"]["no"] == 1
    assert summary["adaptive_context"]["gap_items"][0]["text"] == "context no"
    assert summary["context_gap_count"] == 1

    assert summary["evaluator_extra"]["total"] == 1
    assert summary["evaluator_extra"]["items"][0]["text"] == "extra observation"


def test_contract_semantics_summary_treats_missing_result_as_gap() -> None:
    summary = build_contract_semantics_summary(
        [
            _item(
                text="supporting missing",
                source="reviewed",
                severity="supporting",
                result_present=False,
            ),
            _item(
                text="context missing",
                source="adaptive_context",
                severity="supporting",
                result_present=False,
            ),
        ]
    )

    assert summary["reviewed_supporting"]["missing"] == 1
    assert summary["reviewed_supporting"]["gap_items"][0]["reason"] == (
        "missing_result"
    )
    assert summary["adaptive_context"]["missing"] == 1
    assert summary["adaptive_context"]["gap_items"][0]["reason"] == "missing_result"
    assert summary["soft_quality_gap_count"] == 1
    assert summary["context_gap_count"] == 1


def test_contract_semantics_summary_returns_empty_shape_for_no_items() -> None:
    summary = build_contract_semantics_summary(None)

    assert summary["reviewed_core"]["total"] == 0
    assert summary["reviewed_supporting"]["total"] == 0
    assert summary["adaptive_context"]["total"] == 0
    assert summary["evaluator_extra"]["total"] == 0
    assert summary["hard_gap_count"] == 0
    assert summary["soft_quality_gap_count"] == 0
    assert summary["context_gap_count"] == 0


def test_contract_semantics_summary_ignores_unknown_sources() -> None:
    summary = build_contract_semantics_summary(
        [
            _item(
                text="compiled no",
                source="compiled_fallback",
                severity="core",
                verdict="no",
            )
        ]
    )

    assert summary["reviewed_core"]["total"] == 0
    assert summary["reviewed_supporting"]["total"] == 0
    assert summary["adaptive_context"]["total"] == 0
    assert summary["evaluator_extra"]["total"] == 0
