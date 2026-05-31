"""Deterministic interview history projection for generator context.

The complete ``qa_history`` remains the source of truth. This module
builds the prompt-facing projection used by ask_question: compact
dimension summaries, a recent QA prompt view, and current open gaps.
It never calls an LLM and never mutates the source turns.
"""
from __future__ import annotations

import json
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
        "open_gaps": _dedupe(open_gaps),
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
    for item in dimensions:
        if item.get("dimension") == current_dimension:
            current_gaps = list(item.get("open_gaps") or [])
            break
    if not current_gaps:
        for item in sorted(
            dimensions,
            key=lambda dim: dim.get("latest_turn_idx", -1),
            reverse=True,
        ):
            current_gaps.extend([str(gap) for gap in item.get("open_gaps") or []])
            if current_gaps:
                break

    return {
        "version": 1,
        "mode": "deterministic_projection",
        "source_qa_count": len([turn for turn in qa_history if isinstance(turn, dict)]),
        "source_last_turn_idx": last_turn_idx,
        "current_dimension": current_dimension or "",
        "dimensions": dimensions,
        "current_gaps": _dedupe(current_gaps),
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
        },
    }
