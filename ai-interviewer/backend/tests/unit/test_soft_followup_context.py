from __future__ import annotations

from app.engine.contracts.soft_followup_context import (
    build_soft_followup_advisory_payload,
    build_soft_followup_context,
)


def _hint(
    hint_id: str,
    *,
    hint_type: str,
    text: str,
    check_id: str | None = None,
) -> dict:
    return {
        "hint_id": hint_id,
        "suggestion_id": f"suggestion:{hint_id}",
        "source": "reviewed_supporting"
        if hint_type == "quality"
        else "adaptive_context",
        "intent": "probe_quality_gap"
        if hint_type == "quality"
        else "probe_context_gap",
        "check_id": check_id or f"check:{hint_id}",
        "verdict": "partial",
        "reason": "partial",
        "text": text,
        "focus": f"Probe {text}",
        "evidence_count": 1,
    }


def _soft_hints(
    *,
    quality: list[dict] | None = None,
    context: list[dict] | None = None,
    mode: str = "shadow",
    applied: bool = False,
    total: int | None = None,
) -> dict:
    quality = list(quality or [])
    context = list(context or [])
    priority_order = [
        item["hint_id"]
        for item in [*quality, *context]
        if item.get("hint_id")
    ]
    return {
        "present": bool(priority_order),
        "mode": mode,
        "applied": applied,
        "quality_hints": quality,
        "context_hints": context,
        "priority_order": priority_order,
        "counts": {
            "quality": len(quality),
            "context": len(context),
            "total": len(priority_order) if total is None else total,
        },
    }


def _selection_artifacts(seed_id: str, variant_id: str) -> dict:
    return {
        "question_items": [
            {
                "seed_id": seed_id,
                "variant_id": variant_id,
                "rank": 1,
                "injected": True,
            }
        ]
    }


def test_default_off_returns_disabled_empty_payload() -> None:
    context = build_soft_followup_context(
        qa_history=[],
        current_dimension="system_design",
        ask_plan={"template": "deep_probe"},
    )

    assert context["present"] is False
    assert context["mode"] == "off"
    assert context["applied"] is False
    assert context["counts"] == {"quality": 0, "context": 0, "total": 0}
    assert context["selected_hint_ids"] == []
    assert context["not_applied_reason"] == "disabled"
    assert context["empty_reason"] == "disabled"
    assert context["constraints"]["advisory_only"] is True


def test_shadow_empty_history_returns_empty_shadow_payload() -> None:
    context = build_soft_followup_context(
        qa_history=[],
        current_dimension="system_design",
        ask_plan={"template": "deep_probe"},
        prompt_mode="shadow",
    )

    assert context["present"] is False
    assert context["mode"] == "shadow"
    assert context["applied"] is False
    assert context["not_applied_reason"] == "prompt_shadow"
    assert context["empty_reason"] == "no_history"


def test_selects_at_most_one_quality_and_one_context_hint() -> None:
    quality_1 = _hint("quality-1", hint_type="quality", text="add retry boundary")
    quality_2 = _hint("quality-2", hint_type="quality", text="add alert owner")
    context_1 = _hint("context-1", hint_type="context", text="tie to resume project")
    context_2 = _hint("context-2", hint_type="context", text="tie to JD scale")

    context = build_soft_followup_context(
        qa_history=[
            {
                "turn_idx": 3,
                "dimension": "system_design",
                "evaluation": {
                    "soft_followup_hints": _soft_hints(
                        quality=[quality_1, quality_2],
                        context=[context_1, context_2],
                    )
                },
            }
        ],
        current_dimension="system_design",
        ask_plan={"template": "deep_probe"},
        prompt_mode="shadow",
    )

    assert context["present"] is True
    assert context["eligible_count"] == 4
    assert context["counts"] == {"quality": 1, "context": 1, "total": 2}
    assert context["selected_hint_ids"] == ["quality-1", "context-1"]
    assert context["quality_hints"][0]["source_turn_idx"] == 3
    assert context["quality_hints"][0]["source_dimension"] == "system_design"
    assert context["context_hints"][0]["hint_id"] == "context-1"
    assert context["not_applied_reason"] == "prompt_shadow"


def test_requires_shadow_mode_unapplied_and_positive_total_count() -> None:
    context = build_soft_followup_context(
        qa_history=[
            {
                "turn_idx": 1,
                "dimension": "system_design",
                "evaluation": {
                    "soft_followup_hints": _soft_hints(
                        quality=[_hint("bad-mode", hint_type="quality", text="x")],
                        mode="applied",
                    )
                },
            },
            {
                "turn_idx": 2,
                "dimension": "system_design",
                "evaluation": {
                    "soft_followup_hints": _soft_hints(
                        quality=[_hint("already-used", hint_type="quality", text="x")],
                        applied=True,
                    )
                },
            },
            {
                "turn_idx": 3,
                "dimension": "system_design",
                "evaluation": {
                    "soft_followup_hints": _soft_hints(
                        quality=[_hint("empty-count", hint_type="quality", text="x")],
                        total=0,
                    )
                },
            },
        ],
        current_dimension="system_design",
        ask_plan={"template": "deep_probe"},
        prompt_mode="shadow",
    )

    assert context["present"] is False
    assert context["considered_count"] == 0
    assert context["eligible_count"] == 0
    assert context["empty_reason"] == "no_valid_shadow_hints"
    assert context["rejected_reasons"] == {
        "empty_counts": 1,
        "already_applied": 1,
        "non_shadow_mode": 1,
    }


def test_filters_by_dimension_and_refine_compatible_plan() -> None:
    hints = _soft_hints(
        quality=[_hint("quality-1", hint_type="quality", text="add retry boundary")]
    )

    wrong_plan = build_soft_followup_context(
        qa_history=[
            {
                "turn_idx": 1,
                "dimension": "system_design",
                "evaluation": {"soft_followup_hints": hints},
            }
        ],
        current_dimension="system_design",
        ask_plan={"template": "adaptive"},
        refine_mode=False,
        prompt_mode="shadow",
    )
    assert wrong_plan["present"] is False
    assert wrong_plan["empty_reason"] == "plan_not_refine_or_deep_probe"

    wrong_dimension = build_soft_followup_context(
        qa_history=[
            {
                "turn_idx": 1,
                "dimension": "system_design",
                "evaluation": {"soft_followup_hints": hints},
            }
        ],
        current_dimension="coding_quality",
        ask_plan={"template": "deep_probe"},
        prompt_mode="shadow",
    )
    assert wrong_dimension["present"] is False
    assert wrong_dimension["rejected_reasons"] == {"dimension_mismatch": 1}

    refine_mode_context = build_soft_followup_context(
        qa_history=[
            {
                "turn_idx": 1,
                "dimension": "system_design",
                "evaluation": {"soft_followup_hints": hints},
            }
        ],
        current_dimension="system_design",
        ask_plan={"template": "adaptive"},
        refine_mode=True,
        prompt_mode="shadow",
    )
    assert refine_mode_context["present"] is True
    assert refine_mode_context["selected_hint_ids"] == ["quality-1"]


def test_incomplete_hint_shapes_do_not_raise() -> None:
    context = build_soft_followup_context(
        qa_history=[
            {
                "turn_idx": 1,
                "dimension": "system_design",
                "evaluation": {
                    "soft_followup_hints": _soft_hints(
                        quality=[{"hint_id": "quality-only"}],
                        context=[{}],
                    )
                },
            }
        ],
        current_dimension="system_design",
        ask_plan={"template": "deep_probe"},
        prompt_mode="shadow",
    )

    assert context["present"] is True
    assert context["selected_hint_ids"] == ["quality-only"]
    assert context["quality_hints"][0]["text"] == ""
    assert context["quality_hints"][0]["hint_id"] == "quality-only"


def test_advisory_mode_compiles_prompt_safe_payload() -> None:
    context = build_soft_followup_context(
        qa_history=[
            {
                "turn_idx": 4,
                "dimension": "system_design",
                "evaluation": {
                    "soft_followup_hints": _soft_hints(
                        quality=[
                            _hint(
                                "quality-1",
                                hint_type="quality",
                                text="add retry boundary " * 20,
                            )
                        ],
                        context=[
                            _hint(
                                "context-1",
                                hint_type="context",
                                text="tie to resume project",
                            )
                        ],
                    )
                },
            }
        ],
        current_dimension="system_design",
        ask_plan={"template": "deep_probe"},
        prompt_mode="advisory",
    )

    assert context["mode"] == "advisory"
    assert context["present"] is True
    assert context["applied"] is False
    assert context["not_applied_reason"] == "pending_prompt_apply"
    payload = build_soft_followup_advisory_payload(context, text_limit=48)
    assert payload is not None
    assert payload["mode"] == "advisory"
    assert payload["advisory_only"] is True
    assert payload["do_not_override_seed"] is True
    assert len(payload["quality_hints"]) == 1
    assert len(payload["context_hints"]) == 1
    assert payload["quality_hints"][0]["hint_id"] == "quality-1"
    assert len(payload["quality_hints"][0]["focus"]) <= 48
    assert payload["context_hints"][0]["check_id"] == "check:context-1"


def test_topic_affinity_allows_same_seed_different_variant() -> None:
    quality = _hint("quality-1", hint_type="quality", text="add retry boundary")
    context_hint = _hint("context-1", hint_type="context", text="tie to resume")

    context = build_soft_followup_context(
        qa_history=[
            {
                "turn_idx": 2,
                "dimension": "coding_quality",
                "selection_artifacts": _selection_artifacts(
                    "coding_quality.java_service_testability",
                    "coding_quality.java_service_testability.async_job_test",
                ),
                "evaluation": {
                    "soft_followup_hints": _soft_hints(
                        quality=[quality],
                        context=[context_hint],
                    )
                },
            }
        ],
        current_dimension="coding_quality",
        current_question_refs={
            "seed_id": "coding_quality.java_service_testability",
            "variant_id": (
                "coding_quality.java_service_testability."
                "transaction_service_boundary"
            ),
        },
        ask_plan={"template": "deep_probe"},
        prompt_mode="advisory",
    )

    assert context["present"] is True
    assert context["selected_hint_ids"] == ["quality-1", "context-1"]
    assert context["topic_affinity_policy"] == "balanced"
    assert context["topic_affinity_rejected_count"] == 0
    assert context["quality_hints"][0]["topic_affinity"] == "same_seed"
    assert context["quality_hints"][0]["source_seed_id"] == (
        "coding_quality.java_service_testability"
    )
    assert context["quality_hints"][0]["source_variant_id"] == (
        "coding_quality.java_service_testability.async_job_test"
    )


def test_topic_affinity_rejects_same_dimension_different_seed() -> None:
    context = build_soft_followup_context(
        qa_history=[
            {
                "turn_idx": 8,
                "dimension": "coding_quality",
                "selection_artifacts": _selection_artifacts(
                    "coding_quality.java_api_contract_idempotency",
                    "coding_quality.java_api_contract_idempotency.payment_create_retry",
                ),
                "evaluation": {
                    "soft_followup_hints": _soft_hints(
                        quality=[
                            _hint(
                                "quality-1",
                                hint_type="quality",
                                text="explain idempotency key scope",
                            )
                        ],
                        context=[
                            _hint(
                                "context-1",
                                hint_type="context",
                                text="explain API compatibility",
                            )
                        ],
                    )
                },
            }
        ],
        current_dimension="coding_quality",
        current_question_refs={
            "seed_id": "coding_quality.java_service_testability",
            "variant_id": (
                "coding_quality.java_service_testability."
                "transaction_service_boundary"
            ),
        },
        ask_plan={"template": "deep_probe"},
        prompt_mode="advisory",
    )

    assert context["present"] is False
    assert context["selected_hint_ids"] == []
    assert context["eligible_count"] == 0
    assert context["considered_count"] == 2
    assert context["empty_reason"] == "no_eligible_hints"
    assert context["rejected_reasons"] == {"topic_affinity_mismatch": 2}
    assert context["topic_affinity_rejected_count"] == 2
    assert context["topic_affinity_rejected_reasons"] == {
        "topic_affinity_mismatch": 2
    }


def test_topic_affinity_missing_refs_falls_back_to_dimension_filter() -> None:
    context = build_soft_followup_context(
        qa_history=[
            {
                "turn_idx": 3,
                "dimension": "coding_quality",
                "evaluation": {
                    "soft_followup_hints": _soft_hints(
                        quality=[
                            _hint(
                                "quality-1",
                                hint_type="quality",
                                text="add test seam",
                            )
                        ]
                    )
                },
            }
        ],
        current_dimension="coding_quality",
        current_question_refs={
            "seed_id": "coding_quality.java_service_testability",
            "variant_id": (
                "coding_quality.java_service_testability."
                "transaction_service_boundary"
            ),
        },
        ask_plan={"template": "deep_probe"},
        prompt_mode="shadow",
    )

    assert context["present"] is True
    assert context["not_applied_reason"] == "prompt_shadow"
    assert context["selected_hint_ids"] == ["quality-1"]
    assert context["quality_hints"][0]["topic_affinity"] == (
        "dimension_fallback_missing_refs"
    )
    assert context["topic_affinity_rejected_count"] == 0


def test_topic_affinity_ignores_non_injected_history_candidates() -> None:
    context = build_soft_followup_context(
        qa_history=[
            {
                "turn_idx": 3,
                "dimension": "coding_quality",
                "selection_artifacts": {
                    "question_items": [
                        {
                            "seed_id": "coding_quality.java_api_contract_idempotency",
                            "variant_id": (
                                "coding_quality.java_api_contract_idempotency."
                                "payment_create_retry"
                            ),
                            "rank": 1,
                            "injected": False,
                        }
                    ]
                },
                "evaluation": {
                    "soft_followup_hints": _soft_hints(
                        quality=[
                            _hint(
                                "quality-1",
                                hint_type="quality",
                                text="add test seam",
                            )
                        ]
                    )
                },
            }
        ],
        current_dimension="coding_quality",
        current_question_refs={
            "seed_id": "coding_quality.java_service_testability",
            "variant_id": (
                "coding_quality.java_service_testability."
                "transaction_service_boundary"
            ),
        },
        ask_plan={"template": "deep_probe"},
        prompt_mode="shadow",
    )

    assert context["present"] is True
    assert context["selected_hint_ids"] == ["quality-1"]
    assert context["quality_hints"][0]["source_seed_id"] == ""
    assert context["quality_hints"][0]["topic_affinity"] == (
        "dimension_fallback_missing_refs"
    )
    assert context["topic_affinity_rejected_count"] == 0


def test_invalid_prompt_mode_falls_back_to_off_shape() -> None:
    context = build_soft_followup_context(
        qa_history=[
            {
                "turn_idx": 1,
                "dimension": "system_design",
                "evaluation": {
                    "soft_followup_hints": _soft_hints(
                        quality=[_hint("quality-1", hint_type="quality", text="x")]
                    )
                },
            }
        ],
        current_dimension="system_design",
        ask_plan={"template": "deep_probe"},
        prompt_mode="surprise",
    )

    assert context["mode"] == "off"
    assert context["present"] is False
    assert context["not_applied_reason"] == "disabled"
