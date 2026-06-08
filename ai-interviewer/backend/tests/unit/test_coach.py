"""Tests for the Coach agent (V1 upgrade).

Covers:
- _importance_sample_qa: score-based sampling, fallback filtering, ordering
- _truncate_at_boundary: sentence-boundary truncation
- _fallback_training_plan: diagnosis, steps, success_criteria, dynamic goals
- build_training_plan: LLM path (mocked) and fallback degradation
"""
from __future__ import annotations

from typing import Any
from unittest.mock import patch

from app.engine.agents.coach import (
    _build_diagnosis,
    _fallback_training_plan,
    _importance_sample_qa,
    _normalize_llm_plan,
    _project_qa_for_coach,
    _truncate_at_boundary,
    build_training_plan,
)


def _make_qa(
    turn_idx: int,
    dimension: str = "technical_depth",
    score: float | None = 7.0,
    passed: bool = True,
    weaknesses: list[str] | None = None,
    strengths: list[str] | None = None,
    question: str = "示例问题",
    answer: str = "示例回答",
    source: str | None = None,
) -> dict[str, Any]:
    evaluation: dict[str, Any] = {
        "score": score,
        "passed": passed,
        "weaknesses": weaknesses or [],
        "strengths": strengths or ["有基础"],
    }
    if source:
        evaluation["source"] = source
    return {
        "turn_idx": turn_idx,
        "dimension": dimension,
        "question": question,
        "answer": answer,
        "evaluation": evaluation,
        "resume_anchor": {"project": "demo"},
        "target_skills": ["python"],
        "selected_action": "advance",
    }


def _make_fallback_qa(turn_idx: int) -> dict[str, Any]:
    return _make_qa(
        turn_idx,
        score=5.0,
        passed=False,
        source="fallback",
        weaknesses=["Evaluator LLM unavailable; using conservative fallback."],
    )


class TestTruncateAtBoundary:
    def test_short_text_unchanged(self) -> None:
        assert _truncate_at_boundary("短文本", 300) == "短文本"

    def test_empty_text(self) -> None:
        assert _truncate_at_boundary("", 300) == ""
        assert _truncate_at_boundary(None, 300) == ""  # type: ignore[arg-type]

    def test_truncates_at_sentence(self) -> None:
        text = "第一句话。第二句话。第三句话很长" + "x" * 300
        result = _truncate_at_boundary(text, 20)
        assert result.endswith("…")
        assert "。" in result

    def test_hard_cut_when_no_boundary(self) -> None:
        text = "a" * 500
        result = _truncate_at_boundary(text, 300)
        assert len(result) == 301  # 300 chars + "…"


class TestImportanceSampleQA:
    def test_empty_history(self) -> None:
        assert _importance_sample_qa([]) == []

    def test_filters_fallback_turns(self) -> None:
        qa = [_make_qa(0, score=8.0), _make_fallback_qa(1), _make_qa(2, score=6.0)]
        result = _importance_sample_qa(qa)
        assert len(result) == 2
        assert all(r["turn_idx"] != 1 for r in result)

    def test_score_ascending_priority(self) -> None:
        qa = [
            _make_qa(0, score=9.0),
            _make_qa(1, score=3.0),
            _make_qa(2, score=7.0),
        ]
        result = _importance_sample_qa(qa, max_turns=2)
        assert len(result) == 2
        assert result[0]["turn_idx"] == 1  # lowest score first (by time order)
        assert result[1]["turn_idx"] == 2

    def test_none_scores_are_excluded_from_training_signal(self) -> None:
        qa = [
            _make_qa(0, score=None),
            _make_qa(1, score=5.0),
            _make_qa(2, score=None),
        ]
        result = _importance_sample_qa(qa, max_turns=2)
        assert [r["turn_idx"] for r in result] == [1]

    def test_preserves_time_order(self) -> None:
        qa = [_make_qa(i, score=float(10 - i)) for i in range(15)]
        result = _importance_sample_qa(qa, max_turns=5)
        turn_indices = [r["turn_idx"] for r in result]
        assert turn_indices == sorted(turn_indices)

    def test_max_turns_limit(self) -> None:
        qa = [_make_qa(i, score=float(i)) for i in range(20)]
        result = _importance_sample_qa(qa, max_turns=12)
        assert len(result) == 12

    def test_filters_non_scored_dimensions_from_final_report(self) -> None:
        qa = [
            _make_qa(0, dimension="technical_depth", score=4.0),
            _make_qa(1, dimension="project_experience", score=None, weaknesses=["跳过不是能力弱项"]),
            _make_qa(2, dimension="communication", score=6.5, weaknesses=["评估失败不是能力弱项"]),
        ]
        qa[1]["answer_intent"] = "skipped"
        qa[1]["evaluation"]["skipped"] = True
        qa[2]["evaluation"]["source"] = "fallback"
        final_report = {
            "dimension_scores": {
                "technical_depth": {"score_status": "scored", "coverage_status": "below_threshold"},
                "project_experience": {"score_status": "skipped", "coverage_status": "not_applicable"},
                "communication": {"score_status": "evaluator_unavailable", "coverage_status": "not_applicable"},
            }
        }

        result = _importance_sample_qa(qa, final_report=final_report)

        assert [item["dimension"] for item in result] == ["technical_depth"]


class TestProjectQAForCoach:
    def test_projects_all_fields(self) -> None:
        qa = _make_qa(0, question="很长的问题" * 100, answer="很长的答案" * 100)
        result = _project_qa_for_coach(qa)
        assert result["turn_idx"] == 0
        assert len(result["question"]) <= 201  # 200 + "…"
        assert len(result["answer_excerpt"]) <= 301
        assert result["resume_anchor"] == {"project": "demo"}
        assert result["target_skills"] == ["python"]
        assert isinstance(result["acceptance_verdicts"], dict)


class TestBuildDiagnosis:
    def test_high_score_readiness(self) -> None:
        diag = _build_diagnosis(
            dim_last_score={"technical_depth": 8.5},
            final_report={"overall_score": 8.0, "verdict": "strong_pass"},
            weakness_count=1,
        )
        assert "达标" in diag["overall_readiness"]

    def test_low_score_readiness(self) -> None:
        diag = _build_diagnosis(
            dim_last_score={"technical_depth": 3.0},
            final_report={"overall_score": 3.5, "verdict": "fail"},
            weakness_count=5,
        )
        assert "差距" in diag["overall_readiness"]

    def test_patterns_populated(self) -> None:
        diag = _build_diagnosis(
            dim_last_score={"technical_depth": 4.0, "communication": 3.0},
            final_report={"overall_score": 4.0, "verdict": "fail"},
            weakness_count=5,
        )
        assert len(diag["top_patterns"]) > 0


class TestFallbackTrainingPlan:
    def test_empty_qa_empty_report(self) -> None:
        plan = _fallback_training_plan(final_report={}, qa_history=[])
        assert plan["source"] == "fallback"
        assert "diagnosis" in plan
        assert "goals_30_60_90" in plan

    def test_diagnosis_present(self) -> None:
        qa = [_make_qa(0, score=5.0, weaknesses=["缺少深度"])]
        plan = _fallback_training_plan(
            final_report={"overall_score": 5.0, "verdict": "borderline"},
            qa_history=qa,
        )
        assert "overall_readiness" in plan["diagnosis"]
        assert "target_level_gap" in plan["diagnosis"]

    def test_practice_plan_has_steps(self) -> None:
        qa = [
            _make_qa(0, score=4.0, weaknesses=["设计模式不熟"]),
            _make_qa(1, score=3.0, weaknesses=["设计模式不熟"]),
        ]
        plan = _fallback_training_plan(
            final_report={"overall_score": 4.0, "verdict": "fail"},
            qa_history=qa,
        )
        assert len(plan["practice_plan"]) > 0
        first_task = plan["practice_plan"][0]
        assert "steps" in first_task
        assert "success_criteria" in first_task
        assert len(first_task["steps"]) >= 2

    def test_dynamic_30_60_90(self) -> None:
        qa = [_make_qa(0, score=4.0, weaknesses=["缺少实战"])]
        plan = _fallback_training_plan(
            final_report={"overall_score": 4.0, "verdict": "fail"},
            qa_history=qa,
        )
        goals = plan["goals_30_60_90"]
        assert len(goals["30_days"]) == 2
        assert len(goals["60_days"]) == 2
        assert len(goals["90_days"]) == 2

    def test_excludes_system_weaknesses(self) -> None:
        qa = [_make_fallback_qa(0), _make_qa(1, score=6.0, weaknesses=["真实弱点"])]
        plan = _fallback_training_plan(
            final_report={"overall_score": 6.0, "verdict": "borderline"},
            qa_history=qa,
        )
        all_focuses = [pw["focus"] for pw in plan["priority_weaknesses"]]
        assert "Evaluator LLM unavailable; using conservative fallback." not in all_focuses

    def test_non_scored_turns_do_not_create_ability_weaknesses(self) -> None:
        qa = [
            _make_qa(0, dimension="technical_depth", score=4.0, weaknesses=["真实能力弱项"]),
            _make_qa(1, dimension="project_experience", score=None, weaknesses=["跳过产生的弱项"]),
            _make_qa(2, dimension="communication", score=6.5, weaknesses=["评估失败产生的弱项"]),
            _make_qa(3, dimension="coding_quality", score=None, weaknesses=["未评分产生的弱项"]),
        ]
        qa[1]["answer_intent"] = "skipped"
        qa[1]["evaluation"]["skipped"] = True
        qa[2]["evaluation"]["source"] = "fallback"
        final_report = {
            "overall_score": 4.0,
            "verdict": "fail",
            "dimension_scores": {
                "technical_depth": {"score": 4.0, "score_status": "scored", "coverage_status": "below_threshold"},
                "project_experience": {"score": None, "score_status": "skipped", "coverage_status": "not_applicable"},
                "communication": {"score": None, "score_status": "evaluator_unavailable", "coverage_status": "not_applicable"},
                "coding_quality": {"score": None, "score_status": "not_evaluated", "coverage_status": "not_applicable"},
            },
        }

        plan = _fallback_training_plan(final_report=final_report, qa_history=qa)

        focuses = [item["focus"] for item in plan["priority_weaknesses"]]
        assert focuses == ["真实能力弱项"]

    def test_coverage_limited_turn_creates_coverage_practice_not_ability_weakness(self) -> None:
        qa = [
            _make_qa(
                0,
                dimension="technical_depth",
                score=9.0,
                passed=False,
                weaknesses=["细节没有完全展开"],
            )
        ]
        final_report = {
            "overall_score": 9.0,
            "verdict": "strong_pass",
            "dimension_scores": {
                "technical_depth": {
                    "score": 9.0,
                    "score_status": "scored",
                    "coverage_status": "coverage_limited",
                }
            },
        }

        plan = _fallback_training_plan(final_report=final_report, qa_history=qa)

        focuses = [item["focus"] for item in plan["priority_weaknesses"]]
        tasks = [item["task"] for item in plan["practice_plan"]]
        assert all("细节没有完全展开" not in focus for focus in focuses)
        assert any("覆盖" in focus or "证据" in focus for focus in focuses)
        assert any("覆盖" in task or "证据" in task for task in tasks)


    def test_gate_enforcement_weakness_is_candidate_readable(self) -> None:
        raw = (
            "Reviewed core acceptance failed (no): "
            "候选人说明消息消费、积分发放或修复任务的关键状态。"
        )
        qa = [
            _make_qa(
                0,
                dimension="problem_solving",
                score=6.0,
                passed=False,
                weaknesses=[raw],
            )
        ]

        plan = _fallback_training_plan(
            final_report={"overall_score": 6.0, "verdict": "borderline"},
            qa_history=qa,
        )

        rendered = str(plan)
        assert "Reviewed core acceptance failed" not in rendered
        assert plan["priority_weaknesses"][0]["focus"] == (
            "核心判定条款未满足：候选人说明消息消费、积分发放或修复任务的关键状态。"
        )
        assert "核心判定条款未满足" in plan["practice_plan"][0]["task"]


class TestNormalizeLLMPlan:
    def test_missing_diagnosis_added(self) -> None:
        data = {"practice_plan": []}
        result = _normalize_llm_plan(data)
        assert "diagnosis" in result
        assert result["diagnosis"]["overall_readiness"] == ""

    def test_partial_diagnosis_patched(self) -> None:
        data = {"diagnosis": {"overall_readiness": "ok"}}
        result = _normalize_llm_plan(data)
        assert result["diagnosis"]["overall_readiness"] == "ok"
        assert result["diagnosis"]["target_level_gap"] == ""
        assert result["diagnosis"]["top_patterns"] == []

    def test_practice_plan_items_patched(self) -> None:
        data = {"practice_plan": [{"task": "do X", "rationale": "why"}]}
        result = _normalize_llm_plan(data)
        item = result["practice_plan"][0]
        assert item["steps"] == []
        assert item["success_criteria"] == []
        assert item["estimated_hours"] == 2.0

    def test_missing_goals_added(self) -> None:
        data: dict[str, Any] = {}
        result = _normalize_llm_plan(data)
        assert result["goals_30_60_90"]["30_days"] == []

    def test_partial_goals_patched(self) -> None:
        data = {"goals_30_60_90": {"30_days": ["a"]}}
        result = _normalize_llm_plan(data)
        assert result["goals_30_60_90"]["30_days"] == ["a"]
        assert result["goals_30_60_90"]["60_days"] == []

    def test_preserves_existing_fields(self) -> None:
        data = {
            "diagnosis": {"overall_readiness": "good", "target_level_gap": "none", "top_patterns": ["A"]},
            "practice_plan": [{"task": "X", "rationale": "Y", "steps": ["1"], "success_criteria": ["2"], "estimated_hours": 3.0}],
            "goals_30_60_90": {"30_days": ["a"], "60_days": ["b"], "90_days": ["c"]},
            "signal_summary": "test",
        }
        result = _normalize_llm_plan(data)
        assert result["diagnosis"]["top_patterns"] == ["A"]
        assert result["practice_plan"][0]["steps"] == ["1"]
        assert result["signal_summary"] == "test"

    def test_llm_plan_text_is_cleaned_of_gate_machine_prefixes(self) -> None:
        data = {
            "priority_weaknesses": [
                {
                    "dimension": "problem_solving",
                    "focus": "Reviewed core acceptance failed (partial): 说明修复后的校验闭环。",
                }
            ],
            "practice_plan": [
                {
                    "task": "Reviewed core acceptance failed (no): 描述补偿任务状态。",
                    "steps": [
                        "Reviewed core acceptance failed (missing_result): 补充监控证据。"
                    ],
                    "success_criteria": [
                        "Reviewed core acceptance failed (no): 能说明如何避免重复修复。"
                    ],
                }
            ],
        }

        result = _normalize_llm_plan(data)

        rendered = str(result)
        assert "Reviewed core acceptance failed" not in rendered
        assert result["priority_weaknesses"][0]["focus"] == (
            "核心判定条款未满足：说明修复后的校验闭环。"
        )
        assert result["practice_plan"][0]["task"] == (
            "核心判定条款未满足：描述补偿任务状态。"
        )


class TestBuildTrainingPlan:
    def test_llm_path_returns_data(self) -> None:
        llm_response = {
            "diagnosis": {"overall_readiness": "测试"},
            "priority_weaknesses": [],
            "practice_plan": [],
            "goals_30_60_90": {"30_days": [], "60_days": [], "90_days": []},
            "signal_summary": "测试摘要",
        }
        with (
            patch(
                "app.engine.agents.coach.call_chat",
                return_value='{"diagnosis":{}}',
            ),
            patch(
                "app.engine.agents.coach.parse_json_response",
                return_value=llm_response,
            ),
            patch(
                "app.engine.agents.coach.build_context_frame_for_coach",
            ),
            patch(
                "app.engine.agents.coach.frame_to_coach_messages",
                return_value=[],
            ),
        ):
            plan = build_training_plan(
                job_spec={},
                candidate={},
                final_report={"overall_score": 7.0, "verdict": "pass"},
                qa_history=[_make_qa(0)],
            )
        assert plan["source"] == "llm"

    def test_llm_failure_degrades_to_fallback(self) -> None:
        with (
            patch(
                "app.engine.agents.coach.call_chat",
                side_effect=RuntimeError("LLM down"),
            ),
            patch(
                "app.engine.agents.coach.build_context_frame_for_coach",
            ),
            patch(
                "app.engine.agents.coach.frame_to_coach_messages",
                return_value=[],
            ),
        ):
            plan = build_training_plan(
                job_spec={},
                candidate={},
                final_report={"overall_score": 5.0, "verdict": "fail"},
                qa_history=[_make_qa(0, score=5.0, weaknesses=["弱点1"])],
        )
        assert plan["source"] == "fallback"
        assert plan["fallback_reason"] == "llm_call_failed"
        assert "diagnosis" in plan

    def test_empty_llm_output_records_fallback_reason(self) -> None:
        with (
            patch(
                "app.engine.agents.coach.call_chat",
                return_value="   ",
            ),
            patch(
                "app.engine.agents.coach.build_context_frame_for_coach",
            ),
            patch(
                "app.engine.agents.coach.frame_to_coach_messages",
                return_value=[],
            ),
        ):
            plan = build_training_plan(
                job_spec={},
                candidate={},
                final_report={"overall_score": 5.0, "verdict": "fail"},
                qa_history=[_make_qa(0, score=5.0, weaknesses=["寮辩偣1"])],
            )

        assert plan["source"] == "fallback"
        assert plan["fallback_reason"] == "empty_output"

    def test_empty_llm_output_retries_once_before_fallback(self) -> None:
        valid = (
            '{"diagnosis":{"overall_readiness":"ready"},'
            '"priority_weaknesses":[],"practice_plan":[],'
            '"goals_30_60_90":{"30_days":[],"60_days":[],"90_days":[]},'
            '"signal_summary":"ok"}'
        )
        with (
            patch(
                "app.engine.agents.coach.call_chat",
                side_effect=["   ", valid],
            ) as mock_call,
            patch(
                "app.engine.agents.coach.build_context_frame_for_coach",
            ),
            patch(
                "app.engine.agents.coach.frame_to_coach_messages",
                return_value=[],
            ),
        ):
            plan = build_training_plan(
                job_spec={},
                candidate={},
                final_report={"overall_score": 5.0, "verdict": "fail"},
                qa_history=[_make_qa(0, score=5.0, weaknesses=["瀵京鍋?"])],
            )

        assert mock_call.call_count == 2
        assert plan["source"] == "llm"
        assert plan["signal_summary"] == "ok"

    def test_json_parse_failure_records_fallback_reason(self) -> None:
        with (
            patch(
                "app.engine.agents.coach.call_chat",
                return_value="not json at all",
            ),
            patch(
                "app.engine.agents.coach.build_context_frame_for_coach",
            ),
            patch(
                "app.engine.agents.coach.frame_to_coach_messages",
                return_value=[],
            ),
        ):
            plan = build_training_plan(
                job_spec={},
                candidate={},
                final_report={"overall_score": 5.0, "verdict": "fail"},
                qa_history=[_make_qa(0, score=5.0, weaknesses=["寮辩偣1"])],
            )

        assert plan["source"] == "fallback"
        assert plan["fallback_reason"] == "json_parse_failed"

    def test_json_parse_failure_retries_once_before_fallback(self) -> None:
        valid = (
            '{"diagnosis":{"overall_readiness":"ready"},'
            '"priority_weaknesses":[],"practice_plan":[],'
            '"goals_30_60_90":{"30_days":[],"60_days":[],"90_days":[]},'
            '"signal_summary":"ok"}'
        )
        with (
            patch(
                "app.engine.agents.coach.call_chat",
                side_effect=["not json at all", valid],
            ) as mock_call,
            patch(
                "app.engine.agents.coach.build_context_frame_for_coach",
            ),
            patch(
                "app.engine.agents.coach.frame_to_coach_messages",
                return_value=[],
            ),
        ):
            plan = build_training_plan(
                job_spec={},
                candidate={},
                final_report={"overall_score": 5.0, "verdict": "fail"},
                qa_history=[_make_qa(0, score=5.0, weaknesses=["瀵京鍋?"])],
            )

        assert mock_call.call_count == 2
        assert plan["source"] == "llm"
        assert plan["signal_summary"] == "ok"

    def test_invalid_llm_structure_records_fallback_reason(self) -> None:
        with (
            patch(
                "app.engine.agents.coach.call_chat",
                return_value='{"unexpected":"shape"}',
            ),
            patch(
                "app.engine.agents.coach.build_context_frame_for_coach",
            ),
            patch(
                "app.engine.agents.coach.frame_to_coach_messages",
                return_value=[],
            ),
        ):
            plan = build_training_plan(
                job_spec={},
                candidate={},
                final_report={"overall_score": 5.0, "verdict": "fail"},
                qa_history=[_make_qa(0, score=5.0, weaknesses=["寮辩偣1"])],
            )

        assert plan["source"] == "fallback"
        assert plan["fallback_reason"] == "invalid_structure"

    def test_fallback_uses_candidate_growth_language_for_legacy_hire_verdict(self) -> None:
        plan = _fallback_training_plan(
            final_report={"overall_score": 7.0, "verdict": "hire"},
            qa_history=[_make_qa(0, score=7.0, weaknesses=["缺少量化结果"])],
        )

        assert "录用" not in plan["signal_summary"]
        assert "录用" not in plan["diagnosis"]["verdict"]
        assert plan["diagnosis"]["verdict"] == "达到目标水平"

    def test_new_params_accepted(self) -> None:
        with (
            patch(
                "app.engine.agents.coach.call_chat",
                side_effect=RuntimeError("skip"),
            ),
            patch(
                "app.engine.agents.coach.build_context_frame_for_coach",
            ) as mock_build,
            patch(
                "app.engine.agents.coach.frame_to_coach_messages",
                return_value=[],
            ),
        ):
            build_training_plan(
                job_spec={},
                candidate={},
                final_report={},
                qa_history=[],
                self_intro_profile={"summary": "test"},
                verification={"verdict": "pass"},
            )
        call_kwargs = mock_build.call_args.kwargs
        assert call_kwargs["self_intro_profile"] == {"summary": "test"}
        assert call_kwargs["verification_summary"] == {"verdict": "pass"}

    def test_llm_context_excludes_non_scored_dimension_summaries(self) -> None:
        final_report = {
            "overall_score": 4.0,
            "dimension_scores": {
                "technical_depth": {"score": 4.0, "score_status": "scored", "coverage_status": "below_threshold"},
                "project_experience": {"score": None, "score_status": "skipped", "coverage_status": "not_applicable"},
                "system_design": {"score": 9.0, "score_status": "scored", "coverage_status": "coverage_limited"},
            },
            "dimension_summaries": {
                "technical_depth": {"weaknesses": ["真实能力弱项"], "strengths": []},
                "project_experience": {"weaknesses": ["跳过不应进入训练"], "strengths": []},
                "system_design": {"weaknesses": ["覆盖不足不应作为能力弱项"], "strengths": []},
            },
        }
        with (
            patch(
                "app.engine.agents.coach.call_chat",
                side_effect=RuntimeError("skip"),
            ),
            patch(
                "app.engine.agents.coach.build_context_frame_for_coach",
            ) as mock_build,
            patch(
                "app.engine.agents.coach.frame_to_coach_messages",
                return_value=[],
            ),
        ):
            build_training_plan(
                job_spec={},
                candidate={},
                final_report=final_report,
                qa_history=[
                    _make_qa(0, dimension="technical_depth", score=4.0, weaknesses=["真实能力弱项"]),
                    _make_qa(1, dimension="project_experience", score=None, weaknesses=["跳过不应进入训练"]),
                    _make_qa(2, dimension="system_design", score=9.0, weaknesses=["覆盖不足不应作为能力弱项"]),
                ],
            )

        coach_report = mock_build.call_args.kwargs["final_report"]
        summaries = coach_report["dimension_summaries"]
        assert set(summaries) == {"technical_depth", "system_design"}
        assert summaries["technical_depth"]["weaknesses"] == ["真实能力弱项"]
        assert summaries["system_design"]["weaknesses"] == []
        assert coach_report["coach_generation_policy"]["coverage_limited_dimensions"] == [
            "system_design"
        ]

    def test_llm_context_sanitizes_gate_machine_prefixes(self) -> None:
        raw = (
            "Reviewed core acceptance failed (no): "
            "候选人需要补充修复后的校验闭环。"
        )
        final_report = {
            "overall_score": 6.0,
            "verdict": "borderline",
            "dimension_scores": {
                "problem_solving": {
                    "score": 6.0,
                    "score_status": "scored",
                    "coverage_status": "below_threshold",
                },
            },
            "dimension_summaries": {
                "problem_solving": {"weaknesses": [raw], "strengths": []},
            },
        }
        with (
            patch(
                "app.engine.agents.coach.call_chat",
                side_effect=RuntimeError("skip"),
            ),
            patch(
                "app.engine.agents.coach.build_context_frame_for_coach",
            ) as mock_build,
            patch(
                "app.engine.agents.coach.frame_to_coach_messages",
                return_value=[],
            ),
        ):
            build_training_plan(
                job_spec={},
                candidate={},
                final_report=final_report,
                qa_history=[
                    _make_qa(
                        0,
                        dimension="problem_solving",
                        score=6.0,
                        passed=False,
                        weaknesses=[raw],
                    ),
                ],
            )

        coach_report = mock_build.call_args.kwargs["final_report"]
        rendered = str(coach_report)
        assert "Reviewed core acceptance failed" not in rendered
        assert coach_report["dimension_summaries"]["problem_solving"]["weaknesses"] == [
            "核心判定条款未满足：候选人需要补充修复后的校验闭环。"
        ]
