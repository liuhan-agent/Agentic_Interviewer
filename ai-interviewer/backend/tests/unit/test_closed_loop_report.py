from __future__ import annotations

import math
from typing import Any

from app.engine.agents import coach
from app.engine.workflow.nodes import final_report as fr
from app.engine.workflow.nodes import training_plan as tp
from app.scripts import run_demo


class _NoopTracer:
    def trace_final_report(self, _state: dict[str, Any]) -> None:
        return None

    def trace_node_event(
        self, _state: dict[str, Any], *, node: str, payload: dict[str, Any] | None = None,
        **_kwargs: Any,
    ) -> None:
        return None


def _qa_turn(
    *,
    turn_idx: int,
    dimension: str,
    score: float,
    passed: bool,
    action: str,
) -> dict[str, Any]:
    return {
        "turn_idx": turn_idx,
        "dimension": dimension,
        "question": f"Question {turn_idx}?",
        "answer": "A detailed production answer with concrete trade-offs.",
        "selected_action": action,
        "evaluation": {
            "score": score,
            "passed": passed,
            "strengths": [f"strength-{turn_idx}"],
            "weaknesses": [f"weakness-{turn_idx}"],
            "rubric_coverage": {
                "trade-offs": "covered",
                "failure modes": "partial",
            },
            "acceptance_check_results": {
                "Names a trade-off": "yes",
                "Explains a failure mode": "partial",
                "Quantifies impact": "no",
            },
            "recommended_next": "refine" if not passed else "advance",
            "recommended_next_plan": "deep_probe" if not passed else None,
            "rationale": f"Rationale {turn_idx}",
            "soft_warnings": ["needs sharper metrics"] if not passed else [],
        },
    }


def test_final_report_exposes_dimension_evidence_and_workflow_artifacts(monkeypatch):
    monkeypatch.setattr(fr, "get_tracer", lambda: _NoopTracer())

    state = {
        "session_id": "sess-1",
        "trace_id": "trace-1",
        "candidate": {"name": "Alex"},
        "job_spec": {"title": "Senior Backend Engineer"},
        "quality_threshold": 7.0,
        "scores_per_dim": {"system_design": 7.4, "leadership": 8.2},
        "dimension_status": {"system_design": "active", "leadership": "passed"},
        "qa_history": [
            _qa_turn(
                turn_idx=0,
                dimension="system_design",
                score=6.8,
                passed=False,
                action="plan_deep_probe",
            ),
            _qa_turn(
                turn_idx=1,
                dimension="leadership",
                score=8.2,
                passed=True,
                action="plan_adaptive",
            ),
        ],
        "qa_summary": "[system_design]\n  Key gaps: metrics",
        "current_ask_plan": {"plan_id": "plan-1", "template": "deep_probe"},
        "current_contract": {
            "must_cover": ["trade-offs", "failure modes"],
            "acceptance_checks": ["Names a trade-off", "Explains a failure mode"],
            "signed_by": ["generator", "evaluator"],
        },
        "verification": {
            "verifier_available": True,
            "verdict": "partial",
            "confidence": 0.42,
            "reasons_to_doubt": ["needs sharper metrics"],
        },
        "selected_action": {"id": "plan_deep_probe", "label": "Deep probe"},
    }

    out = fr.final_report_node(state)  # type: ignore[arg-type]
    report = out["final_report"]

    assert report["closed_loop_ready"] is True
    assert report["contract_summary"]["total_checks"] == 3
    assert report["contract_summary"]["checks_yes"] == 1
    assert report["contract_summary"]["checks_partial"] == 1
    assert report["contract_summary"]["checks_no"] == 1
    assert report["risk_flags"] == ["needs sharper metrics", "weakness-0"]

    sys_design = report["dimension_summaries"]["system_design"]
    assert sys_design["turns"] == 1
    assert sys_design["avg_score"] == 7.4
    assert sys_design["followup_reasons"] == ["refine -> deep_probe"]
    assert sys_design["evidence"][0]["acceptance_checks"]["Quantifies impact"] == "no"
    assert sys_design["evidence"][0]["rationale"] == "Rationale 0"

    artifacts = report["workflow_artifacts"]
    assert artifacts["qa_summary"] == "[system_design]\n  Key gaps: metrics"
    assert artifacts["latest_ask_plan"]["template"] == "deep_probe"
    assert artifacts["latest_contract"]["signed_by"] == ["generator", "evaluator"]
    assert artifacts["latest_verification"]["verdict"] == "partial"
    assert artifacts["latest_selected_action"]["id"] == "plan_deep_probe"


def test_demo_summary_projects_closed_loop_fields():
    final_state = {
        "session_id": "sess-demo",
        "qa_history": [
            _qa_turn(
                turn_idx=0,
                dimension="system_design",
                score=7.0,
                passed=True,
                action="plan_adaptive",
            )
        ],
        "final_report": {
            "overall_score": 7.0,
            "verdict": "pass",
            "closed_loop_ready": True,
            "workflow_artifacts": {
                "latest_ask_plan": {"template": "adaptive"},
                "latest_contract": {"signed_by": ["generator", "evaluator"]},
                "latest_verification": None,
            },
            "contract_summary": {
                "total_checks": 3,
                "checks_yes": 2,
                "checks_partial": 1,
                "checks_no": 0,
            },
            "training_plan": {"source": "fallback"},
        },
    }

    summary = run_demo._build_demo_summary(final_state)  # type: ignore[attr-defined]

    assert summary == {
        "session_id": "sess-demo",
        "turns": 1,
        "overall_score": 7.0,
        "verdict": "pass",
        "closed_loop_ready": True,
        "plan_template": "adaptive",
        "contract_signed_by": ["generator", "evaluator"],
        "verification_verdict": None,
        "training_plan_source": "fallback",
        "contract_checks": {"yes": 2, "partial": 1, "no": 0, "total": 3},
    }


def test_training_plan_marks_report_artifact_when_attached(monkeypatch):
    def fake_training_plan(**_kwargs):
        return {
            "source": "fallback",
            "fallback_reason": "json_parse_failed",
            "priority_weaknesses": [{"dimension": "system_design"}],
            "practice_plan": [],
        }

    monkeypatch.setattr(tp, "build_training_plan", fake_training_plan)
    state = {
        "status": "completed",
        "job_spec": {"title": "Senior Backend Engineer"},
        "candidate": {"name": "Alex"},
        "qa_history": [
            _qa_turn(
                turn_idx=0,
                dimension="system_design",
                score=6.5,
                passed=False,
                action="plan_deep_probe",
            )
        ],
        "final_report": {
            "verdict": "borderline",
            "workflow_artifacts": {
                "latest_ask_plan": {"template": "deep_probe"},
            },
        },
    }

    out = tp.training_plan_node(state)  # type: ignore[arg-type]
    report = out["final_report"]

    assert report["training_plan"]["source"] == "fallback"
    assert report["workflow_artifacts"]["latest_ask_plan"]["template"] == "deep_probe"
    assert report["workflow_artifacts"]["training_plan_attached"] is True
    assert report["workflow_artifacts"]["training_plan_source"] == "fallback"
    assert report["workflow_artifacts"]["training_plan_fallback_reason"] == "json_parse_failed"


def test_training_plan_fallback_is_chinese(monkeypatch):
    def fake_call(*_args: Any, **_kwargs: Any) -> str:
        raise RuntimeError("coach unavailable")

    monkeypatch.setattr(coach, "call_chat", fake_call)

    plan = coach.build_training_plan(
        job_spec={"title": "Java 后端开发工程师"},
        candidate={"name": "刘韩"},
        final_report={"verdict": "borderline", "overall_score": 5.5},
        qa_history=[
            {
                "turn_idx": 0,
                "dimension": "communication",
                "evaluation": {
                    "score": 5.0,
                    "passed": False,
                    "weaknesses": ["回答缺少量化指标和复盘结论。"],
                },
            }
        ],
    )

    assert plan["source"] == "fallback"
    assert plan["priority_weaknesses"][0]["dimension"] == "沟通表达"
    assert "专项练习" in plan["practice_plan"][0]["task"]
    assert "量化指标" in plan["practice_plan"][0]["task"]
    rendered = str(plan)
    assert "Evaluator" not in rendered
    assert "Run a targeted drill" not in rendered
    assert "Close the top-1 weakness" not in rendered


def test_training_plan_fallback_ignores_evaluator_system_fallback(monkeypatch):
    def fake_call(*_args: Any, **_kwargs: Any) -> str:
        raise RuntimeError("coach unavailable")

    monkeypatch.setattr(coach, "call_chat", fake_call)

    plan = coach.build_training_plan(
        job_spec={"title": "Java 后端开发工程师"},
        candidate={"name": "刘韩"},
        final_report={"verdict": "borderline", "overall_score": 6.5},
        qa_history=[
            {
                "turn_idx": 0,
                "dimension": "communication",
                "evaluation": {
                    "source": "fallback",
                    "fallback_reason": "llm_failed",
                    "score": 6.5,
                    "passed": False,
                    "weaknesses": [
                        "Evaluator LLM unavailable; using conservative fallback.",
                        "评估模型暂时不可用，已使用保守兜底评价。",
                    ],
                    "system_warnings": [
                        "评估模型暂时不可用，已使用保守兜底评价。"
                    ],
                },
            }
        ],
    )

    assert plan["source"] == "fallback"
    assert plan["priority_weaknesses"] == []
    assert plan["practice_plan"] == []
    rendered = str(plan)
    assert "Evaluator" not in rendered
    assert "评估模型" not in rendered


def test_training_plan_fallback_omits_nan_score(monkeypatch):
    def fake_call(*_args: Any, **_kwargs: Any) -> str:
        raise RuntimeError("coach unavailable")

    monkeypatch.setattr(coach, "call_chat", fake_call)

    plan = coach.build_training_plan(
        job_spec={"title": "Java 后端开发工程师"},
        candidate={"name": "刘韩"},
        final_report={"verdict": "borderline", "overall_score": math.nan},
        qa_history=[
            {
                "turn_idx": 0,
                "dimension": "communication",
                "evaluation": {"score": 5.0, "passed": False, "weaknesses": []},
            }
        ],
    )

    summary = plan["signal_summary"]
    assert "NaN" not in summary
    assert "nan" not in summary
    assert "总分" not in summary
    assert "接近达标" in summary
