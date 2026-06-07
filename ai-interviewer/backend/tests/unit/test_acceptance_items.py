from app.engine.contracts.acceptance_items import (
    acceptance_check_items_from_legacy,
    acceptance_check_items_from_structured,
    append_acceptance_check_items,
    contract_for_legacy_scoring,
    contract_for_source_aware_scoring,
    ensure_contract_acceptance_items,
    join_acceptance_check_results,
)


def test_legacy_checks_generate_adaptive_context_items_and_projection() -> None:
    contract = ensure_contract_acceptance_items(
        {"acceptance_checks": ["Explains idempotency.", "Names retry limits."]},
        source="adaptive_context",
        origin="negotiated_contract",
    )

    assert contract["acceptance_checks"] == [
        "Explains idempotency.",
        "Names retry limits.",
    ]
    assert [item["text"] for item in contract["acceptance_check_items"]] == (
        contract["acceptance_checks"]
    )
    assert {item["source"] for item in contract["acceptance_check_items"]} == {
        "adaptive_context"
    }
    assert {item["severity"] for item in contract["acceptance_check_items"]} == {
        "supporting"
    }


def test_structured_reviewed_and_compiled_checks_preserve_metadata() -> None:
    seed_ref = {
        "seed_id": "technical_depth.java_transaction_consistency",
        "variant_id": "technical_depth.java_transaction_consistency.order_payment_boundary",
        "seed_version": 1,
        "variant_version": 1,
    }
    checks = [
        {
            "check_id": "reviewed:idempotency",
            "source": "must_cover",
            "source_text": "幂等控制",
            "acceptance_check": "候选人说明幂等键、唯一约束或状态机如何防重复。",
            "severity": "core",
            "review_status": "reviewed",
        }
    ]

    reviewed = acceptance_check_items_from_structured(
        checks,
        source="reviewed",
        origin="question_variant",
        seed_ref=seed_ref,
    )
    compiled = acceptance_check_items_from_structured(
        [{**checks[0], "check_id": "seed_check:idempotency"}],
        source="compiled_fallback",
        origin="locked_core_compiler",
        seed_ref=seed_ref,
    )

    assert reviewed[0]["check_id"] == "reviewed:idempotency"
    assert reviewed[0]["source"] == "reviewed"
    assert reviewed[0]["severity"] == "core"
    assert reviewed[0]["source_text"] == "幂等控制"
    assert reviewed[0]["seed_ref"] == seed_ref
    assert reviewed[0]["metadata"]["criterion_source"] == "must_cover"
    assert compiled[0]["source"] == "compiled_fallback"
    assert compiled[0]["origin"] == "locked_core_compiler"


def test_append_dedupes_by_source_text_without_generic_prefix_false_coverage() -> None:
    base = {
        "acceptance_checks": [
            "候选人能按技术栈组件（如Redis扣减、MQ投递、DB落库）顺序列出验证步骤",
        ]
    }
    reviewed = acceptance_check_items_from_structured(
        [
            {
                "check_id": "reviewed:idempotency",
                "source": "must_cover",
                "source_text": "幂等控制",
                "acceptance_check": (
                    "候选人说明重复支付、重复回调或客户端重试时，服务端通过"
                    "业务幂等键、唯一约束或状态机保证请求只生效一次。"
                ),
                "severity": "core",
            },
            {
                "check_id": "reviewed:idempotency-duplicate",
                "source": "must_cover",
                "source_text": "幂等控制",
                "acceptance_check": "候选人说明幂等控制。",
                "severity": "core",
            },
        ],
        source="reviewed",
        origin="question_variant",
    )

    contract, appended = append_acceptance_check_items(base, reviewed)

    assert appended == [reviewed[0]["text"]]
    assert contract["acceptance_checks"] == [
        "候选人能按技术栈组件（如Redis扣减、MQ投递、DB落库）顺序列出验证步骤",
        reviewed[0]["text"],
    ]
    assert [item["text"] for item in contract["acceptance_check_items"]] == (
        contract["acceptance_checks"]
    )


def test_join_acceptance_check_results_backfills_item_metadata() -> None:
    contract = ensure_contract_acceptance_items(
        {
            "acceptance_checks": ["Explains idempotency."],
            "acceptance_check_items": [
                {
                    "check_id": "reviewed:idempotency",
                    "text": "Explains idempotency.",
                    "source": "reviewed",
                    "severity": "core",
                    "source_text": "idempotency",
                    "origin": "question_variant",
                    "seed_ref": {"seed_id": "seed"},
                    "metadata": {"criterion_source": "must_cover"},
                }
            ],
        }
    )
    results = {
        "Explains idempotency.": {
            "verdict": "partial",
            "evidence": ["used requestId"],
            "evidence_spans": [{"match": "exact"}],
        }
    }

    joined = join_acceptance_check_results(contract, results)

    assert joined == [
        {
            "check_id": "reviewed:idempotency",
            "text": "Explains idempotency.",
            "source": "reviewed",
            "severity": "core",
            "source_text": "idempotency",
            "origin": "question_variant",
            "seed_ref": {"seed_id": "seed"},
            "metadata": {"criterion_source": "must_cover"},
            "verdict": "partial",
            "evidence": ["used requestId"],
            "evidence_spans": [{"match": "exact"}],
            "result_present": True,
        }
    ]


def test_join_acceptance_check_results_preserves_evaluator_extra_keys() -> None:
    items = acceptance_check_items_from_legacy(["Explains idempotency."])
    joined = join_acceptance_check_results(
        {"acceptance_check_items": items},
        {
            "Explains idempotency.": {"verdict": "yes", "evidence": []},
            "Unexpected extra check": {"verdict": "no", "evidence": ["nope"]},
        },
    )

    assert [item["source"] for item in joined] == [
        "adaptive_context",
        "evaluator_extra",
    ]
    assert joined[1]["text"] == "Unexpected extra check"
    assert joined[1]["severity"] == "supporting"
    assert joined[1]["verdict"] == "no"


def test_join_acceptance_check_results_does_not_match_check_id_keys() -> None:
    contract = ensure_contract_acceptance_items(
        {
            "acceptance_checks": ["Explains idempotency."],
            "acceptance_check_items": [
                {
                    "check_id": "reviewed:idempotency",
                    "text": "Explains idempotency.",
                    "source": "reviewed",
                    "severity": "core",
                }
            ],
        }
    )

    joined = join_acceptance_check_results(
        contract,
        {
            "reviewed:idempotency": {
                "verdict": "yes",
                "evidence": ["request id"],
            }
        },
    )

    assert joined[0]["text"] == "Explains idempotency."
    assert joined[0]["source"] == "reviewed"
    assert joined[0]["result_present"] is False
    assert joined[1]["text"] == "reviewed:idempotency"
    assert joined[1]["source"] == "evaluator_extra"
    assert joined[1]["verdict"] == "yes"


def test_contract_for_legacy_scoring_removes_structured_items_only() -> None:
    contract = {
        "must_cover": ["capacity"],
        "acceptance_checks": ["Names capacity estimate."],
        "acceptance_check_items": [
            {
                "check_id": "reviewed:capacity",
                "text": "Names capacity estimate.",
                "source": "reviewed",
                "severity": "core",
            }
        ],
    }

    scoring_contract = contract_for_legacy_scoring(contract)

    assert scoring_contract == {
        "must_cover": ["capacity"],
        "acceptance_checks": ["Names capacity estimate."],
    }
    assert "acceptance_check_items" in contract


def test_contract_for_source_aware_scoring_adds_lightweight_prompt_items() -> None:
    contract = {
        "must_cover": ["rollback"],
        "acceptance_checks": ["Mentions rollback."],
        "acceptance_check_items": [
            {
                "check_id": "reviewed:rollback",
                "text": "Mentions rollback.",
                "source": "reviewed",
                "severity": "core",
                "source_text": "rollback",
                "origin": "question_variant",
                "seed_ref": {"seed_id": "seed", "variant_id": "variant"},
                "metadata": {"large": "do not send"},
            },
            {
                "check_id": "adaptive:latency",
                "text": "Quantifies latency impact.",
                "source": "adaptive_context",
                "severity": "supporting",
                "source_text": "",
                "origin": "negotiated_contract",
                "seed_ref": {},
                "metadata": {},
            },
            {
                "check_id": "bad:empty",
                "text": "",
                "source": "reviewed",
                "severity": "core",
            },
        ],
    }

    scoring_contract = contract_for_source_aware_scoring(contract)

    assert scoring_contract["acceptance_checks"] == [
        "Mentions rollback.",
        "Quantifies latency impact.",
    ]
    assert scoring_contract["acceptance_check_items_for_prompt"] == [
        {
            "check_id": "reviewed:rollback",
            "text": "Mentions rollback.",
            "source": "reviewed",
            "severity": "core",
        },
        {
            "check_id": "adaptive:latency",
            "text": "Quantifies latency impact.",
            "source": "adaptive_context",
            "severity": "supporting",
        },
    ]
    assert "acceptance_check_items" not in scoring_contract
    assert "metadata" not in scoring_contract["acceptance_check_items_for_prompt"][0]
    assert "seed_ref" not in scoring_contract["acceptance_check_items_for_prompt"][0]
    assert "acceptance_check_items_for_prompt" not in contract


def test_contract_for_source_aware_scoring_falls_back_to_legacy_without_items() -> None:
    contract = {
        "must_cover": ["capacity"],
        "acceptance_checks": ["Names capacity estimate."],
    }

    scoring_contract = contract_for_source_aware_scoring(contract)

    assert scoring_contract == {
        "must_cover": ["capacity"],
        "acceptance_checks": ["Names capacity estimate."],
    }
