from __future__ import annotations

from app.engine.workflow.nodes.skip_question import skip_question_node


def test_skip_question_persists_minimal_injected_question_refs() -> None:
    update = skip_question_node(
        {
            "turn_idx": 2,
            "formal_turn_idx": 2,
            "turn_budget_remaining": 4,
            "dimensions": ["system_design", "technical_depth"],
            "dimension_status": {"system_design": "active", "technical_depth": "pending"},
            "current_dimension": "system_design",
            "current_question": {
                "dimension": "system_design",
                "question": "Q",
                "selection_artifacts": {
                    "rag": {"doc_refs": [{"source": "kb.md"}]},
                    "question_items": [
                        {
                            "seed_id": "system_design.cache",
                            "variant_id": "system_design.cache.opening",
                            "rank": 1,
                            "injected": True,
                            "scenario_brief": "do not persist",
                            "match_reasons": ["priority:100"],
                        },
                        {
                            "seed_id": "system_design.queue",
                            "variant_id": "system_design.queue.opening",
                            "rank": 2,
                            "injected": False,
                        },
                    ],
                },
            },
        }
    )

    assert update["qa_history"][0]["selection_artifacts"] == {
        "question_items": [
            {
                "seed_id": "system_design.cache",
                "variant_id": "system_design.cache.opening",
                "rank": 1,
                "injected": True,
            }
        ]
    }
