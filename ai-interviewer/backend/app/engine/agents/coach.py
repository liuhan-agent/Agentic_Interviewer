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

import json
import math
import re
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


def _dimension_score_item(final_report: dict[str, Any], dimension: Any) -> dict[str, Any]:
    scores = (final_report or {}).get("dimension_scores") or {}
    item = scores.get(str(dimension or ""))
    return item if isinstance(item, dict) else {}


def _score_status_for_dimension(final_report: dict[str, Any], dimension: Any) -> str | None:
    item = _dimension_score_item(final_report, dimension)
    status = item.get("score_status")
    return str(status) if status else None


def _coverage_status_for_dimension(final_report: dict[str, Any], dimension: Any) -> str | None:
    item = _dimension_score_item(final_report, dimension)
    status = item.get("coverage_status")
    return str(status) if status else None


def _dimension_is_scored_for_report(
    final_report: dict[str, Any],
    dimension: Any,
) -> bool:
    item = _dimension_score_item(final_report, dimension)
    if not item:
        return True
    return item.get("score_status") == "scored"


def _is_scored_evaluator_turn(
    qa: dict[str, Any],
    final_report: dict[str, Any] | None = None,
) -> bool:
    evaluation = qa.get("evaluation") or {}
    if evaluation.get("skipped") or qa.get("answer_intent") == "skipped":
        return False
    if _is_evaluator_fallback(evaluation):
        return False
    if _finite_score(evaluation.get("score")) is None:
        return False

    status = _score_status_for_dimension(final_report or {}, qa.get("dimension"))
    if status is None:
        return True
    return status == "scored"


def _coach_context_report(final_report: dict[str, Any]) -> dict[str, Any]:
    """Return the report projection the Coach may use as training signal.

    The persisted final report keeps all dimensions for audit/UI, but
    the Coach should not infer ability weaknesses from skipped,
    not-evaluated, or evaluator-unavailable dimensions. Coverage-limited
    dimensions stay visible with weaknesses cleared so the plan can
    ask for more evidence rather than treating them as low ability.
    """
    report = dict(final_report or {})
    dimension_summaries = report.get("dimension_summaries") or {}
    filtered_summaries: dict[str, Any] = {}
    coverage_limited: list[str] = []
    for dim, summary in dimension_summaries.items():
        if not _dimension_is_scored_for_report(report, dim):
            continue
        if isinstance(summary, dict):
            next_summary = dict(summary)
        else:
            next_summary = summary
        if _coverage_status_for_dimension(report, dim) == "coverage_limited":
            coverage_limited.append(str(dim))
            if isinstance(next_summary, dict):
                next_summary["weaknesses"] = []
        elif isinstance(next_summary, dict):
            next_summary["weaknesses"] = _sanitize_training_plan_text(
                next_summary.get("weaknesses") or []
            )
        filtered_summaries[str(dim)] = next_summary
    report["dimension_summaries"] = filtered_summaries
    policy = dict(report.get("coach_generation_policy") or {})
    policy["training_signal"] = (
        "only scored evaluator dimensions; skipped/not_evaluated/"
        "evaluator_unavailable excluded"
    )
    policy["coverage_limited_dimensions"] = sorted(coverage_limited)
    report["coach_generation_policy"] = policy
    return report


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


_GATE_ENFORCEMENT_WEAKNESS_RE = re.compile(
    r"^\s*Reviewed core acceptance failed(?:\s*\([^)]+\))?:?\s*(.*)$",
    re.IGNORECASE,
)


def _candidate_readable_weakness(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    match = _GATE_ENFORCEMENT_WEAKNESS_RE.match(text)
    if not match:
        return text
    detail = (match.group(1) or "").strip()
    if detail:
        return f"核心判定条款未满足：{detail}"
    return "核心判定条款未满足：需要补充核心判定条款的证据。"


def _sanitize_training_plan_text(value: Any) -> Any:
    if isinstance(value, str):
        return _candidate_readable_weakness(value)
    if isinstance(value, list):
        return [_sanitize_training_plan_text(item) for item in value]
    if isinstance(value, dict):
        return {
            key: _sanitize_training_plan_text(item)
            for key, item in value.items()
        }
    return value


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
    return known.get(text, _candidate_readable_weakness(text))


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
    final_report: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Sample QA turns prioritising low scores for coach context.

    Filters out evaluator-fallback turns, sorts by score ascending
    (weakest first), takes up to ``max_turns``, then restores
    chronological order for coherent reading.
    """
    valid = [
        qa for qa in qa_history
        if _is_scored_evaluator_turn(qa, final_report)
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
    fallback_reason: str | None = None,
) -> dict[str, Any]:
    """Deterministic plan used when the LLM path is unavailable.

    Aggregates evaluator ``weaknesses`` and builds one practice task
    per frequently-appearing weakness phrase. Includes a diagnosis
    layer and structured steps/success_criteria.
    """
    counter: Counter[tuple[str, str]] = Counter()
    dim_last_score: dict[str, float] = {}
    coverage_limited_dims: dict[str, int] = {}
    for qa in qa_history:
        evaluation = qa.get("evaluation") or {}
        if not _is_scored_evaluator_turn(qa, final_report):
            continue
        dim = qa.get("dimension") or "general"
        score = _finite_score(evaluation.get("score"))
        if score is not None:
            dim_last_score[dim] = score
        if _coverage_status_for_dimension(final_report, dim) == "coverage_limited":
            key = str(dim)
            coverage_limited_dims[key] = coverage_limited_dims.get(key, 0) + 1
            continue
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

    for dim, count in sorted(coverage_limited_dims.items()):
        dim_label = _dimension_label(dim)
        focus = f"补充「{dim_label}」维度的回答证据与覆盖面"
        priority_weaknesses.append(
            {
                "dimension": dim_label,
                "focus": focus,
                "why_it_matters": (
                    f"该维度已有有效评分，但还有 {count} 轮信号显示覆盖不足；"
                    "下一轮重点是补足证据，而不是按低分能力弱项处理。"
                ),
                "category": "coverage_limited",
            }
        )
        practice_plan.append(
            {
                "task": f"围绕「{dim_label}」补充一次证据覆盖练习",
                "rationale": "该维度得分有效，但证据覆盖仍不完整，需要补充更可验证的例子、边界和取舍。",
                "estimated_hours": 1.5,
                "steps": [
                    f"复盘「{dim_label}」维度已有回答，列出已经覆盖和未覆盖的检查点。",
                    "补充 1 个具体项目例子，写清背景、动作、指标、结果和取舍。",
                    "用 3 分钟口述一版答案，确保每个关键结论都有证据支撑。",
                ],
                "success_criteria": [
                    f"能够用至少 2 个具体证据支撑「{dim_label}」维度的核心结论。",
                    "再次模拟时不再出现覆盖不足或证据不足提示。",
                ],
                "category": "coverage_limited",
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

    plan = {
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
    if fallback_reason:
        plan["fallback_reason"] = fallback_reason
    return plan


_COACH_PLAN_KEYS = {
    "diagnosis",
    "priority_weaknesses",
    "practice_plan",
    "goals_30_60_90",
    "signal_summary",
}


def _looks_like_empty_json_object(text: str) -> bool:
    stripped = (text or "").strip()
    if not stripped:
        return False
    if stripped.startswith("```"):
        stripped = stripped.strip("`").strip()
        if stripped.lower().startswith("json"):
            stripped = stripped[4:].strip()
    try:
        return json.loads(stripped) == {}
    except json.JSONDecodeError:
        return False


def _has_coach_plan_shape(data: dict[str, Any]) -> bool:
    return any(key in data for key in _COACH_PLAN_KEYS)


def _fallback_with_reason(
    *,
    reason: str,
    final_report: dict[str, Any],
    qa_history: list[dict[str, Any]],
) -> dict[str, Any]:
    plan = _fallback_training_plan(
        final_report=final_report,
        qa_history=qa_history,
        fallback_reason=reason,
    )
    return plan


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
    cleaned = _sanitize_training_plan_text(data)
    return cleaned if isinstance(cleaned, dict) else data


def _decode_llm_training_plan(raw: Any) -> tuple[dict[str, Any] | None, str]:
    raw_text = str(raw or "").strip()
    if not raw_text:
        return None, "empty_output"

    try:
        data = parse_json_response(raw)
    except Exception as e:  # pragma: no cover
        log.warning("coach LLM response parse raised: %s", e)
        return None, "json_parse_failed"

    if not isinstance(data, dict):
        return None, "invalid_structure"
    if not data:
        reason = (
            "invalid_structure"
            if _looks_like_empty_json_object(raw_text)
            else "json_parse_failed"
        )
        return None, reason
    if not _has_coach_plan_shape(data):
        return None, "invalid_structure"
    return data, ""


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
    coach_report = _coach_context_report(final_report or {})
    qa_tailored = _importance_sample_qa(qa_history, final_report=coach_report)
    frame = build_context_frame_for_coach(
        job_spec=job_spec or {},
        candidate=candidate or {},
        final_report=coach_report,
        qa_tailored=qa_tailored,
        self_intro_profile=self_intro_profile,
        verification_summary=verification,
    )
    messages = frame_to_coach_messages(frame)
    last_reason = "json_parse_failed"
    for attempt in range(2):
        try:
            raw = call_chat(messages, json_mode=True, agent_role="coach")
        except Exception as e:  # pragma: no cover
            log.warning("coach LLM call failed, using fallback: %s", e)
            return _fallback_with_reason(
                reason="llm_call_failed",
                final_report=coach_report,
                qa_history=qa_history,
            )

        data, reason = _decode_llm_training_plan(raw)
        if data is not None:
            data = _normalize_llm_plan(data)
            data.setdefault("source", "llm")
            return data

        last_reason = reason
        if attempt == 0:
            log.info("coach LLM output invalid (%s), retrying once", reason)

    return _fallback_with_reason(
        reason=last_reason,
        final_report=coach_report,
        qa_history=qa_history,
    )
