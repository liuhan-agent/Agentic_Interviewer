from __future__ import annotations

from app.engine.contracts.training_suggestions import (
    build_soft_gap_training_suggestions,
)


def _gap(
    *,
    text: str,
    source: str,
    verdict: str,
    check_id: str,
    reason: str | None = None,
    evidence: list[str] | None = None,
) -> dict:
    return {
        "check_id": check_id,
        "text": text,
        "source": source,
        "severity": "supporting",
        "verdict": verdict,
        "reason": reason or verdict,
        "result_present": verdict != "",
        "evidence": list(evidence or []),
        "evidence_count": len(evidence or []),
    }


def test_reviewed_supporting_gaps_generate_quality_suggestions() -> None:
    summary = {
        "reviewed_core": {
            "failed_items": [
                _gap(
                    text="Core item must not become a soft suggestion.",
                    source="reviewed",
                    verdict="no",
                    check_id="reviewed:core",
                )
            ]
        },
        "reviewed_supporting": {
            "gap_items": [
                _gap(
                    text="Explains idempotent compensation.",
                    source="reviewed",
                    verdict="partial",
                    check_id="reviewed:support:idempotency",
                    evidence=["mentioned retry"],
                ),
                _gap(
                    text="Shows reconciliation monitoring.",
                    source="reviewed",
                    verdict="no",
                    check_id="reviewed:support:reconcile",
                ),
                _gap(
                    text="Missing result is treated as a soft gap.",
                    source="reviewed",
                    verdict="",
                    check_id="reviewed:support:missing",
                    reason="missing_result",
                ),
            ]
        },
        "adaptive_context": {"gap_items": []},
    }

    suggestions = build_soft_gap_training_suggestions(summary)

    assert suggestions["present"] is True
    assert suggestions["source"] == "contract_semantics_summary"
    assert suggestions["counts"] == {"quality": 3, "context": 0, "total": 3}
    quality = suggestions["quality_suggestions"]
    assert [item["check_id"] for item in quality] == [
        "reviewed:support:idempotency",
        "reviewed:support:reconcile",
        "reviewed:support:missing",
    ]
    assert quality[0]["source"] == "reviewed_supporting"
    assert quality[0]["severity"] == "supporting"
    assert quality[0]["verdict"] == "partial"
    assert quality[0]["evidence"] == ["mentioned retry"]
    assert "Core item" not in str(suggestions)


def test_adaptive_context_gaps_generate_context_suggestions() -> None:
    summary = {
        "reviewed_supporting": {"gap_items": []},
        "adaptive_context": {
            "gap_items": [
                _gap(
                    text="Connects the answer to the payment migration project.",
                    source="adaptive_context",
                    verdict="no",
                    check_id="adaptive:payment-migration",
                ),
                _gap(
                    text="Uses the JD scale target in the tradeoff.",
                    source="adaptive_context",
                    verdict="partial",
                    check_id="adaptive:jd-scale",
                    evidence=["mentions scale"],
                ),
            ]
        },
    }

    suggestions = build_soft_gap_training_suggestions(summary)

    assert suggestions["present"] is True
    assert suggestions["counts"] == {"quality": 0, "context": 2, "total": 2}
    context = suggestions["context_suggestions"]
    assert [item["source"] for item in context] == [
        "adaptive_context",
        "adaptive_context",
    ]
    assert context[0]["title"].startswith("Context gap")
    assert context[1]["evidence"] == ["mentions scale"]


def test_yes_results_and_core_items_do_not_generate_soft_suggestions() -> None:
    summary = {
        "reviewed_core": {
            "failed_items": [
                _gap(
                    text="Core no stays in the hard gate lane.",
                    source="reviewed",
                    verdict="no",
                    check_id="reviewed:core:no",
                )
            ]
        },
        "reviewed_supporting": {
            "gap_items": [
                _gap(
                    text="A malformed yes gap is ignored defensively.",
                    source="reviewed",
                    verdict="yes",
                    check_id="reviewed:support:yes",
                )
            ]
        },
        "adaptive_context": {"gap_items": []},
    }

    suggestions = build_soft_gap_training_suggestions(summary)

    assert suggestions["present"] is False
    assert suggestions["quality_suggestions"] == []
    assert suggestions["context_suggestions"] == []
    assert suggestions["counts"] == {"quality": 0, "context": 0, "total": 0}


def test_empty_summary_returns_compatible_empty_shape() -> None:
    suggestions = build_soft_gap_training_suggestions({})

    assert suggestions == {
        "present": False,
        "source": "contract_semantics_summary",
        "quality_suggestions": [],
        "context_suggestions": [],
        "counts": {"quality": 0, "context": 0, "total": 0},
    }


def test_suggestion_id_is_stable() -> None:
    summary = {
        "reviewed_supporting": {
            "gap_items": [
                _gap(
                    text="Explains idempotent compensation.",
                    source="reviewed",
                    verdict="partial",
                    check_id="reviewed:support:idempotency",
                )
            ]
        },
        "adaptive_context": {"gap_items": []},
    }

    first = build_soft_gap_training_suggestions(summary)
    second = build_soft_gap_training_suggestions(summary)

    assert (
        first["quality_suggestions"][0]["suggestion_id"]
        == second["quality_suggestions"][0]["suggestion_id"]
    )
