"""Display-facing follow-up reason projection for replay payloads."""
from __future__ import annotations

from typing import Any

from app.engine.workflow.eval_helpers import (
    is_evaluator_fallback,
    is_system_fallback_text,
)

FOLLOWUP_REASON_TITLE = "为什么继续追问"
FOLLOWUP_REASON_SOURCE = "evaluator"

_PLAN_LABELS = {
    "simple": "基础补问",
    "quick_review": "快速确认",
    "adaptive": "针对性追问",
    "deep_probe": "深挖追问",
}

_PROBE_INTENT_LABELS = {
    "deep_probe": "深挖追问",
    "evidence_probe": "补充证据",
    "metric_probe": "量化指标",
    "tradeoff_probe": "取舍说明",
    "debugging_probe": "故障排查",
    "performance_probe": "性能分析",
    "architecture_challenge": "架构挑战",
    "coverage_closeout": "补齐覆盖",
    "experiment_probe": "实验验证",
    "prioritization_probe": "优先级判断",
    "roleplay_probe": "情景追问",
    "objection_probe": "异议处理",
    "escalation_probe": "升级处理",
    "general": "继续确认",
}


def _clean_text(value: Any) -> str:
    text = str(value or "").strip()
    if not text or is_system_fallback_text(text):
        return ""
    return text


def _dedupe_texts(values: list[Any]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        text = _clean_text(value)
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
    return out


def _label_for(value: Any) -> str:
    key = str(value or "").strip()
    return _PLAN_LABELS.get(key) or _PROBE_INTENT_LABELS.get(key) or _clean_text(value)


def _missing_rubric_items(evaluation: dict[str, Any]) -> list[str]:
    coverage = evaluation.get("rubric_coverage") or {}
    if not isinstance(coverage, dict):
        return []
    return _dedupe_texts(
        [
            key
            for key, status in coverage.items()
            if str(status or "").strip().lower() == "missing"
        ]
    )


def _weakness_items(evaluation: dict[str, Any]) -> list[str]:
    weaknesses = evaluation.get("weaknesses") or []
    if not isinstance(weaknesses, list):
        return []
    return _dedupe_texts(weaknesses)


def build_replay_followup_reason(
    evaluation: dict[str, Any],
) -> dict[str, Any] | None:
    """Build the candidate-facing reason shown in training replay.

    The evaluator still owns the scoring fields. This helper only turns
    normalized refine signals into stable Chinese display copy so the
    frontend never has to know evaluator internals.
    """
    if not isinstance(evaluation, dict):
        return None
    if is_evaluator_fallback(evaluation):
        return None
    if str(evaluation.get("recommended_next") or "").strip().lower() != "refine":
        return None

    missing_items = _missing_rubric_items(evaluation)
    weaknesses = _weakness_items(evaluation)
    failure_reason = _clean_text(evaluation.get("failure_reason"))
    plan_label = _label_for(evaluation.get("recommended_next_plan"))
    probe_label = _label_for(evaluation.get("recommended_probe_intent"))

    focus = missing_items[0] if missing_items else failure_reason
    if not focus and weaknesses:
        focus = weaknesses[0]

    if focus:
        summary = f"上一轮回答还需要补足「{focus}」，下一题会继续围绕这个点追问。"
    else:
        summary = "上一轮回答还有关键点需要进一步确认，下一题会继续追问到可判断的细节。"

    chips = _dedupe_texts(
        [
            plan_label,
            probe_label,
            *missing_items,
            failure_reason,
            *weaknesses,
            "继续追问",
            "补齐缺口",
        ]
    )[:4]

    return {
        "title": FOLLOWUP_REASON_TITLE,
        "summary": summary,
        "chips": chips,
        "source": FOLLOWUP_REASON_SOURCE,
    }


def attach_replay_followup_reason(evaluation: dict[str, Any]) -> dict[str, Any]:
    out = dict(evaluation or {})
    reason = build_replay_followup_reason(out)
    if reason is None:
        out.pop("followup_reason", None)
        return out
    out["followup_reason"] = reason
    return out


def sanitize_replay_followup_reason(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    if value.get("source") != FOLLOWUP_REASON_SOURCE:
        return None
    if _clean_text(value.get("title")) != FOLLOWUP_REASON_TITLE:
        return None
    summary = _clean_text(value.get("summary"))
    raw_chips = value.get("chips")
    if not summary or not isinstance(raw_chips, list):
        return None
    chips = _dedupe_texts(raw_chips)[:4]
    if not chips:
        return None
    return {
        "title": FOLLOWUP_REASON_TITLE,
        "summary": summary,
        "chips": chips,
        "source": FOLLOWUP_REASON_SOURCE,
    }
