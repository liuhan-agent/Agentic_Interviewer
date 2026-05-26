from __future__ import annotations


def test_duplicate_rewrite_replaces_stale_contract(monkeypatch):
    from app.engine.workflow.nodes import ask_question as ask_mod

    repeated = "Tell me about a system you designed and the trade-offs you made."

    def fake_retrieve(**_kwargs):
        class _Ctx:
            as_prompt_block = "(stub retrieval)"

        return _Ctx()

    def fake_generate_question(**kwargs):
        return {
            "question": repeated,
            "dimension": kwargs["dimension"],
            "rubric_points": ["stale"],
            "proposed_contract": {
                "must_cover": ["stale"],
                "acceptance_checks": ["Names a stale check."],
                "minimum_bar": "Old minimum bar.",
                "bar_level": "standard",
            },
        }

    def fake_negotiate(**kwargs):
        return {**kwargs["proposed_contract"], "signed_by": ["generator", "evaluator"]}

    monkeypatch.setattr(ask_mod, "retrieve_for_question", fake_retrieve)
    monkeypatch.setattr(ask_mod, "retrieve_strategies", lambda **_kwargs: [])
    monkeypatch.setattr(
        ask_mod,
        "format_strategies_for_prompt",
        lambda _entries: "(no relevant strategy memories)",
    )
    monkeypatch.setattr(ask_mod, "generate_question", fake_generate_question)
    monkeypatch.setattr(ask_mod, "negotiate_contract_via_evaluator", fake_negotiate)
    traced_payloads: list[dict] = []

    class _Tracer:
        def trace_node_event(self, _state, *, node, payload, **_kwargs):
            if node == "ask_question":
                traced_payloads.append(payload)

    monkeypatch.setattr(ask_mod, "get_tracer", lambda: _Tracer())

    state = {
        "session_id": "sess-contract-sync",
        "trace_id": "trace-contract-sync",
        "job_spec": {
            "title": "Backend Engineer",
            "level": "mid",
            "required_skills": ["redis", "kafka"],
        },
        "candidate": {
            "resume_parsed": {
                "projects": [
                    {
                        "id": "proj-1",
                        "name": "Order System",
                        "tech_stack": ["Redis", "Kafka"],
                    }
                ],
                "focus_areas": [
                    {
                        "id": "focus-1",
                        "project_id": "proj-1",
                        "dimensions": ["technical_depth"],
                        "skills": ["Redis", "Kafka"],
                        "priority": 1,
                    }
                ],
            }
        },
        "dimensions": ["technical_depth"],
        "dimension_status": {"technical_depth": "active"},
        "current_dimension": "technical_depth",
        "turn_idx": 2,
        "formal_turn_idx": 1,
        "qa_history": [{"turn_idx": 0, "question": repeated}],
        "runtime_config": {},
        "refine_mode": False,
        "current_ask_plan": None,
        "current_contract": None,
        "pending_plan_template": None,
        "pending_contract_hints": None,
        "target_difficulty": "medium",
        "selected_action": {"id": "plan_deep_probe", "plan_template": "deep_probe"},
    }

    out = ask_mod.ask_question_node(state)  # type: ignore[arg-type]

    assert out["current_question"]["duplicate_rewrite"] is True
    contract = out["current_contract"]
    checks = " ".join(contract["acceptance_checks"]).lower()
    assert "stale" not in checks
    assert "redis" in checks
    assert out["current_question"]["contract"] == contract
    assert traced_payloads[-1]["contract_diagnostics"]["source"] == "rewrite_fallback"
    assert "rewrite_fallback" in traced_payloads[-1]["contract_diagnostics"]["warnings"]
