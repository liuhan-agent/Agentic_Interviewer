"""Coach agent: turns a finished interview into a growth-oriented plan.

Unlike the Evaluator (which scores one answer) and the Verifier
(which reviews one verdict), the Coach looks at the whole session
and produces a structured ``training_plan`` the candidate can act
on. Its scope covers:

- per-dimension strengths and weaknesses across multiple turns;
- suggested practice exercises, ordered by priority;
- measurable 30 / 60 / 90 day goals.

The coach is deterministic-fallback friendly: if the LLM call fails
we still emit a plan derived purely from the evaluator's ``rubric_
coverage`` / ``weaknesses`` payloads. This keeps the end-of-session
experience useful even when the upstream provider is flaky.
"""
from __future__ import annotations

import math
from collections import Counter
from typing import Any

from app.core.logging import get_logger
from app.engine.context import (
    build_context_frame_for_coach,
    frame_to_coach_messages,
)

from .llm_client import call_chat, parse_json_response

log = get_logger(__name__)

DIMENSION_LABELS = {
    "technical_depth": "技术深度",
    "problem_solving": "问题解决",
    "communication": "沟通表达",
    "system_design": "系统设计",
    "architecture": "架构能力",
    "behavioral": "行为面试",
    "leadership": "协作领导力",
}

VERDICT_LABELS = {
    "strong_pass": "表现优秀",
    "pass": "达到目标水平",
    "borderline": "接近达标",
    "fail": "重点补齐",
    "excellent": "表现优秀",
    "target_met": "达到目标水平",
    "near_target": "接近达标",
    "needs_focus": "重点补齐",
    # Legacy persisted reports may still contain hire-language values.
    # Collapse them into candidate-facing growth labels.
    "strong_hire": "表现优秀",
    "hire": "达到目标水平",
    "lean_hire": "接近达标",
    "lean_no_hire": "重点补齐",
    "no_hire": "重点补齐",
    "cancelled": "已取消",
}


def _dimension_label(dimension: Any) -> str:
    raw = str(dimension or "general")
    return DIMENSION_LABELS.get(raw, raw.replace("_", " "))


def _verdict_label(verdict: Any) -> str:
    raw = str(verdict or "unknown")
    return VERDICT_LABELS.get(raw, raw)


def _finite_score(value: Any) -> float | None:
    try:
        score = float(value)
    except (TypeError, ValueError):
        return None
    return score if math.isfinite(score) else None


_SYSTEM_FALLBACK_MARKERS = (
    "Evaluator LLM unavailable",
    "Evaluator LLM failed",
    "conservative fallback",
    "评估模型暂时不可用",
    "保守兜底评价",
)


def _is_system_fallback_text(value: Any) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    lowered = text.lower()
    return any(marker.lower() in lowered for marker in _SYSTEM_FALLBACK_MARKERS)


def _is_evaluator_fallback(evaluation: dict[str, Any]) -> bool:
    return bool(
        evaluation.get("source") == "fallback"
        or evaluation.get("fallback_reason")
        or any(
            _is_system_fallback_text(item)
            for item in (evaluation.get("weaknesses") or [])
        )
    )


def _localise_known_weakness(text: str) -> str:
    known = {
        "Evaluator LLM unavailable; using conservative fallback.": (
            "评估模型暂时不可用，已使用保守兜底评价。"
        ),
        "Evaluator LLM unavailable.": "评估模型暂时不可用。",
    }
    return known.get(text, text)


def _candidate_weaknesses(evaluation: dict[str, Any]) -> list[str]:
    if _is_evaluator_fallback(evaluation):
        return []
    return [
        _localise_known_weakness(str(item))
        for item in (evaluation.get("weaknesses") or [])
        if item and not _is_system_fallback_text(item)
    ]


def _verdict_of(value: Any) -> str:
    """Extract verdict from either legacy string or canonical dict shape."""
    if isinstance(value, dict):
        v = str(value.get("verdict", "")).strip().lower()
    else:
        v = str(value or "").strip().lower()
    return v if v in ("yes", "partial", "no") else "no"


def _truncate_at_boundary(text: str, max_len: int = 300) -> str:
    """Truncate at sentence boundary to avoid mid-word cuts."""
    if not text or len(text) <= max_len:
        return text or ""
    for sep in ("。", "\n", "；", "，", ". ", "; "):
        idx = text.rfind(sep, 0, max_len)
        if idx > max_len // 2:
            return text[: idx + len(sep)].rstrip() + "…"
    return text[:max_len].rstrip() + "…"


def _qa_sort_key(qa: dict[str, Any]) -> float:
    """Score-ascending key; None/fallback scores sort to end."""
    evaluation = qa.get("evaluation") or {}
    if _is_evaluator_fallback(evaluation):
        return float("inf")
    score = _finite_score(evaluation.get("score"))
    return score if score is not None else float("inf")


def _project_qa_for_coach(qa: dict[str, Any]) -> dict[str, Any]:
    """Project one QA turn down to the fields the coach needs."""
    evaluation = qa.get("evaluation") or {}
    is_fallback = _is_evaluator_fallback(evaluation)
    checks = evaluation.get("acceptance_check_results") or {}
    return {
        "turn_idx": qa.get("turn_idx"),
        "dimension": qa.get("dimension"),
        "question": _truncate_at_boundary(qa.get("question", ""), 200),
        "answer_excerpt": _truncate_at_boundary(qa.get("answer", ""), 300),
        "score": evaluation.get("score"),
        "passed": evaluation.get("passed"),
        "weaknesses": _candidate_weaknesses(evaluation),
        "strengths": [] if is_fallback else (evaluation.get("strengths") or []),
        "recommended_next": None if is_fallback else evaluation.get("recommended_next"),
        "resume_anchor": qa.get("resume_anchor") or {},
        "target_skills": qa.get("target_skills") or [],
        "acceptance_verdicts": (
            {k: _verdict_of(v) for k, v in checks.items()} if checks else {}
        ),
    }


def _importance_sample_qa(
    qa_history: list[dict[str, Any]],
    max_turns: int = 12,
) -> list[dict[str, Any]]:
    """Sample QA turns prioritising low scores for coach context.

    Filters out evaluator-fallback turns, sorts by score ascending
    (weakest first), takes up to ``max_turns``, then restores
    chronological order for coherent reading.
    """
    valid = [
        qa for qa in qa_history
        if not _is_evaluator_fallback(qa.get("evaluation") or {})
    ]
    valid.sort(key=_qa_sort_key)
    sampled = valid[:max_turns]
    sampled.sort(key=lambda qa: qa.get("turn_idx", 0))
    return [_project_qa_for_coach(qa) for qa in sampled]


def _build_diagnosis(
    *,
    dim_last_score: dict[str, float],
    final_report: dict[str, Any],
    weakness_count: int,
) -> dict[str, Any]:
    """Deterministic diagnosis from score statistics."""
    overall = _finite_score(final_report.get("overall_score"))
    verdict = _verdict_label(
        final_report.get("growth_signal")
        or final_report.get("overall_verdict")
        or final_report.get("verdict")
    )

    if overall is not None and overall >= 7.5:
        readiness = "基本达标，少数维度需要巩固"
    elif overall is not None and overall >= 5.0:
        readiness = "有一定基础但存在明显短板"
    else:
        readiness = "距离目标岗位要求有较大差距"

    low_dims = sorted(dim_last_score, key=lambda d: dim_last_score[d])[:3]
    gap_parts = [
        f"「{_dimension_label(d)}」({dim_last_score[d]:.1f}分)" for d in low_dims
    ]
    gap = "、".join(gap_parts) + "偏弱" if gap_parts else "尚无足够维度数据"

    patterns = []
    if weakness_count > 3:
        patterns.append("多个维度反复出现同类待改进项")
    if low_dims and dim_last_score.get(low_dims[0], 10) < 5.0:
        patterns.append(f"「{_dimension_label(low_dims[0])}」存在基础性不足")

    return {
        "overall_readiness": readiness,
        "target_level_gap": gap,
        "top_patterns": patterns or ["暂无明显能力结构特征"],
        "verdict": verdict,
    }


def _fallback_training_plan(
    *,
    final_report: dict[str, Any],
    qa_history: list[dict[str, Any]],
) -> dict[str, Any]:
    """Deterministic plan used when the LLM path is unavailable.

    Aggregates evaluator ``weaknesses`` and builds one practice task
    per frequently-appearing weakness phrase. Includes a diagnosis
    layer and structured steps/success_criteria.
    """
    counter: Counter[tuple[str, str]] = Counter()
    dim_last_score: dict[str, float] = {}
    for qa in qa_history:
        evaluation = qa.get("evaluation") or {}
        if _is_evaluator_fallback(evaluation):
            continue
        dim = qa.get("dimension") or "general"
        score = evaluation.get("score")
        if isinstance(score, (int, float)):
            dim_last_score[dim] = float(score)
        for w in _candidate_weaknesses(evaluation):
            if not w:
                continue
            counter[(dim, str(w))] += 1

    priority_weaknesses: list[dict[str, Any]] = []
    practice_plan: list[dict[str, Any]] = []
    for (dim, focus), count in counter.most_common(5):
        dim_label = _dimension_label(dim)
        priority_weaknesses.append(
            {
                "dimension": dim_label,
                "focus": focus,
                "why_it_matters": (
                    f"评估器在 {count} 轮「{dim_label}」中都标记了这个问题。"
                ),
            }
        )
        practice_plan.append(
            {
                "task": f"围绕「{focus}」做一次{dim_label}专项练习。",
                "rationale": "针对本次面试中反复出现的待改进项。",
                "estimated_hours": 2.0,
                "steps": [
                    f"复习「{dim_label}」相关核心知识点。",
                    f"针对「{focus}」做 2-3 道练习题或案例分析。",
                    "总结错误模式，记录到个人知识库。",
                ],
                "success_criteria": [
                    f"能独立回答与「{focus}」相关的面试问题。",
                    f"在模拟面试中「{dim_label}」维度得分提升 1 分以上。",
                ],
            }
        )

    lowest_dim = None
    if dim_last_score:
        lowest_dim = min(dim_last_score, key=lambda d: dim_last_score[d])

    score = _finite_score(final_report.get("overall_score"))
    verdict_label = _verdict_label(
        final_report.get("growth_signal")
        or final_report.get("overall_verdict")
        or final_report.get("verdict")
    )
    if lowest_dim:
        score_clause = f"总分 {score:.2f}。" if score is not None else ""
        summary = (
            f"综合表现：{verdict_label}，"
            f"{score_clause}下一阶段优先提升「{_dimension_label(lowest_dim)}」。"
        )
    else:
        summary = f"综合表现：{verdict_label}。"

    diagnosis = _build_diagnosis(
        dim_last_score=dim_last_score,
        final_report=final_report,
        weakness_count=len(counter),
    )

    top_dim = priority_weaknesses[0]["dimension"] if priority_weaknesses else "核心能力"
    second_dim = (
        priority_weaknesses[1]["dimension"]
        if len(priority_weaknesses) > 1
        else "综合能力"
    )

    return {
        "diagnosis": diagnosis,
        "priority_weaknesses": priority_weaknesses,
        "practice_plan": practice_plan,
        "goals_30_60_90": {
            "30_days": [
                f"完成「{top_dim}」中最优先待改进项的补强。",
                f"整理「{top_dim}」相关的学习笔记和错题集。",
            ],
            "60_days": [
                f"通过一次模拟复盘面试验证「{top_dim}」改进效果。",
                f"开始补强「{second_dim}」维度。",
            ],
            "90_days": [
                "在一个接近真实生产场景的项目中巩固改进。",
                "进行一次完整的模拟面试，回顾各维度的提升情况。",
            ],
        },
        "signal_summary": summary,
        "source": "fallback",
    }


def _normalize_llm_plan(data: dict[str, Any]) -> dict[str, Any]:
    """Ensure LLM output has required fields with sane defaults.

    Patches missing keys rather than falling back entirely, so
    partial LLM successes are preserved.
    """
    if "diagnosis" not in data or not isinstance(data.get("diagnosis"), dict):
        data["diagnosis"] = {
            "overall_readiness": "",
            "target_level_gap": "",
            "top_patterns": [],
        }
    else:
        diag = data["diagnosis"]
        diag.setdefault("overall_readiness", "")
        diag.setdefault("target_level_gap", "")
        diag.setdefault("top_patterns", [])

    for item in data.get("practice_plan") or []:
        if isinstance(item, dict):
            item.setdefault("steps", [])
            item.setdefault("success_criteria", [])
            item.setdefault("estimated_hours", 2.0)

    goals = data.get("goals_30_60_90")
    if not isinstance(goals, dict):
        data["goals_30_60_90"] = {"30_days": [], "60_days": [], "90_days": []}
    else:
        for key in ("30_days", "60_days", "90_days"):
            goals.setdefault(key, [])

    data.setdefault("signal_summary", "")
    data.setdefault("priority_weaknesses", [])
    data.setdefault("practice_plan", [])
    return data


def build_training_plan(
    *,
    job_spec: dict[str, Any],
    candidate: dict[str, Any],
    final_report: dict[str, Any],
    qa_history: list[dict[str, Any]],
    self_intro_profile: dict[str, Any] | None = None,
    verification: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a structured training plan for the candidate.

    Never raises; degrades to :func:`_fallback_training_plan` on any
    LLM failure.
    """
    qa_tailored = _importance_sample_qa(qa_history)
    frame = build_context_frame_for_coach(
        job_spec=job_spec or {},
        candidate=candidate or {},
        final_report=final_report or {},
        qa_tailored=qa_tailored,
        self_intro_profile=self_intro_profile,
        verification_summary=verification,
    )
    messages = frame_to_coach_messages(frame)
    try:
        raw = call_chat(messages, json_mode=True, agent_role="coach")
        data = parse_json_response(raw)
    except Exception as e:  # pragma: no cover
        log.warning("coach LLM call failed, using fallback: %s", e)
        return _fallback_training_plan(
            final_report=final_report,
            qa_history=qa_history,
        )

    if not isinstance(data, dict) or not data:
        return _fallback_training_plan(
            final_report=final_report,
            qa_history=qa_history,
        )

    data = _normalize_llm_plan(data)
    data.setdefault("source", "llm")
    return data
