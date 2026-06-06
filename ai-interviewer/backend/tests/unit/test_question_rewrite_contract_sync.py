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


def test_duplicate_rewrite_takes_precedence_over_locked_core_contract(monkeypatch):
    from app.engine.workflow.nodes import ask_question as ask_mod
    from app.services.question_selector import QuestionCandidate, QuestionSelectionResult

    repeated = "请说明一次缓存一致性设计。"

    def fake_retrieve(**_kwargs):
        class _Ctx:
            as_prompt_block = "(stub retrieval)"

        return _Ctx()

    def fake_generate_question(**kwargs):
        return {
            "question": repeated,
            "dimension": kwargs["dimension"],
            "rubric_points": ["llm-only"],
            "proposed_contract": {
                "must_cover": ["llm-only"],
                "acceptance_checks": ["Mentions llm-only."],
                "minimum_bar": "Old minimum bar.",
                "bar_level": "standard",
            },
        }

    def fake_negotiate(**kwargs):
        return {**kwargs["proposed_contract"], "signed_by": ["generator", "evaluator"]}

    candidate = QuestionCandidate(
        seed_id="system_design.cache_consistency",
        variant_id="system_design.cache_consistency.flash_sale_inventory",
        seed_version=2,
        variant_version=5,
        rank=1,
        match_score=42.0,
        match_reasons=["priority"],
        injected=False,
        title="Cache consistency",
        dimension="system_design",
        seed_priority=30,
        variant_priority=20,
        skill_tags=["redis"],
        direction_tags=["internet_tech"],
        role_tags=["java_backend"],
        rubric={
            "must_cover": ["seed consistency"],
            "minimum_bar": "Seed minimum bar.",
        },
        intent="opening",
        difficulty="standard",
        scenario_brief="Flash-sale inventory reads are cache-heavy.",
        question_stem="Design a cache consistency approach.",
        prompt_template="Ask a system design question.",
        scenario_skill_tags=["redis"],
        resume_anchor_hints=["cache"],
        failure_categories=["missing_metrics"],
        rubric_additions=["seed invalidation window"],
        expected_signals=["seed signal"],
        anti_patterns=["seed anti-pattern"],
        good_answer_hints=["seed hint"],
        reviewed_acceptance_checks=[
            {
                "check_id": "reviewed:cache-consistency:core:v1",
                "source": "must_cover",
                "source_text": "seed consistency",
                "acceptance_check": "Answer defines the target consistency level.",
                "severity": "core",
                "review_status": "reviewed",
                "version": 1,
                "reviewed_seed_version": 2,
                "reviewed_variant_version": 5,
                "reviewed_by": "qa-lead",
                "reviewed_at": "2026-06-01",
            }
        ],
    )

    monkeypatch.setattr(ask_mod, "retrieve_for_question", fake_retrieve)
    monkeypatch.setattr(ask_mod, "retrieve_strategies", lambda **_kwargs: [])
    monkeypatch.setattr(
        ask_mod,
        "format_strategies_for_prompt",
        lambda _entries: "(no relevant strategy memories)",
    )
    monkeypatch.setattr(ask_mod, "generate_question", fake_generate_question)
    monkeypatch.setattr(ask_mod, "negotiate_contract_via_evaluator", fake_negotiate)
    monkeypatch.setattr(
        ask_mod,
        "select_question_candidates",
        lambda **_kwargs: QuestionSelectionResult(candidates=[candidate]),
    )
    monkeypatch.setattr(ask_mod, "record_question_usages", lambda **_kwargs: None)
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
            "required_skills": ["redis"],
            "interview_direction": "java_backend",
        },
        "candidate": {"resume_parsed": {"projects": [], "focus_areas": []}},
        "dimensions": ["system_design"],
        "dimension_status": {"system_design": "active"},
        "current_dimension": "system_design",
        "turn_idx": 2,
        "formal_turn_idx": 1,
        "qa_history": [{"turn_idx": 0, "question": repeated}],
        "runtime_config": {
            "question_selector_mode": "structured_primary",
            "contract_core_mode": "locked",
            "contract_acceptance_mode": "reviewed_append",
        },
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
    assert contract["must_cover"] != ["seed consistency"]
    diagnostics = traced_payloads[-1]["contract_diagnostics"]
    assert diagnostics["source"] == "rewrite_fallback"
    assert diagnostics["locked_core_present"] is True
    assert diagnostics["locked_core_applied"] is False
    assert "locked_core_not_applied_after_rewrite" in diagnostics["locked_core_warnings"]
    assert diagnostics["contract_acceptance_mode"] == "reviewed_append"
    assert diagnostics["compiled_acceptance_present"] is True
    assert diagnostics["compiled_acceptance_applied"] is False
    assert (
        "compiled_acceptance_not_applied_after_rewrite"
        in diagnostics["compiled_acceptance_warnings"]
    )
    assert diagnostics["reviewed_acceptance_source"] == "reviewed"
    assert diagnostics["reviewed_acceptance_applied"] is False
    assert (
        "reviewed_acceptance_not_applied_after_rewrite"
        in diagnostics["reviewed_acceptance_warnings"]
    )
