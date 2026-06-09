"""Ask-question context projection for soft follow-up hints."""
from __future__ import annotations

from typing import Any


DEFAULT_RECENT_TURN_LIMIT = 3
DEFAULT_PROMPT_TEXT_LIMIT = 160
SOFT_FOLLOWUP_PROMPT_MODES = {"off", "shadow", "advisory"}

_EMPTY_COUNTS = {"quality": 0, "context": 0, "total": 0}
_TOPIC_AFFINITY_POLICY = "balanced"
_CONSTRAINTS = {
    "advisory_only": True,
    "do_not_override_seed": True,
    "do_not_create_hard_gate": True,
}


def build_soft_followup_context(
    *,
    qa_history: Any,
    current_dimension: str | None,
    ask_plan: Any,
    refine_mode: bool = False,
    prompt_mode: str = "off",
    warnings: list[str] | None = None,
    current_question_refs: Any = None,
    recent_turn_limit: int = DEFAULT_RECENT_TURN_LIMIT,
) -> dict[str, Any]:
    """Project prior soft follow-up hints into ask-question context diagnostics.

    ``off`` and ``shadow`` never inject prompt text. ``advisory`` only marks
    selected hints as eligible; the caller still owns the final prompt apply.
    """

    resolved_mode = _resolve_prompt_mode(prompt_mode)
    plan_template = _plan_template(ask_plan)
    plan_compatible = bool(refine_mode) or plan_template == "deep_probe"
    if resolved_mode == "off":
        return empty_soft_followup_context(
            current_dimension=current_dimension,
            ask_plan=ask_plan,
            reason="disabled",
            mode="off",
            warnings=warnings,
        )

    turns = _recent_turns(qa_history, limit=recent_turn_limit)
    current_refs = _question_refs(current_question_refs)
    considered_count = 0
    eligible: list[dict[str, Any]] = []
    rejected_reasons: dict[str, int] = {}
    topic_rejected_reasons: dict[str, int] = {}

    for turn in turns:
        turn_dimension = _turn_dimension(turn)
        source_refs = _turn_question_refs(turn)
        hints = _record(_record(turn.get("evaluation")).get("soft_followup_hints"))
        if not hints:
            _count(rejected_reasons, "missing_hints")
            continue
        if str(hints.get("mode") or "").strip().lower() != "shadow":
            _count(rejected_reasons, "non_shadow_mode")
            continue
        if hints.get("applied") is not False:
            _count(rejected_reasons, "already_applied")
            continue
        counts = _record(hints.get("counts"))
        total = _int(counts.get("total"))
        if total <= 0:
            _count(rejected_reasons, "empty_counts")
            continue

        hint_items = _ordered_hint_items(hints)
        considered_count += len(hint_items)
        if not plan_compatible:
            _count(rejected_reasons, "plan_not_refine_or_deep_probe", len(hint_items))
            continue
        if current_dimension and turn_dimension and turn_dimension != current_dimension:
            _count(rejected_reasons, "dimension_mismatch", len(hint_items))
            continue
        if current_dimension and not turn_dimension:
            _count(rejected_reasons, "missing_turn_dimension", len(hint_items))
            continue

        affinity = _topic_affinity(current_refs=current_refs, source_refs=source_refs)
        if affinity == "topic_affinity_mismatch":
            _count(rejected_reasons, affinity, len(hint_items))
            _count(topic_rejected_reasons, affinity, len(hint_items))
            continue

        for hint in hint_items:
            projected = _project_hint(
                hint,
                source_turn_idx=turn.get("turn_idx"),
                source_dimension=turn_dimension,
                source_refs=source_refs,
                current_refs=current_refs,
                topic_affinity=affinity,
            )
            if projected:
                eligible.append(projected)

    selected = _select_hints(eligible)
    quality_hints = [item for item in selected if item.get("hint_type") == "quality"]
    context_hints = [item for item in selected if item.get("hint_type") == "context"]
    selected_hint_ids = [str(item.get("hint_id")) for item in selected if item.get("hint_id")]

    return {
        "present": bool(selected_hint_ids),
        "mode": resolved_mode,
        "applied": False,
        "source": "soft_followup_hints",
        "considered_count": considered_count,
        "eligible_count": len(eligible),
        "selected_hint_ids": selected_hint_ids,
        "quality_hints": quality_hints,
        "context_hints": context_hints,
        "priority_order": selected_hint_ids,
        "counts": {
            "quality": len(quality_hints),
            "context": len(context_hints),
            "total": len(selected_hint_ids),
        },
        "not_applied_reason": (
            "prompt_shadow" if resolved_mode == "shadow" else _advisory_not_applied_reason(
                selected_hint_ids
            )
        ),
        "empty_reason": None if selected_hint_ids else _empty_reason(
            turns=turns,
            considered_count=considered_count,
            plan_compatible=plan_compatible,
            rejected_reasons=rejected_reasons,
        ),
        "constraints": dict(_CONSTRAINTS),
        "compatibility": {
            "current_dimension": str(current_dimension or ""),
            "plan_template": plan_template,
            "refine_mode": bool(refine_mode),
            "plan_compatible": plan_compatible,
        },
        "rejected_reasons": rejected_reasons,
        "topic_affinity_policy": _TOPIC_AFFINITY_POLICY,
        "topic_affinity_rejected_count": sum(topic_rejected_reasons.values()),
        "topic_affinity_rejected_reasons": topic_rejected_reasons,
        "warnings": list(warnings or []),
    }


def empty_soft_followup_context(
    *,
    current_dimension: str | None = None,
    ask_plan: Any = None,
    reason: str = "no_eligible_hints",
    mode: str = "off",
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    plan_template = _plan_template(ask_plan)
    resolved_mode = _resolve_prompt_mode(mode)
    return {
        "present": False,
        "mode": resolved_mode,
        "applied": False,
        "source": "soft_followup_hints",
        "considered_count": 0,
        "eligible_count": 0,
        "selected_hint_ids": [],
        "quality_hints": [],
        "context_hints": [],
        "priority_order": [],
        "counts": dict(_EMPTY_COUNTS),
        "not_applied_reason": "disabled" if resolved_mode == "off" else "prompt_shadow",
        "empty_reason": reason,
        "constraints": dict(_CONSTRAINTS),
        "compatibility": {
            "current_dimension": str(current_dimension or ""),
            "plan_template": plan_template,
            "refine_mode": False,
            "plan_compatible": False,
        },
        "rejected_reasons": {},
        "topic_affinity_policy": _TOPIC_AFFINITY_POLICY,
        "topic_affinity_rejected_count": 0,
        "topic_affinity_rejected_reasons": {},
        "warnings": list(warnings or []),
    }


def build_soft_followup_advisory_payload(
    soft_followup_context: Any,
    *,
    text_limit: int = DEFAULT_PROMPT_TEXT_LIMIT,
) -> dict[str, Any] | None:
    """Compile selected hints into a short CURRENT_GAPS advisory payload."""

    context = _record(soft_followup_context)
    if context.get("mode") != "advisory":
        return None
    if not context.get("selected_hint_ids"):
        return None
    quality_hints = [
        _prompt_hint(item, text_limit=text_limit)
        for item in _record_list(context.get("quality_hints"))[:1]
    ]
    context_hints = [
        _prompt_hint(item, text_limit=text_limit)
        for item in _record_list(context.get("context_hints"))[:1]
    ]
    quality_hints = [item for item in quality_hints if item is not None]
    context_hints = [item for item in context_hints if item is not None]
    if not quality_hints and not context_hints:
        return None
    return {
        "mode": "advisory",
        "advisory_only": True,
        "do_not_override_seed": True,
        "do_not_create_hard_gate": True,
        "do_not_override_reviewed_core": True,
        "quality_hints": quality_hints,
        "context_hints": context_hints,
        "selected_hint_ids": list(context.get("selected_hint_ids") or []),
    }


def _recent_turns(value: Any, *, limit: int) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    turns = [turn for turn in value if isinstance(turn, dict)]
    safe_limit = max(0, int(limit))
    if safe_limit == 0:
        return []
    return list(reversed(turns[-safe_limit:]))


def _ordered_hint_items(hints: dict[str, Any]) -> list[dict[str, Any]]:
    quality = [
        {**item, "_hint_type": "quality"}
        for item in _record_list(hints.get("quality_hints"))
    ]
    context = [
        {**item, "_hint_type": "context"}
        for item in _record_list(hints.get("context_hints"))
    ]
    items = [*quality, *context]
    priority = [
        str(item)
        for item in hints.get("priority_order", [])
        if str(item or "").strip()
    ] if isinstance(hints.get("priority_order"), list) else []
    rank = {hint_id: idx for idx, hint_id in enumerate(priority)}
    return sorted(
        items,
        key=lambda item: rank.get(str(item.get("hint_id") or ""), len(rank)),
    )


def _select_hints(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_types: set[str] = set()
    for item in items:
        hint_type = str(item.get("hint_type") or "")
        hint_id = str(item.get("hint_id") or "").strip()
        if hint_type not in {"quality", "context"}:
            continue
        if hint_type in seen_types:
            continue
        if hint_id and hint_id in seen_ids:
            continue
        selected.append(item)
        seen_types.add(hint_type)
        if hint_id:
            seen_ids.add(hint_id)
        if len(seen_types) == 2:
            break
    return selected


def _project_hint(
    hint: dict[str, Any],
    *,
    source_turn_idx: Any,
    source_dimension: str,
    source_refs: dict[str, str],
    current_refs: dict[str, str],
    topic_affinity: str,
) -> dict[str, Any] | None:
    hint_id = str(hint.get("hint_id") or "").strip()
    text = str(hint.get("text") or "").strip()
    focus = str(hint.get("focus") or "").strip()
    check_id = str(hint.get("check_id") or "").strip()
    if not hint_id and not text and not focus and not check_id:
        return None
    return {
        "hint_id": hint_id,
        "suggestion_id": str(hint.get("suggestion_id") or "").strip(),
        "source": str(hint.get("source") or "").strip(),
        "intent": str(hint.get("intent") or "").strip(),
        "hint_type": str(hint.get("_hint_type") or "").strip(),
        "check_id": check_id,
        "verdict": str(hint.get("verdict") or "").strip(),
        "reason": str(hint.get("reason") or "").strip(),
        "text": text,
        "focus": focus,
        "evidence_count": max(0, _int(hint.get("evidence_count"))),
        "source_turn_idx": source_turn_idx,
        "source_dimension": source_dimension,
        "source_seed_id": source_refs.get("seed_id", ""),
        "source_variant_id": source_refs.get("variant_id", ""),
        "current_seed_id": current_refs.get("seed_id", ""),
        "current_variant_id": current_refs.get("variant_id", ""),
        "topic_affinity": topic_affinity,
    }


def _turn_dimension(turn: dict[str, Any]) -> str:
    direct = str(turn.get("dimension") or "").strip()
    if direct:
        return direct
    question = _record(turn.get("current_question") or turn.get("question_payload"))
    question_dimension = str(question.get("dimension") or "").strip()
    if question_dimension:
        return question_dimension
    evaluation = _record(turn.get("evaluation"))
    return str(evaluation.get("dimension") or "").strip()


def _turn_question_refs(turn: dict[str, Any]) -> dict[str, str]:
    refs = _question_refs(turn.get("selection_artifacts"))
    if refs:
        return refs
    current_question = _record(turn.get("current_question") or turn.get("question"))
    refs = _question_refs(current_question)
    if refs:
        return refs
    return _question_refs(turn.get("question_payload"))


def _question_refs(value: Any) -> dict[str, str]:
    record = _record(value)
    if not record:
        return {}

    direct_seed_id = str(record.get("seed_id") or "").strip()
    direct_variant_id = str(record.get("variant_id") or "").strip()
    if direct_seed_id or direct_variant_id:
        return {"seed_id": direct_seed_id, "variant_id": direct_variant_id}

    contract_seed = _record(_record(record.get("contract_hints")).get("question_seed"))
    seed_id = str(contract_seed.get("seed_id") or "").strip()
    variant_id = str(contract_seed.get("variant_id") or "").strip()
    if seed_id or variant_id:
        return {"seed_id": seed_id, "variant_id": variant_id}

    question_seed = _record(record.get("question_seed"))
    seed_id = str(question_seed.get("seed_id") or "").strip()
    variant_id = str(question_seed.get("variant_id") or "").strip()
    if seed_id or variant_id:
        return {"seed_id": seed_id, "variant_id": variant_id}

    artifacts = _record(record.get("selection_artifacts"))
    if artifacts:
        return _question_refs(artifacts)

    items = _record_list(record.get("question_items"))
    if not items:
        return {}

    has_injected_marker = any("injected" in item for item in items)
    if has_injected_marker:
        preferred = [
            item
            for item in items
            if item.get("injected") is True and _int(item.get("rank")) == 1
        ]
        if not preferred:
            preferred = [
                item
                for item in items
                if item.get("injected") is True
            ]
        if not preferred:
            return {}
    else:
        preferred = [
            item
            for item in items
            if _int(item.get("rank")) == 1
        ]
        if not preferred:
            preferred = items
    item = preferred[0]
    seed_id = str(item.get("seed_id") or "").strip()
    variant_id = str(item.get("variant_id") or "").strip()
    if not seed_id and not variant_id:
        return {}
    return {"seed_id": seed_id, "variant_id": variant_id}


def _topic_affinity(
    *,
    current_refs: dict[str, str],
    source_refs: dict[str, str],
) -> str:
    current_seed_id = str(current_refs.get("seed_id") or "").strip()
    source_seed_id = str(source_refs.get("seed_id") or "").strip()
    if not current_seed_id or not source_seed_id:
        return "dimension_fallback_missing_refs"
    if current_seed_id == source_seed_id:
        return "same_seed"
    return "topic_affinity_mismatch"


def _plan_template(ask_plan: Any) -> str:
    if not isinstance(ask_plan, dict):
        return ""
    return str(ask_plan.get("template") or "").strip()


def _resolve_prompt_mode(value: str) -> str:
    mode = str(value or "off").strip().lower()
    return mode if mode in SOFT_FOLLOWUP_PROMPT_MODES else "off"


def _advisory_not_applied_reason(selected_hint_ids: list[str]) -> str:
    return "pending_prompt_apply" if selected_hint_ids else "no_eligible_hints"


def _prompt_hint(
    item: dict[str, Any],
    *,
    text_limit: int,
) -> dict[str, Any] | None:
    hint_id = str(item.get("hint_id") or "").strip()
    focus = _short_text(item.get("focus") or item.get("text"), limit=text_limit)
    check_id = str(item.get("check_id") or "").strip()
    if not hint_id and not focus and not check_id:
        return None
    return {
        "hint_id": hint_id,
        "intent": str(item.get("intent") or "").strip(),
        "check_id": check_id,
        "focus": focus,
        "source": str(item.get("source") or "").strip(),
        "verdict": str(item.get("verdict") or "").strip(),
        "source_turn_idx": item.get("source_turn_idx"),
        "source_dimension": str(item.get("source_dimension") or "").strip(),
    }


def _short_text(value: Any, *, limit: int) -> str:
    text = str(value or "").strip()
    safe_limit = max(0, int(limit))
    if safe_limit <= 0:
        return ""
    if len(text) <= safe_limit:
        return text
    return text[: max(0, safe_limit - 3)].rstrip() + "..."


def _empty_reason(
    *,
    turns: list[dict[str, Any]],
    considered_count: int,
    plan_compatible: bool,
    rejected_reasons: dict[str, int],
) -> str:
    if not turns:
        return "no_history"
    if not plan_compatible and considered_count > 0:
        return "plan_not_refine_or_deep_probe"
    if considered_count <= 0 and rejected_reasons:
        return "no_valid_shadow_hints"
    return "no_eligible_hints"


def _record(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _record_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _count(target: dict[str, int], key: str, amount: int = 1) -> None:
    target[key] = int(target.get(key) or 0) + max(0, int(amount))
