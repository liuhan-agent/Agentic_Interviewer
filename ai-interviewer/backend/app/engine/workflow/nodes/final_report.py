"""Synthesize the final interview report.

MVP version: aggregate scores and produce a deterministic report. An
optional LLM summarisation step can be plugged in later without
changing the node signature.
"""
from __future__ import annotations

import math
from typing import Any

from app.core.logging import get_logger
from app.core.metrics import estimate_llm_cost_usd
from app.core.settings import get_settings
from app.core.tracer import get_tracer
from app.core.video_signals_schema import normalize_video_signals
from app.services.scoring_quality import (
    acceptance_counts as _quality_acceptance_counts,
    build_scoring_quality_summary,
    evidence_summary as _quality_evidence_summary,
    merge_contract_checks as _quality_merge_contract_checks,
    verdict_of as _quality_verdict_of,
)
from app.engine.workflow.eval_helpers import (
    is_evaluator_fallback as _is_evaluator_fallback,
)
from app.engine.workflow.eval_helpers import (
    is_system_fallback_text as _is_system_fallback_text,
)
from app.engine.workflow.followup_reason import sanitize_replay_followup_reason
from app.engine.workflow.replay_basis import sanitize_replay_question_basis
from app.engine.workflow.score_aggregation import build_score_breakdowns_from_qa
from app.engine.workflow.state import InterviewState
from app.services.scoring_credibility import compute_credibility

log = get_logger(__name__)


_EVALUATOR_FALLBACK_WARNING = "评估模型暂时不可用，已使用保守兜底评价。"


def _candidate_weaknesses(evaluation: dict[str, Any]) -> list[Any]:
    return [
        item
        for item in (evaluation.get("weaknesses") or [])
        if not _is_system_fallback_text(item)
    ]


def _candidate_strengths(evaluation: dict[str, Any]) -> list[Any]:
    if _is_evaluator_fallback(evaluation):
        return []
    return list(evaluation.get("strengths") or [])


def _candidate_rationale(evaluation: dict[str, Any]) -> str:
    rationale = str(evaluation.get("rationale") or "")
    if _is_system_fallback_text(rationale):
        return ""
    return rationale


def _system_warnings(evaluation: dict[str, Any]) -> list[Any]:
    warnings = [
        item
        for item in (evaluation.get("system_warnings") or [])
        if not _is_system_fallback_text(item)
    ]
    if _is_evaluator_fallback(evaluation):
        warnings.append(_EVALUATOR_FALLBACK_WARNING)
    return _dedupe(warnings)


def _finite_score(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        score = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(score):
        return None
    return score


def _overall_score(dimension_scores: dict[str, dict[str, Any]]) -> float | None:
    valid = [
        score
        for item in dimension_scores.values()
        if item.get("score_status") == "scored"
        for score in [_finite_score(item.get("score"))]
        if score is not None
    ]
    if not valid:
        return None
    return round(sum(valid) / len(valid), 2)


def _verdict(overall: float, threshold: float) -> str:
    if overall >= threshold + 0.5:
        return "strong_pass"
    if overall >= threshold:
        return "pass"
    if overall >= threshold - 1.5:
        return "borderline"
    return "fail"


# Candidate-facing projection. The internal pass/fail vocabulary is
# intentionally kept for tracer / analytics / RL consumers, while the
# report UI gets growth-oriented language instead of hiring decisions.
_VERDICT_TO_GROWTH_SIGNAL = {
    "strong_pass": "excellent",
    "pass": "target_met",
    "borderline": "near_target",
    "fail": "needs_focus",
    "cancelled": "cancelled",
    "unknown": "unknown",
}


def _growth_signal(verdict: str) -> str:
    return _VERDICT_TO_GROWTH_SIGNAL.get(verdict, "unknown")


def _overall_verdict(verdict: str) -> str:
    # Deprecated frontend alias. Keep the field for old clients and
    # persisted-history readers, but project the same candidate-facing
    # growth signal used by new clients.
    return _growth_signal(verdict)


def _coverage_warnings(
    dimension_scores: dict[str, dict[str, Any]],
    dimension_status: dict[str, str],
) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    for dim, status in sorted(dimension_status.items()):
        if status == "passed":
            continue
        score_item = dimension_scores.get(dim) or {}
        warnings.append(
            {
                "dimension": dim,
                "status": status,
                "score": score_item.get("score"),
            }
        )
    return warnings


def _coverage_limited_verdict(
    verdict: str,
    coverage_warnings: list[dict[str, Any]],
) -> str:
    if not coverage_warnings:
        return verdict
    if verdict in {"strong_pass", "pass"}:
        return "borderline"
    return verdict


def _build_dimension_scores(
    scores_per_dim: dict[str, float | None],
    dimension_status: dict[str, str],
    dimension_summaries: dict[str, dict[str, Any]],
    qa_history: list[dict[str, Any]] | None = None,
    quality_threshold: float = 7.5,
    score_breakdowns: dict[str, dict[str, Any]] | None = None,
) -> dict[str, dict[str, Any]]:
    """Project the rich ``dimension_summaries`` map into the frontend
    ``RubricScore`` contract (``score`` / ``passed`` / ``rationale`` /
    ``weaknesses``).

    Rationale is taken from the latest evidence entry for the dim
    since that captures the evaluator's most recent judgement; the
    earlier turns are already surfaced via ``dimension_summaries``
    for callers that want the full trail.
    """
    turn_meta = _dimension_turn_meta(qa_history or [])
    rebuilt_breakdowns = build_score_breakdowns_from_qa(qa_history or [])
    available_breakdowns = dict(rebuilt_breakdowns)
    available_breakdowns.update(score_breakdowns or {})
    out: dict[str, dict[str, Any]] = {}
    dims = (
        set(scores_per_dim.keys())
        | set(dimension_status.keys())
        | set(dimension_summaries.keys())
        | set(turn_meta.keys())
        | set(available_breakdowns.keys())
    )
    for dim in dims:
        summary = dimension_summaries.get(dim) or {}
        evidence = summary.get("evidence") or []
        latest = evidence[-1] if evidence else {}
        meta = turn_meta.get(dim) or {}
        breakdown = _normalise_score_breakdown(available_breakdowns.get(dim))
        stored_score = _finite_score(scores_per_dim.get(dim))
        effective_score = _finite_score((breakdown or {}).get("adopted_score"))
        if effective_score is None:
            effective_score = stored_score
        if effective_score is None and meta.get("scored"):
            effective_score = _finite_score(meta.get("latest_score"))
        score_status = _score_status(
            stored_score=stored_score,
            effective_score=effective_score,
            turn_meta=meta,
            has_score_breakdown=breakdown is not None,
        )
        score = effective_score if score_status == "scored" else None
        exclusion_reason = None if score_status == "scored" else score_status
        item = {
            "score": score,
            "score_status": score_status,
            "excluded_from_overall": score_status != "scored",
            "exclusion_reason": exclusion_reason,
            "coverage_status": _coverage_status(
                score_status=score_status,
                score=score,
                dimension_status=dimension_status.get(dim),
                quality_threshold=quality_threshold,
            ),
            "passed": dimension_status.get(dim) == "passed",
            "rationale": latest.get("rationale") or None,
            "weaknesses": list(summary.get("weaknesses") or []),
        }
        if score_status == "scored" and breakdown is not None:
            item["score_breakdown"] = breakdown
        out[dim] = item
    return out


def _normalise_score_breakdown(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    adopted = _finite_score(value.get("adopted_score"))
    latest = _finite_score(value.get("latest_score"))
    best = _finite_score(value.get("best_score"))
    average = _finite_score(value.get("average_score"))
    try:
        count = int(value.get("scored_turn_count") or 0)
    except (TypeError, ValueError):
        count = 0
    if adopted is None or latest is None or best is None or average is None or count <= 0:
        return None
    return {
        "scored_turn_count": count,
        "latest_score": latest,
        "best_score": best,
        "average_score": average,
        "adopted_score": adopted,
        "scoring_policy": str(value.get("scoring_policy") or "weighted_recent"),
    }


def _dimension_turn_meta(
    qa_history: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    meta: dict[str, dict[str, Any]] = {}
    for qa in qa_history:
        dim = str(qa.get("dimension") or "")
        if not dim:
            continue
        bucket = meta.setdefault(
            dim,
            {
                "scored": False,
                "skipped": False,
                "evaluator_unavailable": False,
                "latest_score": None,
            },
        )
        evaluation = qa.get("evaluation") or {}
        if evaluation.get("skipped") or qa.get("answer_intent") == "skipped":
            bucket["skipped"] = True
            continue
        if _is_evaluator_fallback(evaluation):
            bucket["evaluator_unavailable"] = True
            continue
        score = _finite_score(evaluation.get("score"))
        if score is None:
            continue
        bucket["scored"] = True
        bucket["latest_score"] = score
    return meta


def _score_status(
    *,
    stored_score: float | None,
    effective_score: float | None,
    turn_meta: dict[str, Any],
    has_score_breakdown: bool = False,
) -> str:
    if turn_meta.get("scored") and effective_score is not None:
        return "scored"
    if has_score_breakdown and effective_score is not None:
        return "scored"
    # Legacy persisted reports may only have an aggregate positive
    # dimension score and no qa_history evidence. Keep those readable;
    # legacy 0.0 without evaluator evidence remains unscored.
    if not turn_meta and stored_score is not None and stored_score > 0:
        return "scored"
    if turn_meta.get("skipped"):
        return "skipped"
    if turn_meta.get("evaluator_unavailable"):
        return "evaluator_unavailable"
    return "not_evaluated"


def _coverage_status(
    *,
    score_status: str,
    score: float | None,
    dimension_status: str | None,
    quality_threshold: float,
) -> str:
    if score_status != "scored":
        return "not_applicable"
    if dimension_status == "passed":
        return "passed"
    if score is not None and score < quality_threshold:
        return "below_threshold"
    return "coverage_limited"


def _score_summary(
    dimension_scores: dict[str, dict[str, Any]],
) -> dict[str, int]:
    scored = sum(
        1 for item in dimension_scores.values() if item.get("score_status") == "scored"
    )
    total = len(dimension_scores)
    return {
        "scored_dimension_count": scored,
        "excluded_dimension_count": total - scored,
        "total_dimension_count": total,
    }


def _dedupe(items: list[Any]) -> list[Any]:
    seen: set[str] = set()
    out: list[Any] = []
    for item in items:
        if item in (None, ""):
            continue
        key = str(item)
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _answer_excerpt(answer: str, *, limit: int = 220) -> str:
    answer = " ".join((answer or "").split())
    if len(answer) <= limit:
        return answer
    return answer[: limit - 3].rstrip() + "..."


def _verdict_of(value: Any) -> str:
    """Extract the verdict from either legacy string or canonical dict shape.

    Kept local to this module so the closed-loop report can consume
    mixed-shape ``acceptance_check_results`` (old DB snapshots + new
    evaluator output) without importing the agent-layer helper.
    """
    return _quality_verdict_of(value)


def _acceptance_counts(checks: dict[str, Any]) -> dict[str, int]:
    return _quality_acceptance_counts(checks)


def _evidence_summary(qa_history: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate evidence-span match health for the report UI."""
    return _quality_evidence_summary(qa_history)


def _merge_contract_checks(
    existing: dict[str, str],
    incoming: dict[str, Any],
) -> dict[str, str]:
    """Merge check results by text, keeping the latest observed verdict.

    The merged dictionary holds **verdict strings only** (not full
    dicts): downstream ``contract_summary.checks_*`` only cares about
    the verdict distribution, and the per-turn evidence is preserved
    separately under ``dimension_summaries[dim].evidence[*].acceptance_checks``.
    """
    return _quality_merge_contract_checks(existing, incoming)


def _followup_reason(evaluation: dict[str, Any]) -> str | None:
    if _is_evaluator_fallback(evaluation):
        return None
    if evaluation.get("recommended_next") != "refine":
        return None
    plan = evaluation.get("recommended_next_plan") or "adaptive"
    return f"refine -> {plan}"


def _turn_evidence(qa: dict[str, Any]) -> dict[str, Any]:
    evaluation = qa.get("evaluation") or {}
    evidence = {
        "turn_idx": qa.get("turn_idx"),
        "question": qa.get("question"),
        "answer": str(qa.get("answer") or ""),
        "answer_excerpt": _answer_excerpt(str(qa.get("answer") or "")),
        "selected_action": qa.get("selected_action"),
        "target_skills": qa.get("target_skills") or [],
        "skill_focus": qa.get("skill_focus") or {},
        "score": evaluation.get("score"),
        "passed": evaluation.get("passed"),
        "rationale": _candidate_rationale(evaluation),
        "strengths": _candidate_strengths(evaluation),
        "weaknesses": _candidate_weaknesses(evaluation),
        "system_warnings": _system_warnings(evaluation),
        "rubric_coverage": evaluation.get("rubric_coverage") or {},
        "acceptance_checks": evaluation.get("acceptance_check_results") or {},
        "recommended_next": evaluation.get("recommended_next"),
        "recommended_next_plan": evaluation.get("recommended_next_plan"),
        "soft_warnings": evaluation.get("soft_warnings") or [],
    }
    followup_reason = sanitize_replay_followup_reason(
        evaluation.get("followup_reason")
    )
    if followup_reason is not None:
        evidence["followup_reason"] = followup_reason
    question_basis = sanitize_replay_question_basis(qa.get("question_basis"))
    if question_basis is not None:
        evidence["question_basis"] = question_basis
    return evidence


def _build_cost_summary() -> dict[str, Any] | None:
    """Project the active SessionHandle's LLM cost tallies into the report.

    Returns ``None`` when no SessionHandle is bound (CLI demo /
    unit tests that drive the graph without the session manager) or
    when no LLM call has been booked yet (defensive guard so a fresh
    session does not emit a noise row of zeros).
    """
    try:
        from app.services.session_manager import get_current_session_handle
    except ImportError:  # pragma: no cover - session manager always present in app
        return None
    handle = get_current_session_handle()
    if handle is None or handle.llm_call_count <= 0:
        return None
    model = get_settings().llm_model
    est_usd = estimate_llm_cost_usd(
        model=model,
        prompt_tokens=handle.prompt_tokens_total,
        completion_tokens=handle.completion_tokens_total,
    )
    return {
        "calls": int(handle.llm_call_count),
        "stub_calls": int(handle.llm_stub_call_count),
        "error_calls": int(handle.llm_error_call_count),
        "prompt_tokens": int(handle.prompt_tokens_total),
        "completion_tokens": int(handle.completion_tokens_total),
        "total_tokens": int(
            handle.prompt_tokens_total + handle.completion_tokens_total
        ),
        "est_usd": float(est_usd),
        "usage_estimated": bool(handle.cost_usage_estimated),
        "model_for_pricing": model,
    }


def _video_analysis_summary(
    qa_history: list[dict[str, Any]],
    latest_video_signals: Any,
) -> dict[str, Any] | None:
    signals: list[tuple[int | None, dict[str, Any]]] = []
    for qa in qa_history:
        normalized = normalize_video_signals(qa.get("video_signals"))
        if normalized is not None:
            turn_idx = qa.get("turn_idx")
            signals.append((turn_idx if isinstance(turn_idx, int) else None, normalized))

    if not signals:
        normalized = normalize_video_signals(latest_video_signals)
        if normalized is None:
            return None
        signals.append((None, normalized))

    total_samples = sum(int(signal["sample_count"]) for _, signal in signals)
    if total_samples <= 0:
        return None

    avg_confidence = (
        sum(float(signal["confidence"]) * int(signal["sample_count"]) for _, signal in signals)
        / total_samples
    )
    avg_engagement = (
        sum(float(signal["engagement"]) * int(signal["sample_count"]) for _, signal in signals)
        / total_samples
    )
    emotion_counts: dict[str, int] = {}
    for _, signal in signals:
        emotion = str(signal["dominant_emotion"])
        emotion_counts[emotion] = emotion_counts.get(emotion, 0) + int(
            signal["sample_count"]
        )
    dominant_emotion = max(emotion_counts.items(), key=lambda item: item[1])[0]

    per_turn_signals = [
        {
            "turn_idx": turn_idx,
            "engagement": signal["engagement"],
            "confidence": signal["confidence"],
            "emotion": signal["dominant_emotion"],
        }
        for turn_idx, signal in signals
        if turn_idx is not None
    ]

    payload = {
        "avg_engagement": round(avg_engagement, 2),
        "avg_confidence": round(avg_confidence, 2),
        "dominant_emotion": dominant_emotion,
    }
    if per_turn_signals:
        payload["per_turn_signals"] = per_turn_signals
    return payload


def _workflow_artifacts(state: InterviewState) -> dict[str, Any]:
    return {
        "qa_summary": state.get("qa_summary", ""),
        "latest_ask_plan": state.get("current_ask_plan"),
        "latest_contract": state.get("current_contract"),
        "latest_verification": state.get("verification"),
        "latest_selected_action": state.get("selected_action"),
        "latest_skill_focus": state.get("current_skill_focus"),
        "latest_target_skills": (state.get("current_question") or {}).get(
            "target_skills",
            [],
        ),
        "target_skill_coverage": _target_skill_coverage(
            state.get("qa_history", []),
        ),
    }


def _target_skill_coverage(qa_history: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for qa in qa_history:
        for skill in qa.get("target_skills") or []:
            key = str(skill)
            counts[key] = counts.get(key, 0) + 1
    return counts


def final_report_node(state: InterviewState) -> dict[str, Any]:
    scores = state.get("scores_per_dim", {})
    threshold = state.get("quality_threshold", 7.5)

    qa_history = state.get("qa_history", [])
    dimension_summaries: dict[str, dict[str, Any]] = {}
    for qa in qa_history:
        dim = qa.get("dimension", "unknown")
        bucket = dimension_summaries.setdefault(
            dim,
            {
                "turns": 0,
                "avg_score": 0.0,
                "passed_turns": 0,
                "strengths": [],
                "weaknesses": [],
                "rubric_coverage": {},
                "contract_checks": {"yes": 0, "partial": 0, "no": 0, "total": 0},
                "followup_reasons": [],
                "evidence": [],
            },
        )
        bucket["turns"] += 1
        evaluation = qa.get("evaluation") or {}
        if evaluation.get("passed"):
            bucket["passed_turns"] += 1
        bucket["avg_score"] = _finite_score(scores.get(dim))
        candidate_weaknesses = _candidate_weaknesses(evaluation)
        bucket["strengths"].extend(_candidate_strengths(evaluation))
        bucket["weaknesses"].extend(candidate_weaknesses)
        bucket["rubric_coverage"].update(evaluation.get("rubric_coverage") or {})
        checks = evaluation.get("acceptance_check_results") or {}
        bucket["contract_checks"] = _acceptance_counts(checks)
        reason = _followup_reason(evaluation)
        if reason:
            bucket["followup_reasons"].append(reason)
        bucket["evidence"].append(_turn_evidence(qa))

    for bucket in dimension_summaries.values():
        bucket["strengths"] = _dedupe(bucket["strengths"])
        bucket["weaknesses"] = _dedupe(bucket["weaknesses"])
        bucket["followup_reasons"] = _dedupe(bucket["followup_reasons"])

    verification = state.get("verification") or {}

    # Preserve an upstream ``cancelled`` marker so downstream consumers
    # (API, tracer, analytics) can tell a real completion apart from
    # an early teardown; emitting ``verdict: cancelled`` makes the
    # difference observable in the report payload itself.
    incoming_status = state.get("status")
    dimension_status = state.get("dimension_status", {})
    dimension_scores = _build_dimension_scores(
        scores,
        dimension_status,
        dimension_summaries,
        qa_history,
        threshold,
        score_breakdowns=state.get("score_breakdowns") or {},
    )
    score_summary = _score_summary(dimension_scores)
    overall = _overall_score(dimension_scores)
    coverage_warnings = _coverage_warnings(dimension_scores, dimension_status)
    if incoming_status == "cancelled":
        verdict = "cancelled"
    elif overall is None:
        verdict = "unknown"
    else:
        verdict = _verdict(overall, threshold)
        verdict = _coverage_limited_verdict(verdict, coverage_warnings)
    growth_signal = _growth_signal(verdict)

    # Surface evaluator fallback rate so the report UI can warn when
    # too much of the session was scored on the conservative path
    # (audit follow-up B3). Computed here to avoid the front-end
    # re-walking ``qa_history`` just for a banner trigger.
    evaluator_fallback_count = sum(
        1
        for qa in qa_history
        if _is_evaluator_fallback(qa.get("evaluation") or {})
    )
    quality_summary = build_scoring_quality_summary(
        qa_history=qa_history,
        verification=verification,
        evaluator_fallback_count=evaluator_fallback_count,
    )
    # Frontend-facing projection: the Next.js ``ReportView`` consumes
    # ``growth_signal`` and ``dimension_scores`` (RubricScore shape).
    # We keep the internal ``verdict`` and ``dimension_summaries``
    # fields intact so tracer / analytics / existing tests keep working.
    report = {
        "session_id": state.get("session_id"),
        "trace_id": state.get("trace_id"),
        "candidate": state.get("candidate", {}).get("name"),
        "job_title": state.get("job_spec", {}).get("title"),
        "overall_score": overall,
        "quality_threshold": threshold,
        "verdict": verdict,
        "growth_signal": growth_signal,
        "overall_verdict": growth_signal,
        "scores_per_dim": scores,
        "dimension_status": dimension_status,
        "dimension_summaries": dimension_summaries,
        "dimension_scores": dimension_scores,
        "score_summary": score_summary,
        "total_turns": len(qa_history),
        "self_intro": {
            "answer": state.get("self_intro_answer", ""),
            "profile": state.get("self_intro_profile") or {},
        },
        "policy_ids": sorted({qa.get("selected_action", "") for qa in qa_history if qa.get("selected_action")}),
        "cancelled": incoming_status == "cancelled",
        "closed_loop_ready": bool(qa_history) and incoming_status != "cancelled",
        "contract_summary": quality_summary["contract_summary"],
        "coverage_warnings": coverage_warnings,
        "risk_flags": quality_summary["risk_flags"],
        "evidence_summary": quality_summary["evidence_summary"],
        "evaluator_fallback_count": evaluator_fallback_count,
        "workflow_artifacts": _workflow_artifacts(state),
    }
    report["credibility_summary"] = quality_summary["credibility_summary"]
    cost_summary = _build_cost_summary()
    if cost_summary is not None:
        report["cost_summary"] = cost_summary
    video_analysis = _video_analysis_summary(qa_history, state.get("video_signals"))
    if video_analysis is not None:
        report["video_analysis"] = video_analysis
    final_status = "cancelled" if incoming_status == "cancelled" else "completed"
    overall_label = "null" if overall is None else f"{overall:.2f}"
    log.info(
        "final_report verdict=%s overall=%s turns=%d status=%s",
        verdict,
        overall_label,
        len(qa_history),
        final_status,
    )
    trace_view = dict(state)
    trace_view["final_report"] = report
    trace_view["status"] = final_status
    try:
        get_tracer().trace_final_report(trace_view)
    except Exception as e:  # pragma: no cover
        log.warning("tracer.trace_final_report failed: %s", e)
    # Mirror the session-level update into ``generation_traces`` so the
    # admin trace explorer can surface a ``final_report`` row alongside
    # the per-turn nodes. Without this the ``final_report_trace_count``
    # metric in the panel was structurally always 0.
    try:
        get_tracer().trace_node_event(
            trace_view,
            node="final_report",
            payload={
                "verdict": verdict,
                "overall_score": overall,
                "final_status": final_status,
            },
        )
    except Exception as e:  # pragma: no cover
        log.warning("tracer.trace_node_event(final_report) failed: %s", e)
    return {"final_report": report, "status": final_status}
