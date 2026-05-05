"""Synthesize the final interview report.

MVP version: aggregate scores and produce a deterministic report. An
optional LLM summarisation step can be plugged in later without
changing the node signature.
"""
from __future__ import annotations

from typing import Any

from app.core.logging import get_logger
from app.core.metrics import estimate_llm_cost_usd
from app.core.settings import get_settings
from app.core.tracer import get_tracer
from app.engine.workflow.eval_helpers import (
    is_evaluator_fallback as _is_evaluator_fallback,
)
from app.engine.workflow.eval_helpers import (
    is_system_fallback_text as _is_system_fallback_text,
)
from app.engine.workflow.state import InterviewState

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


def _overall_score(scores: dict[str, float]) -> float:
    if not scores:
        return 0.0
    valid = [v for v in scores.values() if v > 0]
    if not valid:
        return 0.0
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
}


def _growth_signal(verdict: str) -> str:
    return _VERDICT_TO_GROWTH_SIGNAL.get(verdict, "unknown")


def _overall_verdict(verdict: str) -> str:
    # Deprecated frontend alias. Keep the field for old clients and
    # persisted-history readers, but project the same candidate-facing
    # growth signal used by new clients.
    return _growth_signal(verdict)


def _coverage_warnings(
    scores_per_dim: dict[str, float],
    dimension_status: dict[str, str],
) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    for dim, status in sorted(dimension_status.items()):
        if status == "passed":
            continue
        warnings.append(
            {
                "dimension": dim,
                "status": status,
                "score": float(scores_per_dim.get(dim, 0.0) or 0.0),
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
    scores_per_dim: dict[str, float],
    dimension_status: dict[str, str],
    dimension_summaries: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Project the rich ``dimension_summaries`` map into the frontend
    ``RubricScore`` contract (``score`` / ``passed`` / ``rationale`` /
    ``weaknesses``).

    Rationale is taken from the latest evidence entry for the dim
    since that captures the evaluator's most recent judgement; the
    earlier turns are already surfaced via ``dimension_summaries``
    for callers that want the full trail.
    """
    out: dict[str, dict[str, Any]] = {}
    dims = (
        set(scores_per_dim.keys())
        | set(dimension_status.keys())
        | set(dimension_summaries.keys())
    )
    for dim in dims:
        summary = dimension_summaries.get(dim) or {}
        evidence = summary.get("evidence") or []
        latest = evidence[-1] if evidence else {}
        out[dim] = {
            "score": float(scores_per_dim.get(dim, 0.0) or 0.0),
            "passed": dimension_status.get(dim) == "passed",
            "rationale": latest.get("rationale") or None,
            "weaknesses": list(summary.get("weaknesses") or []),
        }
    return out


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
    if isinstance(value, dict):
        v = str(value.get("verdict", "")).strip().lower()
    else:
        v = str(value).strip().lower()
    return v if v in {"yes", "partial", "no"} else "no"


def _acceptance_counts(checks: dict[str, Any]) -> dict[str, int]:
    counts = {"yes": 0, "partial": 0, "no": 0, "total": 0}
    for raw in checks.values():
        counts[_verdict_of(raw)] += 1
        counts["total"] += 1
    return counts


def _evidence_summary(qa_history: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate evidence-span match health for the report UI."""
    total = 0
    exact = 0
    fuzzy = 0
    unmatched = 0
    for qa in qa_history:
        evaluation = qa.get("evaluation") or {}
        checks = evaluation.get("acceptance_check_results") or {}
        if not isinstance(checks, dict):
            continue
        for raw in checks.values():
            if not isinstance(raw, dict):
                continue
            spans = raw.get("evidence_spans") or []
            if not isinstance(spans, list):
                continue
            for span in spans:
                if not isinstance(span, dict):
                    continue
                total += 1
                match = str(span.get("match") or "").strip().lower()
                if match == "exact":
                    exact += 1
                elif match == "fuzzy":
                    fuzzy += 1
                else:
                    unmatched += 1
    matched = exact + fuzzy
    return {
        "total_quotes": total,
        "matched_quotes": matched,
        "unmatched_quotes": unmatched,
        "exact_matches": exact,
        "fuzzy_matches": fuzzy,
        "match_rate": round(matched / total, 3) if total else 0.0,
    }


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
    merged = dict(existing)
    for check, raw_value in (incoming or {}).items():
        if not check:
            continue
        merged[str(check)] = _verdict_of(raw_value)
    return merged


def _followup_reason(evaluation: dict[str, Any]) -> str | None:
    if _is_evaluator_fallback(evaluation):
        return None
    if evaluation.get("recommended_next") != "refine":
        return None
    plan = evaluation.get("recommended_next_plan") or "adaptive"
    return f"refine -> {plan}"


def _turn_evidence(qa: dict[str, Any]) -> dict[str, Any]:
    evaluation = qa.get("evaluation") or {}
    return {
        "turn_idx": qa.get("turn_idx"),
        "question": qa.get("question"),
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
    overall = _overall_score(scores)
    verdict = _verdict(overall, threshold)

    qa_history = state.get("qa_history", [])
    dimension_summaries: dict[str, dict[str, Any]] = {}
    merged_contract_checks: dict[str, str] = {}
    risk_flags: list[str] = []
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
        bucket["avg_score"] = scores.get(dim, 0.0)
        candidate_weaknesses = _candidate_weaknesses(evaluation)
        bucket["strengths"].extend(_candidate_strengths(evaluation))
        bucket["weaknesses"].extend(candidate_weaknesses)
        bucket["rubric_coverage"].update(evaluation.get("rubric_coverage") or {})
        checks = evaluation.get("acceptance_check_results") or {}
        bucket["contract_checks"] = _acceptance_counts(checks)
        merged_contract_checks = _merge_contract_checks(merged_contract_checks, checks)
        reason = _followup_reason(evaluation)
        if reason:
            bucket["followup_reasons"].append(reason)
        bucket["evidence"].append(_turn_evidence(qa))

        if not evaluation.get("passed"):
            risk_flags.extend(candidate_weaknesses)
        risk_flags.extend(
            item
            for item in (evaluation.get("soft_warnings") or [])
            if not _is_system_fallback_text(item)
        )

    for bucket in dimension_summaries.values():
        bucket["strengths"] = _dedupe(bucket["strengths"])
        bucket["weaknesses"] = _dedupe(bucket["weaknesses"])
        bucket["followup_reasons"] = _dedupe(bucket["followup_reasons"])

    verification = state.get("verification") or {}
    risk_flags = _dedupe(
        list(verification.get("reasons_to_doubt") or []) + risk_flags
    )[:8]
    contract_counts = _acceptance_counts(merged_contract_checks)

    # Preserve an upstream ``cancelled`` marker so downstream consumers
    # (API, tracer, analytics) can tell a real completion apart from
    # an early teardown; emitting ``verdict: cancelled`` makes the
    # difference observable in the report payload itself.
    incoming_status = state.get("status")
    if incoming_status == "cancelled":
        verdict = "cancelled"

    dimension_status = state.get("dimension_status", {})
    coverage_warnings = _coverage_warnings(scores, dimension_status)
    if incoming_status != "cancelled":
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
        "dimension_scores": _build_dimension_scores(
            scores, dimension_status, dimension_summaries
        ),
        "total_turns": len(qa_history),
        "self_intro": {
            "answer": state.get("self_intro_answer", ""),
            "profile": state.get("self_intro_profile") or {},
        },
        "policy_ids": sorted({qa.get("selected_action", "") for qa in qa_history if qa.get("selected_action")}),
        "cancelled": incoming_status == "cancelled",
        "closed_loop_ready": bool(qa_history) and incoming_status != "cancelled",
        "contract_summary": {
            "total_checks": contract_counts["total"],
            "checks_yes": contract_counts["yes"],
            "checks_partial": contract_counts["partial"],
            "checks_no": contract_counts["no"],
        },
        "coverage_warnings": coverage_warnings,
        "risk_flags": risk_flags,
        "evidence_summary": _evidence_summary(qa_history),
        "evaluator_fallback_count": evaluator_fallback_count,
        "workflow_artifacts": _workflow_artifacts(state),
    }
    cost_summary = _build_cost_summary()
    if cost_summary is not None:
        report["cost_summary"] = cost_summary
    video_sigs = state.get("video_signals")
    if isinstance(video_sigs, dict) and video_sigs:
        report["video_analysis"] = {
            "avg_engagement": video_sigs.get("engagement"),
            "avg_confidence": video_sigs.get("confidence"),
            "dominant_emotion": video_sigs.get("dominant_emotion"),
        }
    final_status = "cancelled" if incoming_status == "cancelled" else "completed"
    log.info(
        "final_report verdict=%s overall=%.2f turns=%d status=%s",
        verdict,
        overall,
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
