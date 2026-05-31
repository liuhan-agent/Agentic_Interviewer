from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.engine.context.history_context import build_history_context


def _turn(
    turn_idx: int,
    dimension: str,
    *,
    score: float = 7.0,
    passed: bool | None = None,
    answer: str | None = None,
) -> dict[str, Any]:
    return {
        "turn_idx": turn_idx,
        "dimension": dimension,
        "question": f"Question {turn_idx} for {dimension}?",
        "answer": answer if answer is not None else f"Answer {turn_idx}",
        "selected_action": "plan_adaptive",
        "resume_anchor": {"project_name": f"Project {dimension}"},
        "target_skills": ["spring", "redis"],
        "evaluation": {
            "score": score,
            "passed": score >= 7.5 if passed is None else passed,
            "weaknesses": [f"gap {turn_idx}"],
            "recommended_next": "refine" if score < 7.5 else "next_question",
        },
    }


def test_history_context_empty_history_renders_stable_empty_slots() -> None:
    result = build_history_context(
        qa_history=[],
        current_dimension="technical_depth",
    )

    assert result["projection"]["source_qa_count"] == 0
    assert result["projection"]["dimensions"] == []
    assert "INTERVIEW_HISTORY_SUMMARY" in result["history_section"]
    assert "RECENT_QA = []" in result["history_section"]
    assert "CURRENT_GAPS = []" in result["history_section"]
    assert result["selector_summary"] == "(no prior QA history)"
    assert result["prompt_slots"][0]["prompt_label"] == "INTERVIEW_HISTORY_SUMMARY"
    assert result["prompt_slots"][1]["prompt_label"] == "RECENT_QA"
    assert result["prompt_slots"][2]["prompt_label"] == "CURRENT_GAPS"


def test_history_context_projects_older_turns_and_keeps_recent_prompt_view() -> None:
    qa_history = [
        _turn(0, "system_design", score=6.0),
        _turn(1, "system_design", score=7.0),
        _turn(2, "communication", score=8.0),
        _turn(3, "technical_depth", score=7.8),
        _turn(4, "technical_depth", score=8.5),
    ]

    result = build_history_context(
        qa_history=qa_history,
        current_dimension="technical_depth",
    )

    projection = result["projection"]
    assert projection["source_qa_count"] == 5
    assert projection["source_last_turn_idx"] == 4
    by_dim = {item["dimension"]: item for item in projection["dimensions"]}
    assert by_dim["system_design"]["turns"] == 2
    assert by_dim["system_design"]["best_score"] == 7.0
    assert by_dim["technical_depth"]["latest_turn_idx"] == 4
    assert by_dim["technical_depth"]["passed"] is True

    recent_slot = result["prompt_slots"][1]
    assert recent_slot["prompt_label"] == "RECENT_QA"
    assert recent_slot["source_key"] == "recent_qa_prompt_view"
    recent_turns = recent_slot["value"]
    assert [turn["turn_idx"] for turn in recent_turns] == [2, 3, 4]
    assert "Question 4 for technical_depth?" in result["history_section"]
    assert "gap 3" in result["selector_summary"]


def test_history_context_uses_thin_index_for_short_history() -> None:
    qa_history = [
        _turn(0, "system_design", score=6.0),
        _turn(1, "technical_depth", score=7.0),
    ]

    result = build_history_context(
        qa_history=qa_history,
        current_dimension="technical_depth",
    )

    summary_slot = result["prompt_slots"][0]
    summary = summary_slot["value"]
    recent_turns = result["prompt_slots"][1]["value"]

    assert summary["mode"] == "coverage_index"
    assert [turn["turn_idx"] for turn in recent_turns] == [0, 1]
    by_dim = {item["dimension"]: item for item in summary["dimensions"]}
    technical = by_dim["technical_depth"]
    assert technical["turns"] == 1
    assert technical["latest_score"] == 7.0
    assert technical["open_gap_count"] == 1
    assert "open_gaps" not in technical
    assert "last_question" not in technical
    assert "resume_anchor" not in technical
    assert "target_skills" not in technical
    assert "Question 1 for technical_depth?" in result["history_section"]
    assert "gap 1" in result["selector_summary"]


def test_history_context_current_gaps_live_in_dedicated_slot_only() -> None:
    qa_history = [
        _turn(0, "system_design", score=6.0),
        _turn(1, "system_design", score=7.0),
        _turn(2, "communication", score=8.0),
        _turn(3, "technical_depth", score=7.8),
    ]

    result = build_history_context(
        qa_history=qa_history,
        current_dimension="system_design",
    )

    summary_slot = result["prompt_slots"][0]
    gaps_slot = result["prompt_slots"][2]
    summary = summary_slot["value"]

    assert "current_gaps" not in summary
    assert summary["current_gap_count"] == len(gaps_slot["value"])
    assert "system_design" in summary["current_gap_dimensions"]
    assert gaps_slot["prompt_label"] == "CURRENT_GAPS"
    assert gaps_slot["value"] == ["gap 1", "gap 0"]
    for dimension in summary["dimensions"]:
        assert "open_gaps" not in dimension


def test_history_context_keeps_recent_questions_full_before_budget_pressure() -> None:
    long_question = "请详细说明这个复杂链路中的缓存一致性、消息重试和降级恢复。" * 30
    qa_history = [_turn(i, "technical_depth", answer=f"answer {i}") for i in range(4)]
    qa_history[-1]["question"] = long_question

    result = build_history_context(
        qa_history=qa_history,
        current_dimension="technical_depth",
        history_budget_chars=8000,
        recent_question_limit_chars=80,
    )

    recent_turn = result["prompt_slots"][1]["value"][-1]
    assert recent_turn["question"] == long_question
    assert recent_turn["question_truncated"] is False
    assert result["prompt_slots"][1]["prompt_truncated"] is False


def test_history_context_truncates_prompt_view_without_mutating_source() -> None:
    long_answer = "answer-" * 600
    qa_history = [_turn(i, "technical_depth", answer=long_answer) for i in range(4)]
    qa_history[-1]["question"] = "Question requiring careful cache recovery reasoning. " * 20
    original = deepcopy(qa_history)

    result = build_history_context(
        qa_history=qa_history,
        current_dimension="technical_depth",
        history_budget_chars=900,
        recent_answer_soft_limit_chars=80,
        recent_question_limit_chars=60,
    )

    assert qa_history == original
    recent_slot = result["prompt_slots"][1]
    assert recent_slot["truncated"] is True
    assert recent_slot["prompt_truncated"] is True
    assert recent_slot["trace_text_truncated"] is False
    assert any(turn["answer_truncated"] for turn in recent_slot["value"])
    assert any(turn["question_truncated"] for turn in recent_slot["value"])
    assert len(result["history_section"]) <= 900


def test_history_context_compacts_projection_when_summary_exceeds_budget() -> None:
    long_gap = (
        "候选人需要补充线上故障恢复过程中的关键证据，包括指标、日志、回滚决策、"
        "跨团队沟通、根因假设排序以及复盘后的防复发机制。"
    )
    qa_history = []
    for idx in range(10):
        turn = _turn(
            idx,
            f"dimension_{idx % 4}",
            score=6.0 + (idx % 3),
            answer="完整回答不应该被改写。" * 80,
        )
        turn["question"] = f"Question {idx} " + "关于复杂系统排障细节。" * 80
        turn["resume_anchor"] = {
            "project_name": "智学在线教育平台",
            "description": "项目锚点原文很长，不能让它把历史摘要预算吃光。" * 40,
            "skills": ["spring", "redis", "rabbitmq", "elasticsearch"],
        }
        turn["evaluation"]["weaknesses"] = [f"{long_gap} #{idx}-{offset}" for offset in range(5)]
        turn["evaluation"]["strengths"] = [f"已覆盖证据 #{idx}-{offset}" for offset in range(5)]
        qa_history.append(turn)
    original = deepcopy(qa_history)

    result = build_history_context(
        qa_history=qa_history,
        current_dimension="dimension_1",
        history_budget_chars=1600,
        recent_answer_soft_limit_chars=120,
        recent_question_limit_chars=80,
    )

    assert qa_history == original
    assert len(result["history_section"]) <= 1600
    assert result["stats"]["projection_compacted"] is True
    assert result["prompt_slots"][0]["truncated"] is True
    assert result["prompt_slots"][0]["prompt_truncated"] is True
    assert result["prompt_slots"][0]["trace_text_truncated"] is False
    assert "description" not in result["history_section"]


def test_history_context_preserves_three_recent_turns_when_projection_index_is_enough() -> None:
    qa_history = []
    for idx in range(10):
        turn = _turn(
            idx,
            f"dimension_{idx % 4}",
            score=6.5 + (idx % 3),
            answer=f"short answer {idx}",
        )
        turn["resume_anchor"] = {
            "project_name": "智学在线教育平台",
            "description": "非常长的项目锚点文本。" * 80,
        }
        turn["evaluation"]["weaknesses"] = [
            f"需要补充复杂链路排障证据和复盘机制 #{idx}-{offset} " * 8
            for offset in range(5)
        ]
        qa_history.append(turn)

    result = build_history_context(
        qa_history=qa_history,
        current_dimension="dimension_1",
        history_budget_chars=3600,
        recent_answer_soft_limit_chars=120,
        recent_question_limit_chars=80,
    )

    assert len(result["history_section"]) <= 3600
    assert result["stats"]["projection_compacted"] is False
    assert result["stats"]["recent_turn_count"] == 3
    assert [turn["turn_idx"] for turn in result["recent_qa_prompt_view"]] == [7, 8, 9]


def test_history_context_tolerates_malformed_evaluation() -> None:
    qa_history = [
        {"turn_idx": 0, "dimension": "communication", "question": "Q", "answer": "A"},
        {
            "turn_idx": 1,
            "dimension": "communication",
            "question": "Q2",
            "answer": "A2",
            "evaluation": "not-a-dict",
        },
    ]

    result = build_history_context(
        qa_history=qa_history,
        current_dimension="communication",
    )

    dim = result["projection"]["dimensions"][0]
    assert dim["dimension"] == "communication"
    assert dim["turns"] == 2
    assert dim["best_score"] is None
