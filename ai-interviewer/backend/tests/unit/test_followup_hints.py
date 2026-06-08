from __future__ import annotations

from app.engine.contracts.followup_hints import build_soft_followup_hints


def _suggestion(
    *,
    suggestion_id: str,
    source: str,
    check_id: str,
    text: str,
    verdict: str,
    reason: str | None = None,
    evidence: list[str] | None = None,
) -> dict:
    return {
        "suggestion_id": suggestion_id,
        "source": source,
        "severity": "supporting",
        "check_id": check_id,
        "text": text,
        "title": f"Gap: {text}",
        "description": f"Improve: {text}",
        "verdict": verdict,
        "reason": reason or verdict,
        "evidence": list(evidence or []),
        "evidence_count": len(evidence or []),
        "result_present": verdict != "",
    }


def test_quality_suggestions_generate_shadow_quality_hints() -> None:
    hints = build_soft_followup_hints(
        {
            "present": True,
            "quality_suggestions": [
                _suggestion(
                    suggestion_id="soft_gap:quality",
                    source="reviewed_supporting",
                    check_id="reviewed:support:idempotency",
                    text="Explains idempotent compensation.",
                    verdict="partial",
                    evidence=["mentioned retry"],
                )
            ],
            "context_suggestions": [],
        }
    )

    assert hints["present"] is True
    assert hints["mode"] == "shadow"
    assert hints["applied"] is False
    assert hints["source"] == "soft_gap_training_suggestions"
    assert hints["counts"] == {"quality": 1, "context": 0, "total": 1}
    assert hints["quality_hints"][0]["intent"] == "probe_quality_gap"
    assert hints["quality_hints"][0]["source"] == "reviewed_supporting"
    assert hints["quality_hints"][0]["check_id"] == (
        "reviewed:support:idempotency"
    )
    assert hints["quality_hints"][0]["evidence"] == ["mentioned retry"]
    assert hints["priority_order"] == [hints["quality_hints"][0]["hint_id"]]


def test_context_suggestions_generate_shadow_context_hints() -> None:
    hints = build_soft_followup_hints(
        {
            "present": True,
            "quality_suggestions": [],
            "context_suggestions": [
                _suggestion(
                    suggestion_id="soft_gap:context",
                    source="adaptive_context",
                    check_id="adaptive:resume:payment-project",
                    text="Connects the answer to the payment migration project.",
                    verdict="no",
                )
            ],
        }
    )

    assert hints["counts"] == {"quality": 0, "context": 1, "total": 1}
    assert hints["context_hints"][0]["intent"] == "probe_context_gap"
    assert hints["context_hints"][0]["source"] == "adaptive_context"
    assert hints["context_hints"][0]["focus"].startswith("Probe context gap")
    assert hints["priority_order"] == [hints["context_hints"][0]["hint_id"]]


def test_empty_suggestions_return_shadow_empty_shape() -> None:
    hints = build_soft_followup_hints({})

    assert hints == {
        "present": False,
        "mode": "shadow",
        "applied": False,
        "source": "soft_gap_training_suggestions",
        "quality_hints": [],
        "context_hints": [],
        "priority_order": [],
        "counts": {"quality": 0, "context": 0, "total": 0},
    }


def test_hint_id_is_stable() -> None:
    suggestions = {
        "present": True,
        "quality_suggestions": [
            _suggestion(
                suggestion_id="soft_gap:quality",
                source="reviewed_supporting",
                check_id="reviewed:support:idempotency",
                text="Explains idempotent compensation.",
                verdict="partial",
            )
        ],
        "context_suggestions": [
            _suggestion(
                suggestion_id="soft_gap:context",
                source="adaptive_context",
                check_id="adaptive:resume:payment-project",
                text="Connects the answer to the payment migration project.",
                verdict="no",
            )
        ],
    }

    first = build_soft_followup_hints(suggestions)
    second = build_soft_followup_hints(suggestions)

    assert first["priority_order"] == second["priority_order"]
    assert first["quality_hints"][0]["hint_id"] == (
        second["quality_hints"][0]["hint_id"]
    )
    assert first["context_hints"][0]["hint_id"] == (
        second["context_hints"][0]["hint_id"]
    )
