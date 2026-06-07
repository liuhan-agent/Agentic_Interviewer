from __future__ import annotations

import json

from app.engine.contracts.acceptance_items import contract_for_source_aware_scoring


def test_model_pass_true_cannot_override_low_score(monkeypatch):
    from app.engine.agents import evaluator_agent as eval_mod

    def fake_call(*_args, **_kwargs):
        return (
            '{"score": 3.0, "passed": true, '
            '"strengths": [], "weaknesses": [], '
            '"acceptance_check_results": {'
            '"depth": {"verdict": "yes", "evidence": ["deep detail"]}}, '
            '"recommended_next": "advance", '
            '"rationale": "model overconfident"}'
        )

    monkeypatch.setattr(eval_mod, "call_chat", fake_call)

    result = eval_mod.evaluate_answer(
        dimension="technical_depth",
        question="Explain the deepest technical decision.",
        rubric_points=["depth"],
        answer="deep detail",
        quality_threshold=7.0,
        contract={
            "must_cover": ["depth"],
            "acceptance_checks": ["depth"],
            "minimum_bar": "Shows technical depth.",
            "bar_level": "standard",
        },
    )

    assert result["score"] == 3.0
    assert result["rubric_coverage"]["depth"] == "covered"
    assert result["passed"] is False


def test_model_pass_true_cannot_override_missing_must_cover(monkeypatch):
    from app.engine.agents import evaluator_agent as eval_mod

    def fake_call(*_args, **_kwargs):
        return (
            '{"score": 9.0, "passed": true, '
            '"strengths": ["clear"], "weaknesses": ["missing rollback"], '
            '"rubric_coverage": {"rollback plan": "missing"}, '
            '"acceptance_check_results": {'
            '"Mentions rollback plan.": {"verdict": "no", "evidence": []}}, '
            '"recommended_next": "advance", '
            '"rationale": "model ignored missing coverage"}'
        )

    monkeypatch.setattr(eval_mod, "call_chat", fake_call)

    result = eval_mod.evaluate_answer(
        dimension="technical_depth",
        question="How do you handle schema migrations?",
        rubric_points=["rollback plan"],
        answer="I would deploy carefully.",
        quality_threshold=7.0,
        contract={
            "must_cover": ["rollback plan"],
            "acceptance_checks": ["Mentions rollback plan."],
            "minimum_bar": "Includes rollback planning.",
            "bar_level": "standard",
        },
    )

    assert result["score"] == 9.0
    assert result["rubric_coverage"]["rollback plan"] == "missing"
    assert result["passed"] is False


def test_evaluator_prompt_includes_source_aware_checks_but_keeps_legacy_output(
    monkeypatch,
) -> None:
    from app.engine.agents import evaluator_agent as eval_mod

    captured: dict[str, object] = {}

    def fake_call(messages, *_args, **_kwargs):
        captured["messages"] = messages
        return json.dumps(
            {
                "score": 8.0,
                "passed": True,
                "strengths": ["clear"],
                "weaknesses": [],
                "acceptance_check_results": {
                    "Mentions rollback.": {
                        "verdict": "yes",
                        "evidence": ["rollback"],
                    }
                },
                "recommended_next": "advance",
                "recommended_next_plan": None,
                "failure_categories": [],
                "rationale": "ok",
            }
        )

    monkeypatch.setattr(eval_mod, "call_chat", fake_call)
    contract = contract_for_source_aware_scoring(
        {
            "must_cover": ["rollback"],
            "acceptance_checks": ["Mentions rollback."],
            "acceptance_check_items": [
                {
                    "check_id": "reviewed:rollback",
                    "text": "Mentions rollback.",
                    "source": "reviewed",
                    "severity": "core",
                }
            ],
        }
    )

    result = eval_mod.evaluate_answer(
        dimension="technical_depth",
        question="How would you migrate safely?",
        rubric_points=["rollback"],
        answer="I would include rollback.",
        quality_threshold=7.0,
        contract=contract,
    )

    user_text = captured["messages"][1].content  # type: ignore[index,union-attr]
    assert '"acceptance_check_items_for_prompt"' in user_text
    assert '"check_id": "reviewed:rollback"' in user_text
    assert '"source": "reviewed"' in user_text
    assert '"severity": "core"' in user_text
    assert "reviewed/core" in user_text
    assert "core baseline" in user_text
    assert "Use the check text, not check_id, as the acceptance_check_results key" in (
        user_text
    )
    assert list(result["acceptance_check_results"]) == ["Mentions rollback."]
    check_result = result["acceptance_check_results"]["Mentions rollback."]
    assert check_result["verdict"] == "yes"
    assert check_result["evidence"] == ["rollback"]
