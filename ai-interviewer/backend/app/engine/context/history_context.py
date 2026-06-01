"""Deterministic interview history projection for generator context.

The complete ``qa_history`` remains the source of truth. This module
builds the prompt-facing projection used by ask_question: compact
dimension summaries, a recent QA prompt view, and current open gaps.
It never calls an LLM and never mutates the source turns.
"""
from __future__ import annotations

import json
import re
from typing import Any

DEFAULT_RECENT_QA_WINDOW = 3
DEFAULT_HISTORY_BUDGET_CHARS = 8000
DEFAULT_RECENT_ANSWER_SOFT_LIMIT_CHARS = 1400
DEFAULT_RECENT_QUESTION_LIMIT_CHARS = 500
FIELD_TEXT_LIMIT = 240
LIST_ITEM_LIMIT = 5
COMPACT_LIST_ITEM_LIMIT = 3
COMPACT_FIELD_TEXT_LIMIT = 120

__all__ = ["build_history_context"]


def _text(value: Any, *, limit: int = FIELD_TEXT_LIMIT) -> str:
    raw = str(value or "").strip()
    if len(raw) <= limit:
        return raw
    return raw[: max(0, limit - 3)].rstrip() + "..."


def _number(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _record(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list_strings(value: Any, *, limit: int = LIST_ITEM_LIMIT) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = _text(item)
        if text and text not in seen:
            result.append(text)
            seen.add(text)
        if len(result) >= limit:
            break
    return result


_OPERATIONAL_GAP_TERMS = (
    "compensation",
    "success rate",
    "retry",
    "time window",
    "manual",
    "fallback",
    "\u8865\u507f",
    "\u6210\u529f\u7387",
    "\u91cd\u8bd5",
    "\u65f6\u95f4\u7a97\u53e3",
    "\u4eba\u5de5",
    "\u515c\u5e95",
    "\u5b57\u6bb5",
)


def _normalized_gap_text(value: str) -> str:
    lowered = value.strip().lower()
    compact = re.sub(r"[^0-9a-z\u4e00-\u9fff]+", " ", lowered)
    return " ".join(compact.split()) or lowered


def _has_any(value: str, terms: tuple[str, ...]) -> bool:
    return any(term in value for term in terms)


def _gap_key_reason(value: str) -> tuple[str, str]:
    lowered = value.strip().lower()
    normalized = _normalized_gap_text(value)
    missing_terms = ("未", "缺", "missing", "lack", "不够", "没有", "仅")
    metric_terms = (
        "指标",
        "数值",
        "量化",
        "阈值",
        "tps",
        "qps",
        "p95",
        "p99",
        "响应时间",
        "错误率",
    )
    rollback_terms = ("回滚", "旧方案", "止损", "rollback")
    cache_atomic_terms = ("原子", "版本检查", "version check", "lua")
    db_pressure_terms = ("缓存穿透", "限流", "熔断", "压力保护", "db", "数据库")

    if _has_any(lowered, rollback_terms) and _has_any(lowered, missing_terms):
        return "rollback_plan_missing", "near_synonym:rollback_plan_missing"
    if _has_any(lowered, metric_terms) and _has_any(lowered, missing_terms):
        return "missing_metric_numbers", "near_synonym:missing_metric_numbers"
    if "缓存" in lowered and _has_any(lowered, cache_atomic_terms):
        return "cache_read_atomicity", "near_synonym:cache_read_atomicity"
    if (
        "缓存" in lowered
        and _has_any(lowered, db_pressure_terms)
        and _has_any(lowered, missing_terms)
    ):
        return "db_pressure_protection", "near_synonym:db_pressure_protection"
    operational_hits = sum(1 for term in _OPERATIONAL_GAP_TERMS if term in lowered)
    if operational_hits >= 2:
        return "operational_recovery_evidence", "near_synonym:operational_recovery_evidence"
    return normalized[:120] or lowered[:120], "normalized_text"


def _gap_key(value: str) -> str:
    return _gap_key_reason(value)[0]


def _gap_specificity_score(value: str) -> tuple[int, int]:
    lowered = value.strip().lower()
    signal_terms = (
        "tps",
        "qps",
        "p95",
        "p99",
        "错误率",
        "响应时间",
        "阈值",
        "指标名称",
        "旧方案",
        "快速止损",
        "止损",
        "限流",
        "熔断",
        "半开",
        "原子",
        "版本",
        "lua",
        "补偿",
        "幂等",
    )
    score = len(set(re.findall(r"[0-9a-z]+|[\u4e00-\u9fff]{2,}", lowered)))
    score += sum(4 for term in signal_terms if term in lowered)
    score += len(re.findall(r"\d+(?:\.\d+)?%?", lowered)) * 3
    if "如" in value or "(" in value or "（" in value:
        score += 2
    return score, len(value)


def _empty_gap_dedupe_diagnostics(
    *,
    raw_count: int = 0,
    deduped_count: int = 0,
) -> dict[str, Any]:
    return {
        "raw_count": raw_count,
        "deduped_count": deduped_count,
        "merge_count": 0,
        "groups": [],
    }


def _dedupe_gap_texts_with_diagnostics(
    values: list[str],
    *,
    limit: int = LIST_ITEM_LIMIT,
) -> tuple[list[str], dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    raw_count = 0
    for value in values:
        text = _text(value)
        if not text:
            continue
        raw_count += 1
        key, reason = _gap_key_reason(text)
        score = _gap_specificity_score(text)
        group = groups.get(key)
        if group is None:
            groups[key] = {
                "key": key,
                "reason": reason,
                "kept": text,
                "kept_score": score,
                "kept_count": 1,
                "raw_count": 1,
                "text_counts": {text: 1},
                "examples": [text],
                "first_index": len(order),
            }
            order.append(key)
            continue
        group["raw_count"] = int(group.get("raw_count") or 0) + 1
        text_counts = group.setdefault("text_counts", {})
        text_counts[text] = int(text_counts.get(text) or 0) + 1
        examples = group.setdefault("examples", [])
        if len(examples) < 3 and text not in examples:
            examples.append(text)
        text_count = int(text_counts[text])
        kept_count = int(group.get("kept_count") or 0)
        kept_score = group.get("kept_score", (0, 0))
        clearly_more_specific = score[0] >= kept_score[0] + 6
        more_frequent_with_similar_detail = (
            text_count > kept_count and score[0] + 4 >= kept_score[0]
        )
        tied_frequency_more_specific = text_count == kept_count and score > kept_score
        if (
            clearly_more_specific
            or more_frequent_with_similar_detail
            or tied_frequency_more_specific
        ):
            group["kept"] = text
            group["kept_score"] = score
            group["kept_count"] = text_count

    priority = {
        "missing_metric_numbers": 10,
        "rollback_plan_missing": 20,
        "cache_read_atomicity": 30,
        "db_pressure_protection": 40,
        "operational_recovery_evidence": 90,
    }
    ordered_groups = sorted(
        (groups[key] for key in order),
        key=lambda item: (priority.get(str(item.get("key")), 100), item["first_index"]),
    )
    result = [str(group["kept"]) for group in ordered_groups[: max(0, limit)]]
    dedupe_groups = [
        {
            "key": str(group["key"]),
            "reason": str(group["reason"]),
            "kept": str(group["kept"]),
            "merged_count": int(group["raw_count"]) - 1,
            "examples": [str(example) for example in group.get("examples") or []],
        }
        for group in ordered_groups
        if int(group["raw_count"]) > 1
    ]
    diagnostics = {
        "raw_count": raw_count,
        "deduped_count": len(result),
        "merge_count": sum(group["merged_count"] for group in dedupe_groups),
        "groups": dedupe_groups,
    }
    return result, diagnostics


def _dedupe_gap_texts(values: list[str], *, limit: int = LIST_ITEM_LIMIT) -> list[str]:
    return _dedupe_gap_texts_with_diagnostics(values, limit=limit)[0]


def _turn_idx(turn: dict[str, Any], fallback: int) -> int:
    try:
        return int(turn.get("turn_idx", fallback))
    except (TypeError, ValueError):
        return fallback


def _project_dimension(dimension: str, turns: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(turns, key=lambda item: _turn_idx(item, 0))
    latest = ordered[-1] if ordered else {}
    latest_eval = _record(latest.get("evaluation"))
    scores = [
        score
        for score in (_number(_record(turn.get("evaluation")).get("score")) for turn in ordered)
        if score is not None
    ]
    latest_score = _number(latest_eval.get("score"))
    open_gaps: list[str] = []
    covered: list[str] = []
    for turn in reversed(ordered):
        evaluation = _record(turn.get("evaluation"))
        open_gaps.extend(_list_strings(evaluation.get("weaknesses")))
        covered.extend(_list_strings(evaluation.get("strengths")))
        if len(open_gaps) >= LIST_ITEM_LIMIT and len(covered) >= LIST_ITEM_LIMIT:
            break

    open_gap_texts, open_gap_dedupe = _dedupe_gap_texts_with_diagnostics(open_gaps)

    return {
        "dimension": dimension,
        "turns": len(ordered),
        "latest_turn_idx": _turn_idx(latest, -1),
        "best_score": max(scores) if scores else None,
        "latest_score": latest_score,
        "passed": bool(latest_eval.get("passed")) if latest_eval else False,
        "last_question": _text(latest.get("question")),
        "last_action": _text(latest.get("selected_action")),
        "resume_anchor": _record(latest.get("resume_anchor")),
        "target_skills": _list_strings(latest.get("target_skills")),
        "covered": _dedupe(covered),
        "open_gaps": open_gap_texts,
        "open_gap_dedupe": open_gap_dedupe,
        "recommended_next": _text(latest_eval.get("recommended_next")),
    }


def _dedupe(values: list[str], *, limit: int = LIST_ITEM_LIMIT) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value and value not in seen:
            result.append(value)
            seen.add(value)
        if len(result) >= limit:
            break
    return result


def _build_projection(
    *,
    qa_history: list[dict[str, Any]],
    current_dimension: str | None,
) -> dict[str, Any]:
    by_dimension: dict[str, list[dict[str, Any]]] = {}
    last_turn_idx = -1
    for fallback_idx, turn in enumerate(qa_history):
        if not isinstance(turn, dict):
            continue
        dimension = _text(turn.get("dimension") or "general", limit=80) or "general"
        by_dimension.setdefault(dimension, []).append(turn)
        last_turn_idx = max(last_turn_idx, _turn_idx(turn, fallback_idx))

    dimensions = [
        _project_dimension(dimension, turns)
        for dimension, turns in sorted(by_dimension.items())
    ]
    current_gaps: list[str] = []
    current_gap_dedupe = _empty_gap_dedupe_diagnostics()
    for item in dimensions:
        if item.get("dimension") == current_dimension:
            current_gaps = list(item.get("open_gaps") or [])
            current_gap_dedupe = _record(item.get("open_gap_dedupe"))
            break
    if not current_gaps:
        for item in sorted(
            dimensions,
            key=lambda dim: dim.get("latest_turn_idx", -1),
            reverse=True,
        ):
            current_gaps.extend([str(gap) for gap in item.get("open_gaps") or []])
            current_gap_dedupe = _record(item.get("open_gap_dedupe"))
            if current_gaps:
                break

    return {
        "version": 1,
        "mode": "deterministic_projection",
        "source_qa_count": len([turn for turn in qa_history if isinstance(turn, dict)]),
        "source_last_turn_idx": last_turn_idx,
        "current_dimension": current_dimension or "",
        "dimensions": dimensions,
        "current_gaps": _dedupe_gap_texts(current_gaps),
        "current_gap_dedupe": current_gap_dedupe
        or _empty_gap_dedupe_diagnostics(
            raw_count=len(current_gaps),
            deduped_count=len(current_gaps),
        ),
    }


def _compact_text_list(value: Any, *, limit: int, text_limit: int) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = _text(item, limit=text_limit)
        if text and text not in seen:
            result.append(text)
            seen.add(text)
        if len(result) >= limit:
            break
    return result


def _compact_dimension(
    item: dict[str, Any],
    *,
    gap_limit: int,
    text_limit: int,
    include_context_fields: bool,
) -> dict[str, Any]:
    compact: dict[str, Any] = {
        "dimension": item.get("dimension"),
        "turns": item.get("turns"),
        "latest_turn_idx": item.get("latest_turn_idx"),
        "best_score": item.get("best_score"),
        "latest_score": item.get("latest_score"),
        "passed": item.get("passed"),
        "open_gap_count": item.get(
            "open_gap_count",
            (
                len(item.get("open_gaps") or [])
                if isinstance(item.get("open_gaps"), list)
                else 0
            ),
        ),
    }
    if "open_gaps" in item:
        compact["open_gaps"] = _compact_text_list(
            item.get("open_gaps"),
            limit=gap_limit,
            text_limit=text_limit,
        )
    recommended_next = _text(item.get("recommended_next"), limit=text_limit)
    if recommended_next:
        compact["recommended_next"] = recommended_next
    if include_context_fields:
        last_action = _text(item.get("last_action"), limit=80)
        target_skills = _compact_text_list(
            item.get("target_skills"),
            limit=COMPACT_LIST_ITEM_LIMIT,
            text_limit=80,
        )
        if last_action:
            compact["last_action"] = last_action
        if target_skills:
            compact["target_skills"] = target_skills
    return compact


def _compact_projection(
    projection: dict[str, Any],
    *,
    gap_limit: int,
    text_limit: int,
    include_context_fields: bool,
) -> dict[str, Any]:
    dimensions = [
        _compact_dimension(
            item,
            gap_limit=gap_limit,
            text_limit=text_limit,
            include_context_fields=include_context_fields,
        )
        for item in projection.get("dimensions") or []
        if isinstance(item, dict)
    ]
    current_gaps = _compact_text_list(
        projection.get("current_gaps"),
        limit=gap_limit,
        text_limit=text_limit,
    )
    compact_projection = {
        "version": projection.get("version", 1),
        "mode": "deterministic_projection_compact",
        "projection_compacted": True,
        "source_qa_count": projection.get("source_qa_count", 0),
        "source_last_turn_idx": projection.get("source_last_turn_idx", -1),
        "current_dimension": projection.get("current_dimension", ""),
        "dimensions": dimensions,
        "current_gap_count": projection.get("current_gap_count", len(current_gaps)),
        "current_gap_dimensions": list(projection.get("current_gap_dimensions") or []),
    }
    if "current_gaps" in projection:
        compact_projection["current_gaps"] = current_gaps
    return compact_projection


def _current_gap_dimensions(
    projection: dict[str, Any],
    current_gaps: list[str],
) -> list[str]:
    gap_set = {str(gap) for gap in current_gaps if str(gap)}
    dimensions: list[str] = []
    for item in projection.get("dimensions") or []:
        if not isinstance(item, dict):
            continue
        dimension = str(item.get("dimension") or "")
        if not dimension:
            continue
        if any(str(gap) in gap_set for gap in item.get("open_gaps") or []):
            dimensions.append(dimension)
    return _dedupe(dimensions)


def _prompt_dimension_index(
    item: dict[str, Any],
    *,
    include_context_fields: bool,
) -> dict[str, Any]:
    indexed: dict[str, Any] = {
        "dimension": item.get("dimension"),
        "turns": item.get("turns"),
        "latest_turn_idx": item.get("latest_turn_idx"),
        "best_score": item.get("best_score"),
        "latest_score": item.get("latest_score"),
        "passed": item.get("passed"),
        "open_gap_count": len(item.get("open_gaps") or []),
    }
    recommended_next = _text(item.get("recommended_next"), limit=80)
    if recommended_next:
        indexed["recommended_next"] = recommended_next
    if include_context_fields:
        last_action = _text(item.get("last_action"), limit=80)
        target_skills = _compact_text_list(
            item.get("target_skills"),
            limit=COMPACT_LIST_ITEM_LIMIT,
            text_limit=80,
        )
        if last_action:
            indexed["last_action"] = last_action
        if target_skills:
            indexed["target_skills"] = target_skills
    return indexed


def _build_prompt_projection(
    projection: dict[str, Any],
    *,
    current_gaps: list[str],
    recent_window: int,
) -> dict[str, Any]:
    source_qa_count = int(projection.get("source_qa_count") or 0)
    short_history = source_qa_count <= max(0, int(recent_window))
    dimensions = [
        _prompt_dimension_index(
            item,
            include_context_fields=not short_history,
        )
        for item in projection.get("dimensions") or []
        if isinstance(item, dict)
    ]
    return {
        "version": projection.get("version", 1),
        "mode": "coverage_index" if short_history else "deterministic_projection_index",
        "source_qa_count": source_qa_count,
        "source_last_turn_idx": projection.get("source_last_turn_idx", -1),
        "current_dimension": projection.get("current_dimension", ""),
        "dimensions": dimensions,
        "current_gap_count": len(current_gaps),
        "current_gap_dimensions": _current_gap_dimensions(projection, current_gaps),
    }


def _truncate_recent_turn(
    turn: dict[str, Any],
    *,
    question_limit: int | None,
    answer_limit: int | None,
) -> dict[str, Any]:
    evaluation = _record(turn.get("evaluation"))
    question = str(turn.get("question") or "")
    answer = str(turn.get("answer") or "")
    question_view = (
        question if question_limit is None else _text(question, limit=question_limit)
    )
    answer_view = answer
    answer_truncated = False
    if answer_limit is not None and len(answer) > answer_limit:
        answer_view = _text(answer, limit=answer_limit)
        answer_truncated = True
    return {
        "turn_idx": _turn_idx(turn, -1),
        "dimension": _text(turn.get("dimension"), limit=80),
        "question": question_view,
        "question_truncated": len(question) > len(question_view),
        "answer": answer_view,
        "answer_truncated": answer_truncated,
        "score": _number(evaluation.get("score")),
        "passed": evaluation.get("passed") if "passed" in evaluation else None,
        "selected_action": _text(turn.get("selected_action"), limit=80),
    }


def _recent_prompt_view(
    qa_history: list[dict[str, Any]],
    *,
    recent_window: int,
    question_limit: int | None,
    answer_limit: int | None,
) -> list[dict[str, Any]]:
    turns = [turn for turn in qa_history if isinstance(turn, dict)]
    return [
        _truncate_recent_turn(
            turn,
            question_limit=question_limit,
            answer_limit=answer_limit,
        )
        for turn in turns[-max(0, recent_window) :]
    ]


def _render_history_section(
    *,
    projection: dict[str, Any],
    recent_view: list[dict[str, Any]],
    current_gaps: list[str],
) -> str:
    return "\n".join(
        [
            "INTERVIEW_HISTORY_SUMMARY = "
            + json.dumps(projection, ensure_ascii=False, separators=(",", ":")),
            "RECENT_QA = "
            + json.dumps(recent_view, ensure_ascii=False, separators=(",", ":")),
            "CURRENT_GAPS = "
            + json.dumps(current_gaps, ensure_ascii=False, separators=(",", ":")),
        ]
    )


def _selector_summary(projection: dict[str, Any]) -> str:
    dimensions = projection.get("dimensions") or []
    if not dimensions:
        return "(no prior QA history)"
    lines: list[str] = []
    for item in dimensions:
        if not isinstance(item, dict):
            continue
        gaps = ", ".join(str(gap) for gap in item.get("open_gaps") or [])
        lines.append(
            " | ".join(
                part
                for part in [
                    f"dimension={item.get('dimension')}",
                    f"turns={item.get('turns')}",
                    f"latest_score={item.get('latest_score')}",
                    f"best_score={item.get('best_score')}",
                    f"passed={item.get('passed')}",
                    f"gaps={gaps}" if gaps else "",
                    f"recommended_next={item.get('recommended_next')}"
                    if item.get("recommended_next")
                    else "",
                ]
                if part
            )
        )
    return "\n".join(lines) or "(no prior QA history)"


def _slot(
    *,
    prompt_label: str,
    source_key: str,
    text: str,
    value: Any,
    truncated: bool = False,
) -> dict[str, Any]:
    stripped = text.strip()
    return {
        "prompt_label": prompt_label,
        "source_key": source_key,
        "injected": bool(stripped) and stripped not in {"[]", "{}"},
        "chars": len(text),
        "truncated": bool(truncated),
        "prompt_truncated": bool(truncated),
        "trace_text_truncated": False,
        "text": text,
        "value": value,
        "empty_reason": None if stripped and stripped not in {"[]", "{}"} else "empty",
        "legacy": False,
    }


def build_history_context(
    *,
    qa_history: list[dict[str, Any]],
    current_dimension: str | None,
    recent_window: int = DEFAULT_RECENT_QA_WINDOW,
    history_budget_chars: int = DEFAULT_HISTORY_BUDGET_CHARS,
    recent_answer_soft_limit_chars: int = DEFAULT_RECENT_ANSWER_SOFT_LIMIT_CHARS,
    recent_question_limit_chars: int = DEFAULT_RECENT_QUESTION_LIMIT_CHARS,
) -> dict[str, Any]:
    """Build the ask_question history context from complete QA history."""
    source_history = [turn for turn in qa_history if isinstance(turn, dict)]
    full_projection = _build_projection(
        qa_history=source_history,
        current_dimension=current_dimension,
    )

    active_window = max(0, int(recent_window))
    current_gaps = list(full_projection.get("current_gaps") or [])
    current_gap_dedupe = _record(full_projection.get("current_gap_dedupe"))
    projection = _build_prompt_projection(
        full_projection,
        current_gaps=current_gaps,
        recent_window=active_window,
    )
    recent_view = _recent_prompt_view(
        source_history,
        recent_window=active_window,
        question_limit=None,
        answer_limit=None,
    )
    history_section = _render_history_section(
        projection=projection,
        recent_view=recent_view,
        current_gaps=current_gaps,
    )
    truncated_recent = False
    projection_compacted = False

    if len(history_section) > history_budget_chars:
        recent_view = _recent_prompt_view(
            source_history,
            recent_window=active_window,
            question_limit=recent_question_limit_chars,
            answer_limit=recent_answer_soft_limit_chars,
        )
        truncated_recent = any(turn.get("answer_truncated") for turn in recent_view)
        history_section = _render_history_section(
            projection=projection,
            recent_view=recent_view,
            current_gaps=current_gaps,
        )

    if len(history_section) > history_budget_chars:
        for gap_limit, text_limit, include_context_fields in (
            (COMPACT_LIST_ITEM_LIMIT, COMPACT_FIELD_TEXT_LIMIT, True),
            (2, 80, False),
            (1, 60, False),
            (0, 40, False),
        ):
            projection = _compact_projection(
                projection,
                gap_limit=gap_limit,
                text_limit=text_limit,
                include_context_fields=include_context_fields,
            )
            projection_compacted = True
            history_section = _render_history_section(
                projection=projection,
                recent_view=recent_view,
                current_gaps=current_gaps,
            )
            if len(history_section) <= history_budget_chars:
                break

    while len(history_section) > history_budget_chars and active_window > 1:
        active_window -= 1
        recent_view = _recent_prompt_view(
            source_history,
            recent_window=active_window,
            question_limit=recent_question_limit_chars,
            answer_limit=recent_answer_soft_limit_chars,
        )
        truncated_recent = True
        history_section = _render_history_section(
            projection=projection,
            recent_view=recent_view,
            current_gaps=current_gaps,
        )

    if len(history_section) > history_budget_chars:
        clipped_recent = recent_view
        if clipped_recent:
            clipped_recent = [{**clipped_recent[-1], "answer": "", "answer_truncated": True}]
        truncated_recent = True
        history_section = _render_history_section(
            projection=projection,
            recent_view=clipped_recent,
            current_gaps=current_gaps,
        )
        recent_view = clipped_recent

    if len(history_section) > history_budget_chars and recent_view:
        recent_view = []
        truncated_recent = True
        history_section = _render_history_section(
            projection=projection,
            recent_view=recent_view,
            current_gaps=current_gaps,
        )

    summary_text = json.dumps(
        projection,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    recent_text = json.dumps(
        recent_view,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    gaps_text = json.dumps(
        current_gaps,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return {
        "projection": projection,
        "recent_qa_prompt_view": recent_view,
        "current_gaps": current_gaps,
        "history_section": history_section,
        "selector_summary": _selector_summary(full_projection),
        "selector_projection": full_projection,
        "prompt_slots": [
            _slot(
                prompt_label="INTERVIEW_HISTORY_SUMMARY",
                source_key="history_summary_projection",
                text=summary_text,
                value=projection,
                truncated=projection_compacted,
            ),
            _slot(
                prompt_label="RECENT_QA",
                source_key="recent_qa_prompt_view",
                text=recent_text,
                value=recent_view,
                truncated=truncated_recent,
            ),
            _slot(
                prompt_label="CURRENT_GAPS",
                source_key="current_gaps",
                text=gaps_text,
                value=current_gaps,
            ),
        ],
        "stats": {
            "source_qa_count": projection["source_qa_count"],
            "recent_turn_count": len(recent_view),
            "budget_chars": history_budget_chars,
            "rendered_chars": len(history_section),
            "projection_compacted": projection_compacted,
            "history_budget_exceeded": len(history_section) > history_budget_chars,
            "truncated_recent_answers_count": sum(
                1 for turn in recent_view if turn.get("answer_truncated")
            ),
            "current_gaps_raw_count": int(
                current_gap_dedupe.get("raw_count") or len(current_gaps)
            ),
            "current_gaps_deduped_count": len(current_gaps),
            "current_gaps_dedupe_merge_count": int(
                current_gap_dedupe.get("merge_count") or 0
            ),
            "current_gaps_dedupe_groups": list(
                current_gap_dedupe.get("groups") or []
            ),
        },
    }
