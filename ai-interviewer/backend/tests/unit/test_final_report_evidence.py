"""Tests for evidence-span handling in ``final_report``.

``final_report_node`` is the last consumer of
``acceptance_check_results`` before the API response (and the tracer)
sees it, so it's where the evidence-spans upgrade has to be
shape-robust:

- In-memory data that came straight from the upgraded evaluator is
  the canonical dict shape ``{"verdict": ..., "evidence": [...]}``.
- Replayed DB snapshots can still be the legacy flat-string shape.
- A partially-migrated session can even mix both shapes across turns.

What this file pins down:

1. ``_verdict_of`` extracts the verdict from either shape (direct
   unit test — cheap sanity guard that the helper contract stays
   sane even if refactored).
2. ``_acceptance_counts`` sums correctly across mixed shapes, so
   ``contract_summary`` numbers don't skew after the migration.
3. ``_merge_contract_checks`` strips down to verdict strings only
   (the merged blob is a summary, not an evidence archive).
4. ``_turn_evidence`` passes the **full** acceptance dict through
   untouched, so the per-turn evidence survives into the report
   payload that the front-end / audit tools consume.
5. End-to-end ``final_report_node`` emits a consistent report when
   the QA history is purely new-shape, purely legacy, and mixed.
"""
from __future__ import annotations

from typing import Any

from app.engine.workflow.nodes import final_report as fr
from app.engine.workflow.nodes.final_report import (
    _acceptance_counts,
    _build_dimension_scores,
    _merge_contract_checks,
    _overall_verdict,
    _turn_evidence,
    _verdict_of,
)


class _NoopTracer:
    def trace_final_report(self, _state: dict[str, Any]) -> None:
        return None

    def trace_node_event(
        self, _state: dict[str, Any], *, node: str, payload: dict[str, Any] | None = None,
        **_kwargs: Any,
    ) -> None:
        return None


# ---------------------------------------------------------------------------
# _verdict_of — local to final_report, mirrors the agent helper
# ---------------------------------------------------------------------------


def test_verdict_of_legacy_string_shape() -> None:
    assert _verdict_of("yes") == "yes"
    assert _verdict_of("Partial") == "partial"
    assert _verdict_of("NO") == "no"


def test_verdict_of_canonical_dict_shape() -> None:
    assert _verdict_of({"verdict": "yes", "evidence": ["q"]}) == "yes"
    assert _verdict_of({"verdict": "partial", "evidence": []}) == "partial"


def test_verdict_of_unknown_value_falls_back_to_no() -> None:
    assert _verdict_of({"verdict": "maybe"}) == "no"
    assert _verdict_of(None) == "no"
    assert _verdict_of("") == "no"


# ---------------------------------------------------------------------------
# _acceptance_counts — mixed shapes tally correctly
# ---------------------------------------------------------------------------


def test_acceptance_counts_all_new_dict_shape() -> None:
    checks = {
        "c1": {"verdict": "yes", "evidence": ["q1"]},
        "c2": {"verdict": "partial", "evidence": []},
        "c3": {"verdict": "no", "evidence": []},
    }

    counts = _acceptance_counts(checks)

    assert counts == {"yes": 1, "partial": 1, "no": 1, "total": 3}


def test_acceptance_counts_all_legacy_string_shape() -> None:
    checks = {"c1": "yes", "c2": "yes", "c3": "no"}

    counts = _acceptance_counts(checks)

    assert counts == {"yes": 2, "partial": 0, "no": 1, "total": 3}


def test_acceptance_counts_mixed_shape() -> None:
    """A partially-migrated session: some turns have old shape
    (before the commit), others have new shape (after the commit)."""
    checks = {
        "legacy_yes": "yes",
        "canonical_partial": {"verdict": "partial", "evidence": ["q"]},
        "legacy_no": "no",
        "canonical_yes": {"verdict": "yes", "evidence": []},
    }

    counts = _acceptance_counts(checks)

    assert counts == {"yes": 2, "partial": 1, "no": 1, "total": 4}


def test_acceptance_counts_invalid_values_count_as_no() -> None:
    """Defensive: unknown verdicts count as failure, not total-skew,
    so ``contract_summary`` still sums to ``total`` across the
    yes/partial/no buckets.
    """
    checks = {
        "c1": {"verdict": "MAYBE", "evidence": []},
        "c2": "garbage",
        "c3": {},
    }

    counts = _acceptance_counts(checks)

    assert counts == {"yes": 0, "partial": 0, "no": 3, "total": 3}
    # yes + partial + no == total is a load-bearing invariant for the
    # contract_summary.checks_no percentage in the audit panel.
    assert counts["yes"] + counts["partial"] + counts["no"] == counts["total"]


# ---------------------------------------------------------------------------
# _merge_contract_checks — merged blob is verdict-only (summary semantics)
# ---------------------------------------------------------------------------


def test_merge_contract_checks_collapses_dict_shape_to_verdict_string() -> None:
    merged = _merge_contract_checks(
        existing={},
        incoming={
            "c1": {"verdict": "yes", "evidence": ["q1"]},
            "c2": {"verdict": "partial", "evidence": ["q2"]},
        },
    )

    # Evidence intentionally dropped: this dict feeds ``contract_summary``
    # which only counts verdicts. Per-turn evidence is preserved
    # separately under ``dimension_summaries[dim].evidence[*].acceptance_checks``.
    assert merged == {"c1": "yes", "c2": "partial"}


def test_merge_contract_checks_latest_wins_across_shapes() -> None:
    merged = _merge_contract_checks(
        existing={"shared": "partial"},
        incoming={
            "shared": {"verdict": "yes", "evidence": ["later quote"]},
            "new_check": "no",
        },
    )

    # Last-write-wins on ``shared`` turn, legacy strings still
    # normalised to lowercase verdict.
    assert merged == {"shared": "yes", "new_check": "no"}


def test_merge_contract_checks_ignores_empty_keys() -> None:
    merged = _merge_contract_checks(
        existing={},
        incoming={"": "yes", "valid": {"verdict": "no", "evidence": []}},
    )

    assert merged == {"valid": "no"}


# ---------------------------------------------------------------------------
# _turn_evidence — preserves the full acceptance dict verbatim
# ---------------------------------------------------------------------------


def test_turn_evidence_preserves_full_dict_shape() -> None:
    """The per-turn evidence payload must carry the whole
    ``acceptance_check_results`` dict (verdict + evidence) so the
    front-end can quote evidence per check. Summarising here would
    defeat the whole P0-2 upgrade.
    """
    qa = {
        "turn_idx": 3,
        "dimension": "system_design",
        "question": "Explain your caching strategy.",
        "answer": "We cache hot reads in Redis with a 5-min TTL and invalidate on write.",
        "selected_action": "plan_deep_probe",
        "evaluation": {
            "score": 8.5,
            "passed": True,
            "rationale": "covers invalidation",
            "strengths": ["concrete TTL"],
            "weaknesses": [],
            "rubric_coverage": {"caching": "covered"},
            "acceptance_check_results": {
                "Names an invalidation strategy.": {
                    "verdict": "yes",
                    "evidence": ["invalidate on write"],
                },
                "Quantifies cache TTL.": {
                    "verdict": "yes",
                    "evidence": ["5-min TTL"],
                },
            },
            "recommended_next": "advance",
            "recommended_next_plan": "adaptive",
        },
    }

    evidence = _turn_evidence(qa)

    assert evidence["acceptance_checks"] == {
        "Names an invalidation strategy.": {
            "verdict": "yes",
            "evidence": ["invalidate on write"],
        },
        "Quantifies cache TTL.": {
            "verdict": "yes",
            "evidence": ["5-min TTL"],
        },
    }
    assert evidence["score"] == 8.5
    assert evidence["selected_action"] == "plan_deep_probe"


def test_turn_evidence_keeps_full_answer_alongside_excerpt() -> None:
    long_answer = (
        "我先确认读写路径和一致性目标，再把缓存失效、回源保护、容量估算、"
        "监控告警和降级策略串起来说明。"
        * 8
    )
    qa = {
        "turn_idx": 2,
        "dimension": "technical_depth",
        "question": "如何设计一个缓存系统？",
        "answer": long_answer,
        "evaluation": {
            "score": 7.5,
            "passed": True,
            "acceptance_check_results": {},
        },
    }

    evidence = _turn_evidence(qa)

    assert evidence["answer"] == long_answer
    assert evidence["answer_excerpt"] != long_answer
    assert len(evidence["answer_excerpt"]) <= 220
    assert evidence["answer_excerpt"].endswith("...")


def test_turn_evidence_preserves_display_followup_reason() -> None:
    followup_reason = {
        "title": "为什么继续追问",
        "summary": "上一轮回答还需要补足「容量估算」，下一题会继续围绕这个点追问。",
        "chips": ["深挖追问", "量化指标", "容量估算"],
        "source": "evaluator",
    }
    qa = {
        "turn_idx": 4,
        "dimension": "technical_depth",
        "question": "How do you size Redis capacity?",
        "answer": "I would estimate hot keys and value sizes.",
        "evaluation": {
            "score": 6.0,
            "passed": False,
            "recommended_next": "refine",
            "recommended_next_plan": "deep_probe",
            "followup_reason": followup_reason,
            "acceptance_check_results": {},
        },
    }

    evidence = _turn_evidence(qa)

    assert evidence["followup_reason"] == followup_reason


def test_turn_evidence_preserves_display_question_basis() -> None:
    question_basis = {
        "title": "为什么问这一题",
        "summary": "这题结合了简历中的支付迁移项目，并围绕技术深度确认 Redis。",
        "chips": ["来自简历", "评分维度", "技术深度", "Redis"],
    }
    qa = {
        "turn_idx": 5,
        "dimension": "technical_depth",
        "question": "How did you use Redis in the payment migration?",
        "answer": "I used Redis for hot reads.",
        "question_basis": question_basis,
        "evaluation": {
            "score": 8.0,
            "passed": True,
            "acceptance_check_results": {},
        },
    }

    evidence = _turn_evidence(qa)

    assert evidence["question_basis"] == question_basis


def test_turn_evidence_separates_evaluator_fallback_from_candidate_weaknesses() -> None:
    qa = {
        "turn_idx": 1,
        "dimension": "communication",
        "question": "q",
        "answer": "a",
        "evaluation": {
            "source": "fallback",
            "fallback_reason": "llm_failed",
            "score": 6.5,
            "passed": False,
            "rationale": (
                "Evaluator LLM failed before returning a score. The interview "
                "continues with a conservative fallback rather than dropping the session."
            ),
            "weaknesses": [
                "Evaluator LLM unavailable; using conservative fallback.",
                "评估模型暂时不可用，已使用保守兜底评价。",
            ],
            "system_warnings": ["评估模型暂时不可用，已使用保守兜底评价。"],
            "acceptance_check_results": {},
        },
    }

    evidence = _turn_evidence(qa)

    assert evidence["weaknesses"] == []
    assert evidence["system_warnings"] == ["评估模型暂时不可用，已使用保守兜底评价。"]


def test_turn_evidence_preserves_legacy_shape_verbatim() -> None:
    """Replayed old-shape sessions pass through unchanged — the
    front-end has to tolerate both shapes (which is documented
    expectation for P0-2)."""
    qa = {
        "turn_idx": 0,
        "dimension": "leadership",
        "question": "q",
        "answer": "a",
        "evaluation": {
            "acceptance_check_results": {
                "Names a conflict strategy.": "partial",
            }
        },
    }

    evidence = _turn_evidence(qa)

    assert evidence["acceptance_checks"] == {
        "Names a conflict strategy.": "partial",
    }


def test_final_report_filters_evaluator_fallback_from_risk_flags(monkeypatch) -> None:
    monkeypatch.setattr(fr, "get_tracer", lambda: _NoopTracer())

    qa_history = [
        {
            "turn_idx": 0,
            "dimension": "communication",
            "question": "Q0?",
            "answer": "A detailed answer saved while evaluator was unavailable.",
            "evaluation": {
                "source": "fallback",
                "fallback_reason": "llm_failed",
                "score": 6.5,
                "passed": False,
                "strengths": ["本轮回答已保留到面试记录中。"],
                "weaknesses": [
                    "Evaluator LLM unavailable; using conservative fallback.",
                    "评估模型暂时不可用，已使用保守兜底评价。",
                ],
                "system_warnings": ["评估模型暂时不可用，已使用保守兜底评价。"],
                "rubric_coverage": {},
                "acceptance_check_results": {},
                "recommended_next": "refine",
                "recommended_next_plan": "simple",
                "rationale": "评估模型暂时不可用，已先使用保守评价保留本轮回答。",
                "soft_warnings": [],
            },
        }
    ]

    out = fr.final_report_node(_mk_state(qa_history))  # type: ignore[arg-type]
    report = out["final_report"]
    summary = report["dimension_summaries"]["communication"]

    assert summary["weaknesses"] == []
    assert report["dimension_scores"]["communication"]["weaknesses"] == []
    assert report["risk_flags"] == []
    assert summary["evidence"][0]["system_warnings"] == [
        "评估模型暂时不可用，已使用保守兜底评价。"
    ]


# ---------------------------------------------------------------------------
# final_report_node — end-to-end across shapes
# ---------------------------------------------------------------------------


def _mk_qa_turn(
    *,
    turn_idx: int,
    dimension: str,
    passed: bool,
    score: float,
    acceptance: dict[str, Any],
) -> dict[str, Any]:
    return {
        "turn_idx": turn_idx,
        "dimension": dimension,
        "question": f"Q{turn_idx}?",
        "answer": "A detailed production answer with concrete trade-offs.",
        "selected_action": "plan_adaptive",
        "evaluation": {
            "score": score,
            "passed": passed,
            "strengths": [f"strength-{turn_idx}"],
            "weaknesses": [] if passed else [f"weakness-{turn_idx}"],
            "rubric_coverage": {},
            "acceptance_check_results": acceptance,
            "recommended_next": "advance" if passed else "refine",
            "recommended_next_plan": None if passed else "deep_probe",
            "rationale": f"rationale-{turn_idx}",
            "soft_warnings": [],
        },
    }


def _mk_skipped_turn(*, turn_idx: int, dimension: str) -> dict[str, Any]:
    return {
        "turn_idx": turn_idx,
        "dimension": dimension,
        "question": f"Q{turn_idx}?",
        "answer": "",
        "answer_intent": "skipped",
        "evaluation": {
            "score": None,
            "passed": False,
            "strengths": [],
            "weaknesses": ["本题已跳过"],
            "rationale": "候选人选择跳过，本轮不纳入评分。",
            "skipped": True,
        },
    }


def _mk_fallback_turn(*, turn_idx: int, dimension: str) -> dict[str, Any]:
    return {
        "turn_idx": turn_idx,
        "dimension": dimension,
        "question": f"Q{turn_idx}?",
        "answer": "A recorded answer that could not be evaluated.",
        "answer_intent": "normal",
        "evaluation": {
            "source": "fallback",
            "fallback_reason": "llm_failed",
            "score": 6.5,
            "passed": False,
            "strengths": ["本轮回答已保留到面试记录中。"],
            "weaknesses": ["Evaluator LLM unavailable; using conservative fallback."],
            "rationale": "Evaluator LLM unavailable; using conservative fallback.",
            "acceptance_check_results": {},
            "rubric_coverage": {},
        },
    }


def _mk_state(qa_history: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "session_id": "sess-evidence",
        "trace_id": "trace-evidence",
        "candidate": {"name": "Alex"},
        "job_spec": {"title": "Staff Backend Engineer"},
        "quality_threshold": 7.0,
        "scores_per_dim": {"system_design": 7.8},
        "dimension_status": {"system_design": "active"},
        "qa_history": qa_history,
        "current_ask_plan": {"template": "adaptive"},
        "current_contract": {"signed_by": ["generator", "evaluator"]},
        "verification": None,
        "selected_action": {"id": "plan_adaptive"},
    }


def test_final_report_node_new_shape_end_to_end(monkeypatch) -> None:
    monkeypatch.setattr(fr, "get_tracer", lambda: _NoopTracer())

    qa_history = [
        _mk_qa_turn(
            turn_idx=0,
            dimension="system_design",
            passed=True,
            score=8.0,
            acceptance={
                "Names a trade-off.": {
                    "verdict": "yes",
                    "evidence": ["we trade consistency"],
                },
                "Explains a failure mode.": {
                    "verdict": "partial",
                    "evidence": ["mentions partitions"],
                },
            },
        ),
    ]

    out = fr.final_report_node(_mk_state(qa_history))  # type: ignore[arg-type]
    report = out["final_report"]

    # contract_summary was derived via _verdict_of, so new shape
    # must count correctly.
    assert report["contract_summary"]["total_checks"] == 2
    assert report["contract_summary"]["checks_yes"] == 1
    assert report["contract_summary"]["checks_partial"] == 1
    assert report["contract_summary"]["checks_no"] == 0

    dim = report["dimension_summaries"]["system_design"]
    # Per-turn evidence survives into the report payload, full dict shape.
    per_turn = dim["evidence"][0]["acceptance_checks"]
    assert per_turn["Names a trade-off."]["evidence"] == ["we trade consistency"]
    assert per_turn["Explains a failure mode."]["verdict"] == "partial"


def test_final_report_node_aggregates_per_turn_video_signals(monkeypatch) -> None:
    monkeypatch.setattr(fr, "get_tracer", lambda: _NoopTracer())

    qa_history = [
        _mk_qa_turn(
            turn_idx=0,
            dimension="system_design",
            passed=True,
            score=8.0,
            acceptance={"Names a trade-off.": "yes"},
        ),
        _mk_qa_turn(
            turn_idx=1,
            dimension="communication",
            passed=True,
            score=8.2,
            acceptance={"Explains a failure mode.": "yes"},
        ),
    ]
    qa_history[0]["video_signals"] = {
        "confidence": 0.6,
        "engagement": 0.4,
        "dominant_emotion": "neutral",
        "sample_count": 2,
    }
    qa_history[1]["video_signals"] = {
        "confidence": 0.9,
        "engagement": 0.8,
        "dominant_emotion": "positive",
        "sample_count": 6,
    }

    out = fr.final_report_node(_mk_state(qa_history))  # type: ignore[arg-type]
    video = out["final_report"]["video_analysis"]

    assert video["avg_confidence"] == 0.83
    assert video["avg_engagement"] == 0.7
    assert video["dominant_emotion"] == "positive"
    assert video["per_turn_signals"] == [
        {
            "turn_idx": 0,
            "engagement": 0.4,
            "confidence": 0.6,
            "emotion": "neutral",
        },
        {
            "turn_idx": 1,
            "engagement": 0.8,
            "confidence": 0.9,
            "emotion": "positive",
        },
    ]


def test_final_report_node_legacy_shape_end_to_end(monkeypatch) -> None:
    monkeypatch.setattr(fr, "get_tracer", lambda: _NoopTracer())

    qa_history = [
        _mk_qa_turn(
            turn_idx=0,
            dimension="system_design",
            passed=True,
            score=8.0,
            acceptance={"Names a trade-off.": "yes", "Explains a failure mode.": "no"},
        ),
    ]

    out = fr.final_report_node(_mk_state(qa_history))  # type: ignore[arg-type]
    report = out["final_report"]

    assert report["contract_summary"]["total_checks"] == 2
    assert report["contract_summary"]["checks_yes"] == 1
    assert report["contract_summary"]["checks_no"] == 1

    dim = report["dimension_summaries"]["system_design"]
    # Legacy shape preserved verbatim; front-end is responsible for the
    # shape branch.
    assert dim["evidence"][0]["acceptance_checks"] == {
        "Names a trade-off.": "yes",
        "Explains a failure mode.": "no",
    }


def test_final_report_node_mixed_shape_across_turns(monkeypatch) -> None:
    """Worst-case migration: one old turn (from a previous session
    replayed through checkpoint resume) and one new turn in the same
    history. Contract summary must still add up cleanly.
    """
    monkeypatch.setattr(fr, "get_tracer", lambda: _NoopTracer())

    qa_history = [
        # Turn 0: new shape.
        _mk_qa_turn(
            turn_idx=0,
            dimension="system_design",
            passed=True,
            score=7.8,
            acceptance={
                "New shape check.": {"verdict": "yes", "evidence": ["q"]},
            },
        ),
        # Turn 1: legacy shape.
        _mk_qa_turn(
            turn_idx=1,
            dimension="system_design",
            passed=False,
            score=6.0,
            acceptance={"Legacy shape check.": "partial"},
        ),
    ]

    out = fr.final_report_node(_mk_state(qa_history))  # type: ignore[arg-type]
    report = out["final_report"]

    # Merged contract summary counts each distinct check by latest
    # verdict; there are 2 distinct checks.
    assert report["contract_summary"]["total_checks"] == 2
    assert report["contract_summary"]["checks_yes"] == 1
    assert report["contract_summary"]["checks_partial"] == 1

    dim = report["dimension_summaries"]["system_design"]
    # Each turn's evidence preserved in its native shape.
    turn0 = dim["evidence"][0]["acceptance_checks"]
    turn1 = dim["evidence"][1]["acceptance_checks"]
    assert turn0["New shape check."]["evidence"] == ["q"]
    assert turn1["Legacy shape check."] == "partial"


def test_final_report_node_summarises_evidence_span_match_rate(monkeypatch) -> None:
    monkeypatch.setattr(fr, "get_tracer", lambda: _NoopTracer())

    qa_history = [
        _mk_qa_turn(
            turn_idx=0,
            dimension="system_design",
            passed=True,
            score=8.0,
            acceptance={
                "Names a trade-off.": {
                    "verdict": "yes",
                    "evidence": ["we trade consistency", "availability"],
                    "evidence_spans": [
                        {
                            "text": "we trade consistency",
                            "start": 0,
                            "end": 20,
                            "match": "exact",
                        },
                        {
                            "text": "availability",
                            "start": 42,
                            "end": 54,
                            "match": "fuzzy",
                        },
                    ],
                },
                "Explains a failure mode.": {
                    "verdict": "partial",
                    "evidence": ["not actually present"],
                    "evidence_spans": [
                        {
                            "text": "not actually present",
                            "start": -1,
                            "end": -1,
                            "match": "none",
                        }
                    ],
                },
            },
        ),
    ]

    out = fr.final_report_node(_mk_state(qa_history))  # type: ignore[arg-type]
    summary = out["final_report"]["evidence_summary"]

    assert summary == {
        "total_quotes": 3,
        "matched_quotes": 2,
        "unmatched_quotes": 1,
        "exact_matches": 1,
        "fuzzy_matches": 1,
        "match_rate": 0.667,
    }


def test_final_report_node_emits_empty_evidence_summary_without_spans(
    monkeypatch,
) -> None:
    monkeypatch.setattr(fr, "get_tracer", lambda: _NoopTracer())

    qa_history = [
        _mk_qa_turn(
            turn_idx=0,
            dimension="system_design",
            passed=True,
            score=8.0,
            acceptance={
                "Legacy check.": {"verdict": "yes", "evidence": ["quote only"]},
                "Old shape check.": "partial",
            },
        ),
    ]

    out = fr.final_report_node(_mk_state(qa_history))  # type: ignore[arg-type]

    assert out["final_report"]["evidence_summary"] == {
        "total_quotes": 0,
        "matched_quotes": 0,
        "unmatched_quotes": 0,
        "exact_matches": 0,
        "fuzzy_matches": 0,
        "match_rate": 0.0,
    }


# ---------------------------------------------------------------------------
# Frontend-facing projection: growth_signal + overall_verdict + dimension_scores
# ---------------------------------------------------------------------------


def test_growth_signal_maps_internal_vocabulary_to_candidate_language() -> None:
    assert fr._growth_signal("strong_pass") == "excellent"
    assert fr._growth_signal("pass") == "target_met"
    assert fr._growth_signal("borderline") == "near_target"
    assert fr._growth_signal("fail") == "needs_focus"
    assert fr._growth_signal("cancelled") == "cancelled"
    assert fr._growth_signal("something_new") == "unknown"


def test_overall_verdict_is_deprecated_candidate_signal_alias() -> None:
    assert _overall_verdict("strong_pass") == "excellent"
    assert _overall_verdict("pass") == "target_met"
    assert _overall_verdict("borderline") == "near_target"
    assert _overall_verdict("fail") == "needs_focus"
    assert _overall_verdict("cancelled") == "cancelled"
    assert _overall_verdict("something_new") == "unknown"


def test_build_dimension_scores_projects_rubric_score_shape() -> None:
    """``dimension_scores`` must match the TypeScript ``RubricScore``
    contract the Next.js report reads: score state + ``passed`` +
    ``rationale`` + ``weaknesses``. The richer
    ``dimension_summaries`` stays untouched for power users /
    analytics.
    """
    scores_per_dim = {"system_design": 7.8, "leadership": 0.0}
    dimension_status = {"system_design": "passed", "leadership": "pending"}
    dimension_summaries = {
        "system_design": {
            "weaknesses": ["needs_concrete_example"],
            "evidence": [
                {"rationale": "old", "score": 7.0},
                {"rationale": "latest wins", "score": 7.8},
            ],
        },
        # leadership intentionally missing summary: the helper still
        # needs to emit an unscored slot so the UI can avoid showing
        # a fake "0 / 10".
    }

    out = _build_dimension_scores(
        scores_per_dim, dimension_status, dimension_summaries
    )

    assert out["system_design"] == {
        "score": 7.8,
        "score_status": "scored",
        "excluded_from_overall": False,
        "exclusion_reason": None,
        "coverage_status": "passed",
        "passed": True,
        "rationale": "latest wins",
        "weaknesses": ["needs_concrete_example"],
    }
    assert out["leadership"] == {
        "score": None,
        "score_status": "not_evaluated",
        "excluded_from_overall": True,
        "exclusion_reason": "not_evaluated",
        "coverage_status": "not_applicable",
        "passed": False,
        "rationale": None,
        "weaknesses": [],
    }


def test_final_report_node_emits_frontend_projection(monkeypatch) -> None:
    """End-to-end guarantee: the report payload carries both the
    candidate-facing ``growth_signal`` and the ``dimension_scores``
    shape the Next.js frontend consumes — while the internal
    ``verdict`` and ``dimension_summaries`` stay available for the
    tracer + analytics pipeline.
    """
    monkeypatch.setattr(fr, "get_tracer", lambda: _NoopTracer())

    qa_history = [
        _mk_qa_turn(
            turn_idx=0,
            dimension="system_design",
            passed=True,
            score=8.0,
            acceptance={"Names a trade-off.": "yes"},
        ),
    ]

    state = _mk_state(qa_history)
    state["scores_per_dim"] = {"system_design": 8.0}
    state["dimension_status"] = {"system_design": "passed"}

    out = fr.final_report_node(state)  # type: ignore[arg-type]
    report = out["final_report"]

    # Internal vocab kept for backward compatibility with the tracer
    # / RL reward bridge / persisted traces.
    assert report["verdict"] in {"strong_pass", "pass"}
    assert "dimension_summaries" in report

    # Frontend-facing aliases.
    assert report["growth_signal"] in {"excellent", "target_met"}
    assert report["overall_verdict"] == report["growth_signal"]
    assert report["dimension_scores"]["system_design"]["score"] == 8.0
    assert report["dimension_scores"]["system_design"]["passed"] is True
    assert report["dimension_scores"]["system_design"]["coverage_status"] == "passed"
    assert report["dimension_scores"]["system_design"]["rationale"] == "rationale-0"


def test_final_report_node_cancelled_verdict_passes_through(monkeypatch) -> None:
    """A cancelled session should still emit ``overall_verdict`` so
    the UI does not crash on ``undefined``; the value falls through
    unchanged because the frontend colours it as an outline badge.
    """
    monkeypatch.setattr(fr, "get_tracer", lambda: _NoopTracer())

    state = _mk_state([])
    state["status"] = "cancelled"

    out = fr.final_report_node(state)  # type: ignore[arg-type]
    report = out["final_report"]

    assert report["verdict"] == "cancelled"
    assert report["growth_signal"] == "cancelled"
    assert report["overall_verdict"] == "cancelled"
    assert report["cancelled"] is True


def test_final_report_caps_positive_verdict_when_dimension_uncovered(monkeypatch) -> None:
    monkeypatch.setattr(fr, "get_tracer", lambda: _NoopTracer())

    qa_history = [
        _mk_qa_turn(
            turn_idx=0,
            dimension="system_design",
            passed=True,
            score=8.8,
            acceptance={"Names a trade-off.": "yes"},
        ),
    ]
    state = _mk_state(qa_history)
    state["quality_threshold"] = 7.0
    state["scores_per_dim"] = {
        "system_design": 8.8,
        "communication": 0.0,
    }
    state["dimension_status"] = {
        "system_design": "passed",
        "communication": "pending",
    }

    out = fr.final_report_node(state)  # type: ignore[arg-type]
    report = out["final_report"]

    assert report["overall_score"] == 8.8
    assert report["verdict"] == "borderline"
    assert report["growth_signal"] == "near_target"
    assert report["overall_verdict"] == "near_target"
    assert report["coverage_warnings"] == [
            {
                "dimension": "communication",
                "status": "pending",
                "score": None,
            }
        ]


def test_final_report_counts_real_zero_scores_in_overall(monkeypatch) -> None:
    monkeypatch.setattr(fr, "get_tracer", lambda: _NoopTracer())

    qa_history = [
        _mk_qa_turn(
            turn_idx=0,
            dimension="coding_quality",
            passed=False,
            score=0.0,
            acceptance={"Writes correct code.": "no"},
        ),
        _mk_qa_turn(
            turn_idx=1,
            dimension="system_design",
            passed=True,
            score=10.0,
            acceptance={"Names a trade-off.": "yes"},
        ),
    ]
    state = _mk_state(qa_history)
    state["scores_per_dim"] = {"coding_quality": 0.0, "system_design": 10.0}
    state["dimension_status"] = {"coding_quality": "active", "system_design": "passed"}

    out = fr.final_report_node(state)  # type: ignore[arg-type]
    report = out["final_report"]

    assert report["overall_score"] == 5.0
    assert report["score_summary"] == {
        "scored_dimension_count": 2,
        "excluded_dimension_count": 0,
        "total_dimension_count": 2,
    }
    assert report["dimension_scores"]["coding_quality"]["score"] == 0.0
    assert report["dimension_scores"]["coding_quality"]["score_status"] == "scored"
    assert report["dimension_scores"]["coding_quality"]["excluded_from_overall"] is False
    assert report["dimension_scores"]["coding_quality"]["exclusion_reason"] is None
    assert report["dimension_scores"]["coding_quality"]["coverage_status"] == "below_threshold"


def test_final_report_marks_unscored_skipped_and_fallback_dimensions(monkeypatch) -> None:
    monkeypatch.setattr(fr, "get_tracer", lambda: _NoopTracer())

    qa_history = [
        _mk_qa_turn(
            turn_idx=0,
            dimension="system_design",
            passed=True,
            score=9.0,
            acceptance={"Names a trade-off.": "yes"},
        ),
        _mk_skipped_turn(turn_idx=1, dimension="project_experience"),
        _mk_fallback_turn(turn_idx=2, dimension="communication"),
    ]
    state = _mk_state(qa_history)
    state["scores_per_dim"] = {
        "system_design": 9.0,
        "project_experience": None,
        "communication": None,
        "problem_solving": None,
    }
    state["dimension_status"] = {
        "system_design": "passed",
        "project_experience": "pending",
        "communication": "pending",
        "problem_solving": "pending",
    }

    out = fr.final_report_node(state)  # type: ignore[arg-type]
    report = out["final_report"]

    assert report["overall_score"] == 9.0
    assert report["score_summary"] == {
        "scored_dimension_count": 1,
        "excluded_dimension_count": 3,
        "total_dimension_count": 4,
    }
    assert report["dimension_scores"]["project_experience"]["score"] is None
    assert report["dimension_scores"]["project_experience"]["score_status"] == "skipped"
    assert report["dimension_scores"]["project_experience"]["exclusion_reason"] == "skipped"
    assert report["dimension_scores"]["communication"]["score"] is None
    assert report["dimension_scores"]["communication"]["score_status"] == "evaluator_unavailable"
    assert report["dimension_scores"]["communication"]["exclusion_reason"] == "evaluator_unavailable"
    assert report["dimension_scores"]["problem_solving"]["score"] is None
    assert report["dimension_scores"]["problem_solving"]["score_status"] == "not_evaluated"
    assert report["dimension_scores"]["problem_solving"]["exclusion_reason"] == "not_evaluated"


def test_final_report_keeps_coverage_limited_scores_in_overall(monkeypatch) -> None:
    monkeypatch.setattr(fr, "get_tracer", lambda: _NoopTracer())

    qa_history = [
        _mk_qa_turn(
            turn_idx=0,
            dimension="technical_depth",
            passed=False,
            score=9.0,
            acceptance={"Explains consistency trade-off.": "partial"},
        ),
    ]
    state = _mk_state(qa_history)
    state["scores_per_dim"] = {"technical_depth": 9.0}
    state["dimension_status"] = {"technical_depth": "active"}
    state["quality_threshold"] = 7.0

    out = fr.final_report_node(state)  # type: ignore[arg-type]
    report = out["final_report"]

    assert report["overall_score"] == 9.0
    assert report["dimension_scores"]["technical_depth"]["score_status"] == "scored"
    assert report["dimension_scores"]["technical_depth"]["excluded_from_overall"] is False
    assert report["dimension_scores"]["technical_depth"]["coverage_status"] == "coverage_limited"


def test_final_report_rebuilds_multiturn_score_breakdown_from_qa_history(
    monkeypatch,
) -> None:
    monkeypatch.setattr(fr, "get_tracer", lambda: _NoopTracer())

    qa_history = [
        _mk_qa_turn(
            turn_idx=i,
            dimension="technical_depth",
            passed=i < 4,
            score=score,
            acceptance={"Explains root cause.": "yes" if i < 4 else "partial"},
        )
        for i, score in enumerate([9.0, 9.0, 9.0, 9.0, 8.0])
    ]
    state = _mk_state(qa_history)
    state["scores_per_dim"] = {"technical_depth": None}
    state["dimension_status"] = {"technical_depth": "active"}
    state["quality_threshold"] = 7.0

    out = fr.final_report_node(state)  # type: ignore[arg-type]
    report = out["final_report"]

    assert report["overall_score"] == 8.7
    assert report["dimension_scores"]["technical_depth"]["score"] == 8.7
    assert report["dimension_scores"]["technical_depth"]["score_breakdown"] == {
        "scored_turn_count": 5,
        "latest_score": 8.0,
        "best_score": 9.0,
        "average_score": 8.8,
        "adopted_score": 8.7,
        "scoring_policy": "weighted_recent",
    }


def test_final_report_null_overall_when_no_valid_scores(monkeypatch) -> None:
    monkeypatch.setattr(fr, "get_tracer", lambda: _NoopTracer())

    state = _mk_state([])
    state["scores_per_dim"] = {"technical_depth": None, "communication": None}
    state["dimension_status"] = {"technical_depth": "pending", "communication": "pending"}

    out = fr.final_report_node(state)  # type: ignore[arg-type]
    report = out["final_report"]

    assert report["overall_score"] is None
    assert report["verdict"] == "unknown"
    assert report["growth_signal"] == "unknown"
    assert report["score_summary"] == {
        "scored_dimension_count": 0,
        "excluded_dimension_count": 2,
        "total_dimension_count": 2,
    }
