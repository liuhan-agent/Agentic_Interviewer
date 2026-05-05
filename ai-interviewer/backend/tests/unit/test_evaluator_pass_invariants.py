from __future__ import annotations


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
