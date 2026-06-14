"""Shadow contract-score calculation from structured evaluator verdicts."""
from __future__ import annotations

from typing import Any


_MAX_SCORE = 10.0
SCORE_MODE = "llm"
SCORE_MODES = {"llm", "shadow_contract", "hybrid", "contract"}
INVALID_SCORE_MODE_FALLBACK_WARNING = "invalid_evaluator_score_mode_fallback"
CONTRACT_SCORE_UNAVAILABLE_FALLBACK_WARNING = (
    "contract_score_unavailable_fallback_llm"
)
LLM_SCORE_UNAVAILABLE_FALLBACK_WARNING = "llm_score_unavailable_fallback_contract"
_HYBRID_CONTRACT_WEIGHT = 0.70
_HYBRID_LLM_WEIGHT = 0.30
_VERDICT_VALUE = {
    "yes": 1.0,
    "partial": 0.5,
    "no": 0.0,
}
_WEIGHTS = {
    "core": 0.60,
    "supporting": 0.20,
    "adaptive_context": 0.10,
    "evidence_quality": 0.10,
}


def resolve_evaluator_score_mode(
    *,
    runtime_config: dict[str, Any] | None,
    settings: Any,
) -> tuple[str, list[str]]:
    """Resolve score takeover mode, preferring runtime config over settings."""

    raw = None
    if isinstance(runtime_config, dict):
        raw = runtime_config.get("evaluator_score_mode")
    if raw is None:
        raw = getattr(settings, "evaluator_score_mode", SCORE_MODE)

    mode = _normalize_score_mode(raw)
    if mode in SCORE_MODES:
        return mode, []
    return SCORE_MODE, [INVALID_SCORE_MODE_FALLBACK_WARNING]


def build_contract_score_shadow(
    evaluation: dict[str, Any] | None,
    *,
    evaluator_score_mode: str = SCORE_MODE,
    score_mode_warnings: list[str] | None = None,
) -> dict[str, Any]:
    """Return deterministic contract score fields and optional score takeover.

    The current workflow still treats ``evaluation["score"]`` as the
    authoritative score by default.  Non-default modes let operators
    explicitly gray-rollout deterministic contract scoring without
    changing pass/routing semantics in the same step.
    """

    payload = dict(evaluation or {})
    llm_score = _score_or_none(payload.get("llm_score"))
    if llm_score is None:
        llm_score = _score_or_none(payload.get("score"))
    items = _dict_items(payload.get("acceptance_check_result_items"))
    breakdown = _build_breakdown(
        items,
        rubric_coverage=payload.get("rubric_coverage"),
    )
    contract_score = _score_from_breakdown(breakdown)
    requested_mode = _normalize_score_mode(evaluator_score_mode)
    mode_warnings = list(score_mode_warnings or [])
    if requested_mode not in SCORE_MODES:
        requested_mode = SCORE_MODE
        mode_warnings = _append_unique(
            mode_warnings,
            INVALID_SCORE_MODE_FALLBACK_WARNING,
        )
    mode_fields = _score_mode_fields(
        llm_score=llm_score,
        contract_score=contract_score,
        evaluator_score_mode=requested_mode,
        warnings=mode_warnings,
    )

    result = {
        "llm_score": llm_score,
        "contract_score": contract_score,
        "contract_score_mode": "shadow" if contract_score is not None else "unavailable",
        "contract_score_breakdown": breakdown,
    }
    result.update(mode_fields)
    return result


def build_contract_pass_shadow(
    evaluation: dict[str, Any] | None,
    *,
    quality_threshold: float,
) -> dict[str, Any]:
    """Project what pass/routing signals would be under contract score.

    This is intentionally observation-only.  It does not mutate the
    authoritative ``passed`` / ``recommended_next`` fields; callers add
    these shadow fields to traces and reports to measure rollout risk.
    """

    payload = dict(evaluation or {})
    contract_score = _score_or_none(payload.get("contract_score"))
    legacy_passed = bool(payload.get("passed"))
    legacy_next = str(payload.get("recommended_next") or "").strip() or None
    legacy_plan = payload.get("recommended_next_plan")
    try:
        threshold = float(quality_threshold)
    except (TypeError, ValueError):
        threshold = 7.5

    if contract_score is None:
        shadow = {
            "available": False,
            "reason": "contract_score_unavailable",
            "quality_threshold": threshold,
            "legacy_passed": legacy_passed,
            "legacy_recommended_next": legacy_next,
            "legacy_recommended_next_plan": legacy_plan,
        }
        return {
            "contract_pass_shadow": shadow,
            "contract_passed_shadow": None,
            "contract_recommended_next_shadow": None,
            "contract_recommended_next_plan_shadow": None,
            "contract_pass_shadow_reason": "contract_score_unavailable",
            "contract_pass_shadow_diff": False,
            "contract_routing_signal_shadow_diff": False,
        }

    gate_failed, gate_meta = _contract_gate_failure(payload)
    shadow_passed = False if gate_failed else contract_score >= threshold
    shadow_next = "advance" if shadow_passed else "refine"
    shadow_plan = None if shadow_passed else _shadow_refine_plan(payload)
    if gate_failed:
        reason = "contract_gate_failed"
    else:
        reason = (
            "contract_score_meets_threshold"
            if shadow_passed
            else "contract_score_below_threshold"
        )
    pass_diff = legacy_passed != shadow_passed
    routing_diff = (
        pass_diff
        or legacy_next != shadow_next
        or _normalize_plan(legacy_plan) != _normalize_plan(shadow_plan)
    )
    shadow = {
        "available": True,
        "score": contract_score,
        "score_source": "contract_score",
        "quality_threshold": threshold,
        "passed": shadow_passed,
        "recommended_next": shadow_next,
        "recommended_next_plan": shadow_plan,
        "reason": reason,
        "legacy_passed": legacy_passed,
        "legacy_recommended_next": legacy_next,
        "legacy_recommended_next_plan": legacy_plan,
        "pass_diff": pass_diff,
        "routing_signal_diff": routing_diff,
    }
    shadow.update(gate_meta)
    return {
        "contract_pass_shadow": shadow,
        "contract_passed_shadow": shadow_passed,
        "contract_recommended_next_shadow": shadow_next,
        "contract_recommended_next_plan_shadow": shadow_plan,
        "contract_pass_shadow_reason": reason,
        "contract_pass_shadow_diff": pass_diff,
        "contract_routing_signal_shadow_diff": routing_diff,
    }


def _score_mode_fields(
    *,
    llm_score: float | None,
    contract_score: float | None,
    evaluator_score_mode: str,
    warnings: list[str],
) -> dict[str, Any]:
    mode = evaluator_score_mode
    score_source = "llm"
    final_score = llm_score
    score_formula = "llm_score"
    out_warnings = list(warnings)

    if mode == "contract":
        if contract_score is None:
            mode = SCORE_MODE
            out_warnings = _append_unique(
                out_warnings,
                CONTRACT_SCORE_UNAVAILABLE_FALLBACK_WARNING,
            )
        else:
            final_score = contract_score
            score_source = "contract"
            score_formula = "contract_score"
    elif mode == "hybrid":
        if contract_score is None:
            mode = SCORE_MODE
            out_warnings = _append_unique(
                out_warnings,
                CONTRACT_SCORE_UNAVAILABLE_FALLBACK_WARNING,
            )
        elif llm_score is None:
            mode = "contract"
            final_score = contract_score
            score_source = "contract"
            score_formula = "contract_score"
            out_warnings = _append_unique(
                out_warnings,
                LLM_SCORE_UNAVAILABLE_FALLBACK_WARNING,
            )
        else:
            final_score = round(
                contract_score * _HYBRID_CONTRACT_WEIGHT
                + llm_score * _HYBRID_LLM_WEIGHT,
                2,
            )
            score_source = "hybrid"
            score_formula = "0.7*contract_score+0.3*llm_score"
    elif mode == "shadow_contract":
        score_formula = "llm_score"

    result: dict[str, Any] = {
        "final_score": final_score,
        "score_source": score_source,
        "evaluator_score_mode": mode,
        "requested_evaluator_score_mode": evaluator_score_mode,
        "score_formula": score_formula,
        "score_mode_warnings": out_warnings,
    }
    if final_score is not None:
        result["score"] = final_score
    return result


def _build_breakdown(
    items: list[dict[str, Any]],
    *,
    rubric_coverage: Any = None,
) -> dict[str, Any]:
    reviewed = [item for item in items if _source(item) == "reviewed"]
    fallback = [item for item in items if _source(item) == "compiled_fallback"]
    use_reviewed = bool(reviewed)
    has_structured_core = any(
        _severity(item) == "core" for item in [*reviewed, *fallback]
    )
    rubric_core = _rubric_coverage_bucket(
        rubric_coverage,
        configured_weight=_WEIGHTS["core"],
        enabled=not has_structured_core,
    )
    structured_source = (
        "reviewed"
        if use_reviewed
        else "compiled_fallback"
        if fallback
        else "rubric_coverage"
        if rubric_core["available"]
        else "none"
    )
    structured_items = reviewed if use_reviewed else fallback

    reviewed_core = _bucket(
        [item for item in reviewed if _severity(item) == "core"],
        configured_weight=_WEIGHTS["core"],
    )
    reviewed_supporting = _bucket(
        [item for item in reviewed if _severity(item) == "supporting"],
        configured_weight=_WEIGHTS["supporting"],
    )
    fallback_core = _bucket(
        [item for item in fallback if _severity(item) == "core"],
        configured_weight=_WEIGHTS["core"],
    )
    fallback_supporting = _bucket(
        [item for item in fallback if _severity(item) == "supporting"],
        configured_weight=_WEIGHTS["supporting"],
    )
    adaptive = _bucket(
        [item for item in items if _source(item) == "adaptive_context"],
        configured_weight=_WEIGHTS["adaptive_context"],
    )

    active_structured_core = (
        reviewed_core
        if reviewed_core["available"]
        else fallback_core
        if fallback_core["available"]
        else rubric_core
    )
    active_structured_supporting = (
        reviewed_supporting if use_reviewed else fallback_supporting
    )
    scoring_items = [
        *[item for item in structured_items if _severity(item) in {"core", "supporting"}],
        *[item for item in items if _source(item) == "adaptive_context"],
    ]
    evidence_quality = _evidence_quality_bucket(scoring_items)

    active_buckets = {
        "structured_core": active_structured_core,
        "structured_supporting": active_structured_supporting,
        "adaptive_context": adaptive,
        "evidence_quality": evidence_quality,
    }
    active_weight_total = sum(
        float(bucket["configured_weight"])
        for bucket in active_buckets.values()
        if bucket["available"]
    )
    _attach_effective_weights(active_buckets, active_weight_total)

    return {
        "available": (bool(items) or rubric_core["available"])
        and active_weight_total > 0,
        "structured_source": structured_source,
        "item_count": len(items),
        "active_weight_total": round(active_weight_total, 4),
        "reviewed_core": reviewed_core,
        "reviewed_supporting": reviewed_supporting,
        "fallback_core": fallback_core,
        "fallback_supporting": fallback_supporting,
        "rubric_core": rubric_core,
        "adaptive_context": adaptive,
        "evidence_quality": evidence_quality,
        "active_buckets": active_buckets,
    }


def _score_from_breakdown(breakdown: dict[str, Any]) -> float | None:
    if not breakdown.get("available"):
        return None
    active_buckets = breakdown.get("active_buckets")
    if not isinstance(active_buckets, dict):
        return None
    total = 0.0
    for bucket in active_buckets.values():
        if not isinstance(bucket, dict) or not bucket.get("available"):
            continue
        total += float(bucket.get("raw_score") or 0.0) * float(
            bucket.get("effective_weight") or 0.0
        )
    return round(max(0.0, min(_MAX_SCORE, total * _MAX_SCORE)), 2)


def _bucket(
    items: list[dict[str, Any]],
    *,
    configured_weight: float,
) -> dict[str, Any]:
    if not items:
        return {
            "available": False,
            "count": 0,
            "configured_weight": configured_weight,
            "effective_weight": 0.0,
            "raw_score": None,
            "yes": 0,
            "partial": 0,
            "no": 0,
            "missing": 0,
        }

    scores = [_item_score(item) for item in items]
    verdict_counts = _verdict_counts(items)
    return {
        "available": True,
        "count": len(items),
        "configured_weight": configured_weight,
        "effective_weight": 0.0,
        "raw_score": round(sum(scores) / len(scores), 4),
        **verdict_counts,
    }


def _rubric_coverage_bucket(
    value: Any,
    *,
    configured_weight: float,
    enabled: bool,
) -> dict[str, Any]:
    if not enabled or not isinstance(value, dict):
        return {
            "available": False,
            "count": 0,
            "configured_weight": configured_weight,
            "effective_weight": 0.0,
            "raw_score": None,
            "covered": 0,
            "partial": 0,
            "missing": 0,
        }

    statuses: list[str] = []
    for status in value.values():
        normalized = _coverage_status(status)
        if normalized in {"covered", "partial", "missing"}:
            statuses.append(normalized)
    if not statuses:
        return {
            "available": False,
            "count": 0,
            "configured_weight": configured_weight,
            "effective_weight": 0.0,
            "raw_score": None,
            "covered": 0,
            "partial": 0,
            "missing": 0,
        }

    scores = [
        1.0 if status == "covered" else 0.5 if status == "partial" else 0.0
        for status in statuses
    ]
    return {
        "available": True,
        "count": len(statuses),
        "configured_weight": configured_weight,
        "effective_weight": 0.0,
        "raw_score": round(sum(scores) / len(scores), 4),
        "covered": statuses.count("covered"),
        "partial": statuses.count("partial"),
        "missing": statuses.count("missing"),
    }


def _evidence_quality_bucket(items: list[dict[str, Any]]) -> dict[str, Any]:
    candidates = [
        item
        for item in items
        if _verdict(item) in {"yes", "partial"} and bool(item.get("result_present"))
    ]
    if not candidates:
        return {
            "available": False,
            "count": 0,
            "configured_weight": _WEIGHTS["evidence_quality"],
            "effective_weight": 0.0,
            "raw_score": None,
            "with_evidence": 0,
            "missing_evidence": 0,
        }
    with_evidence = sum(1 for item in candidates if _has_evidence(item))
    missing = len(candidates) - with_evidence
    return {
        "available": True,
        "count": len(candidates),
        "configured_weight": _WEIGHTS["evidence_quality"],
        "effective_weight": 0.0,
        "raw_score": round(with_evidence / len(candidates), 4),
        "with_evidence": with_evidence,
        "missing_evidence": missing,
    }


def _attach_effective_weights(
    buckets: dict[str, dict[str, Any]],
    active_weight_total: float,
) -> None:
    if active_weight_total <= 0:
        return
    for bucket in buckets.values():
        if not bucket.get("available"):
            continue
        bucket["effective_weight"] = round(
            float(bucket.get("configured_weight") or 0.0) / active_weight_total,
            4,
        )


def _item_score(item: dict[str, Any]) -> float:
    if not bool(item.get("result_present")):
        return 0.0
    return _VERDICT_VALUE.get(_verdict(item), 0.0)


def _verdict_counts(items: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"yes": 0, "partial": 0, "no": 0, "missing": 0}
    for item in items:
        if not bool(item.get("result_present")):
            counts["missing"] += 1
            continue
        verdict = _verdict(item)
        if verdict in {"yes", "partial", "no"}:
            counts[verdict] += 1
        else:
            counts["missing"] += 1
    return counts


def _dict_items(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _source(item: dict[str, Any]) -> str:
    return str(item.get("source") or "").strip().lower()


def _severity(item: dict[str, Any]) -> str:
    value = str(item.get("severity") or "").strip().lower()
    return value if value in {"core", "supporting"} else "supporting"


def _verdict(item: dict[str, Any]) -> str:
    verdict = str(item.get("verdict") or "").strip().lower()
    return verdict if verdict in {"yes", "partial", "no"} else ""


def _coverage_status(value: Any) -> str:
    status = str(value or "").strip().lower()
    return status if status in {"covered", "partial", "missing"} else ""


def _has_evidence(item: dict[str, Any]) -> bool:
    evidence = item.get("evidence")
    if isinstance(evidence, list):
        return any(str(value or "").strip() for value in evidence)
    if isinstance(evidence, str):
        return bool(evidence.strip())
    evidence_spans = item.get("evidence_spans")
    if isinstance(evidence_spans, list):
        return bool(evidence_spans)
    return False


def _score_or_none(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        score = float(value)
    except (TypeError, ValueError):
        return None
    if score != score:
        return None
    return round(score, 2)


def _normalize_score_mode(value: Any) -> str:
    return str(value or SCORE_MODE).strip().lower()


def _append_unique(values: list[str], value: str) -> list[str]:
    out = list(values)
    if value not in out:
        out.append(value)
    return out


def _shadow_refine_plan(evaluation: dict[str, Any]) -> str:
    plan = _normalize_plan(evaluation.get("recommended_next_plan"))
    if plan:
        return plan
    return "deep_probe"


def _normalize_plan(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _contract_gate_failure(evaluation: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    gate = evaluation.get("contract_gate_result")
    gate_status = None
    gate_mode = None
    failed_check_ids: list[str] = []
    failed_count = 0

    if isinstance(gate, dict):
        gate_status = str(gate.get("status") or "").strip().lower() or None
        gate_mode = str(gate.get("mode") or "").strip().lower() or None
        failed_count = _int_or_zero(gate.get("failed_count"))
        failed_items = _dict_items(gate.get("failed_items"))
        failed_check_ids.extend(
            str(item.get("check_id") or "").strip()
            for item in failed_items
            if str(item.get("check_id") or "").strip()
        )

    explicit_failed_ids = evaluation.get("contract_gate_failed_check_ids")
    if isinstance(explicit_failed_ids, list):
        failed_check_ids.extend(
            str(value or "").strip()
            for value in explicit_failed_ids
            if str(value or "").strip()
        )

    failed_check_ids = list(dict.fromkeys(failed_check_ids))
    gate_failed = (
        bool(evaluation.get("contract_gate_enforced"))
        or gate_status == "failed"
        or failed_count > 0
        or bool(failed_check_ids)
    )
    meta: dict[str, Any] = {
        "gate_failed": gate_failed,
        "gate_status": gate_status,
        "gate_mode": gate_mode,
        "gate_failed_check_ids": failed_check_ids,
    }
    if failed_count > 0:
        meta["gate_failed_count"] = failed_count
    return gate_failed, meta


def _int_or_zero(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0
