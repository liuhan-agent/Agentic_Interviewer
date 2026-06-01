"""Depth-mode follow-up slot selection.

Deep interviews treat ``max_turns`` as a target when the normal coverage
loop has already passed every dimension. This module keeps that extra
selection policy small and side-effect free so routers and director nodes
can make the same decision without changing the LangGraph topology.
"""
from __future__ import annotations

from typing import Any

from app.engine.workflow.eval_helpers import is_evaluator_fallback
from app.engine.workflow.state import InterviewState

DEPTH_FOLLOWUP_PHASE = "depth_followup"
DEPTH_FOLLOWUP_PLAN_TEMPLATE = "deep_probe"

_FAILURE_CATEGORY_TO_PROBE = {
    "missing_evidence": "evidence_probe",
    "missing_tradeoff": "tradeoff_probe",
    "missing_metrics": "metric_probe",
    "unclear_architecture": "architecture_challenge",
    "weak_debugging": "debugging_probe",
    "weak_prioritization": "prioritization_probe",
    "weak_roleplay_response": "roleplay_probe",
}


def _int_or_default(value: Any, default: int) -> int:
    if isinstance(value, bool):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _depth_target_turns(state: InterviewState) -> int:
    return max(1, _int_or_default(state.get("max_turns"), 8))


def _formal_turn_idx(state: InterviewState) -> int:
    return max(
        0,
        _int_or_default(
            state.get("formal_turn_idx", state.get("turn_idx", 0)),
            0,
        ),
    )


def _turn_budget_remaining(state: InterviewState) -> int:
    raw_budget = state.get("turn_budget_remaining")
    if raw_budget is None:
        return max(0, _depth_target_turns(state) - _formal_turn_idx(state))
    return max(0, _int_or_default(raw_budget, 0))


def _all_dimensions_passed(state: InterviewState) -> bool:
    dims = list(state.get("dimensions") or [])
    if not dims:
        return False
    status = state.get("dimension_status") or {}
    return all(status.get(dim) == "passed" for dim in dims)


def should_consider_depth_followup(state: InterviewState) -> bool:
    """Return True when deep mode may use an extra formal follow-up slot."""

    if state.get("status") == "cancelled":
        return False
    runtime_config = state.get("runtime_config") or {}
    if str(runtime_config.get("interview_depth") or "standard") != "deep":
        return False
    if _formal_turn_idx(state) >= _depth_target_turns(state):
        return False
    if _turn_budget_remaining(state) <= 0:
        return False
    return _all_dimensions_passed(state)


def _qa_history(state: InterviewState) -> list[dict[str, Any]]:
    return [turn for turn in state.get("qa_history") or [] if isinstance(turn, dict)]


def _evaluation(turn: dict[str, Any]) -> dict[str, Any]:
    evaluation = turn.get("evaluation")
    return evaluation if isinstance(evaluation, dict) else {}


def _is_depth_followup_turn(turn: dict[str, Any]) -> bool:
    metadata = turn.get("depth_followup")
    return turn.get("phase") == DEPTH_FOLLOWUP_PHASE or isinstance(metadata, dict)


def _is_skipped(turn: dict[str, Any], evaluation: dict[str, Any]) -> bool:
    return (
        turn.get("answer_intent") == "skipped"
        or bool(evaluation.get("skipped"))
        or str(turn.get("skip_reason") or "").strip() != ""
    )


def _is_valid_source_turn(turn: dict[str, Any]) -> bool:
    evaluation = _evaluation(turn)
    if is_evaluator_fallback(evaluation):
        return False
    if _is_skipped(turn, evaluation):
        return False
    return True


def _passed_turn(turn: dict[str, Any]) -> bool:
    return bool(_evaluation(turn).get("passed"))


def _score(turn: dict[str, Any]) -> float | None:
    value = _evaluation(turn).get("score")
    if value is None or isinstance(value, bool):
        return None
    try:
        score = float(value)
    except (TypeError, ValueError):
        return None
    return score if score == score else None


def _anchor(turn: dict[str, Any]) -> dict[str, Any]:
    raw = turn.get("resume_anchor")
    return dict(raw) if isinstance(raw, dict) and raw else {}


def _anchor_key(turn: dict[str, Any]) -> str:
    anchor = _anchor(turn)
    return str(
        anchor.get("anchor_key")
        or anchor.get("focus_id")
        or anchor.get("project_id")
        or turn.get("resume_anchor_key")
        or ""
    ).strip()


def _turn_idx(turn: dict[str, Any]) -> int | None:
    value = turn.get("turn_idx")
    if isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _turn_has_material(turn: dict[str, Any]) -> bool:
    if _anchor(turn):
        return True
    if isinstance(turn.get("question_basis"), dict) and turn.get("question_basis"):
        return True
    if str(turn.get("question") or "").strip():
        return True
    if str(turn.get("answer") or "").strip():
        return True
    evaluation = _evaluation(turn)
    return bool(
        evaluation.get("weaknesses")
        or evaluation.get("strengths")
        or evaluation.get("acceptance_check_results")
        or evaluation.get("rubric_coverage")
    )


def _same_focus(left: dict[str, Any], right: dict[str, Any]) -> bool:
    left_anchor = _anchor_key(left)
    right_anchor = _anchor_key(right)
    if left_anchor and right_anchor:
        return left_anchor == right_anchor
    return str(left.get("dimension") or "") == str(right.get("dimension") or "")


def _used_depth_source_turns(history: list[dict[str, Any]]) -> set[int]:
    used: set[int] = set()
    for turn in history:
        metadata = turn.get("depth_followup")
        if not isinstance(metadata, dict):
            continue
        source_idx = _int_or_default(metadata.get("source_turn_idx"), -1)
        if source_idx >= 0:
            used.add(source_idx)
    return used


def _recovered_parent_turns(history: list[dict[str, Any]]) -> set[int]:
    recovered: set[int] = set()
    for turn in history:
        metadata = turn.get("depth_followup")
        if not isinstance(metadata, dict):
            continue
        parent_idx = _int_or_default(metadata.get("parent_turn_idx"), -1)
        if parent_idx >= 0:
            recovered.add(parent_idx)
    return recovered


def _depth_slot_rank(history: list[dict[str, Any]]) -> int:
    return 1 + sum(1 for turn in history if _is_depth_followup_turn(turn))


def sanitize_depth_followup_metadata(value: Any) -> dict[str, Any]:
    """Return the stable public metadata subset for trace/report payloads."""

    if not isinstance(value, dict):
        return {}
    out: dict[str, Any] = {}
    for key in (
        "source_turn_idx",
        "parent_turn_idx",
        "depth_reason",
        "depth_slot_rank",
        "depth_target_turns",
    ):
        raw = value.get(key)
        if key in {
            "source_turn_idx",
            "parent_turn_idx",
            "depth_slot_rank",
            "depth_target_turns",
        }:
            converted = _int_or_default(raw, -1)
            if converted >= 0:
                out[key] = converted
        elif isinstance(raw, str) and raw.strip():
            out[key] = raw.strip()
    return out


def _probe_intent_for_turn(turn: dict[str, Any], *, reason: str) -> str:
    probe = str(turn.get("probe_intent") or "").strip()
    if probe:
        return probe
    evaluation = _evaluation(turn)
    for category in evaluation.get("failure_categories") or []:
        mapped = _FAILURE_CATEGORY_TO_PROBE.get(str(category or "").strip())
        if mapped:
            return mapped
    weakness_text = " ".join(str(item) for item in evaluation.get("weaknesses") or [])
    lowered = weakness_text.lower()
    if "debug" in lowered or "failure" in lowered or "rollback" in lowered:
        return "debugging_probe"
    if "metric" in lowered or "量化" in weakness_text:
        return "metric_probe"
    if "trade" in lowered or "取舍" in weakness_text:
        return "tradeoff_probe"
    if reason == "evidence_gap":
        return "evidence_probe"
    return "debugging_probe"


def _slot_from_turn(
    state: InterviewState,
    turn: dict[str, Any],
    *,
    reason: str,
    rank: int,
    parent_turn_idx: int | None = None,
    source_turn_idx: int | None = None,
) -> dict[str, Any] | None:
    resolved_source = source_turn_idx if source_turn_idx is not None else _turn_idx(turn)
    if resolved_source is None:
        return None
    dimension = str(turn.get("dimension") or state.get("current_dimension") or "")
    if not dimension:
        return None
    slot: dict[str, Any] = {
        "phase": DEPTH_FOLLOWUP_PHASE,
        "source_turn_idx": resolved_source,
        "dimension": dimension,
        "resume_anchor": _anchor(turn),
        "probe_intent": _probe_intent_for_turn(turn, reason=reason),
        "plan_template": DEPTH_FOLLOWUP_PLAN_TEMPLATE,
        "depth_reason": reason,
        "depth_slot_rank": rank,
        "depth_target_turns": _depth_target_turns(state),
    }
    if parent_turn_idx is not None:
        slot["parent_turn_idx"] = parent_turn_idx
    question_basis = turn.get("question_basis")
    if isinstance(question_basis, dict) and question_basis:
        slot["question_basis"] = dict(question_basis)
    return slot


def _failed_depth_followup_recovery_slot(
    state: InterviewState,
    history: list[dict[str, Any]],
    *,
    rank: int,
) -> dict[str, Any] | None:
    recovered_parents = _recovered_parent_turns(history)
    by_turn_idx = {
        idx: turn
        for turn in history
        if (idx := _turn_idx(turn)) is not None
    }
    for turn in reversed(history):
        turn_idx = _turn_idx(turn)
        if turn_idx is None or turn_idx in recovered_parents:
            continue
        if not _is_depth_followup_turn(turn) or not _is_valid_source_turn(turn):
            continue
        if _passed_turn(turn):
            continue
        metadata = turn.get("depth_followup") if isinstance(turn.get("depth_followup"), dict) else {}
        if metadata.get("depth_reason") == "depth_followup_recovery":
            continue
        source_idx = _int_or_default(metadata.get("source_turn_idx"), turn_idx)
        source_turn = by_turn_idx.get(source_idx, turn)
        if not _turn_has_material(source_turn) and not _turn_has_material(turn):
            continue
        source_for_slot = source_turn if source_turn is not None else turn
        return _slot_from_turn(
            state,
            source_for_slot,
            reason="depth_followup_recovery",
            rank=rank,
            parent_turn_idx=turn_idx,
            source_turn_idx=source_idx,
        )
    return None


def _recent_refine_then_passed_slot(
    state: InterviewState,
    candidates: list[dict[str, Any]],
    *,
    rank: int,
) -> dict[str, Any] | None:
    for idx in range(len(candidates) - 1, -1, -1):
        turn = candidates[idx]
        if not _passed_turn(turn) or not _turn_has_material(turn):
            continue
        earlier = candidates[:idx]
        if any(
            not _passed_turn(prev)
            and _same_focus(prev, turn)
            and _is_valid_source_turn(prev)
            for prev in earlier
        ):
            return _slot_from_turn(
                state,
                turn,
                reason="recent_refine_then_passed",
                rank=rank,
            )
    return None


def _lowest_passed_score_slot(
    state: InterviewState,
    candidates: list[dict[str, Any]],
    *,
    rank: int,
) -> dict[str, Any] | None:
    scored = [
        (score, turn)
        for turn in candidates
        if _passed_turn(turn)
        and _turn_has_material(turn)
        and (score := _score(turn)) is not None
    ]
    if not scored:
        return None
    _, turn = sorted(scored, key=lambda item: (item[0], _turn_idx(item[1]) or 0))[0]
    return _slot_from_turn(
        state,
        turn,
        reason="lowest_passed_score",
        rank=rank,
    )


def _has_evidence_gap(turn: dict[str, Any]) -> bool:
    evaluation = _evaluation(turn)
    if evaluation.get("weaknesses"):
        return True
    acceptance = evaluation.get("acceptance_check_results")
    if isinstance(acceptance, dict):
        for raw in acceptance.values():
            verdict = raw.get("verdict") if isinstance(raw, dict) else raw
            if str(verdict or "").strip().lower() in {"partial", "no"}:
                return True
    rubric = evaluation.get("rubric_coverage")
    if isinstance(rubric, dict):
        for raw in rubric.values():
            if str(raw or "").strip().lower() in {"partial", "missing"}:
                return True
    return False


def _evidence_gap_slot(
    state: InterviewState,
    candidates: list[dict[str, Any]],
    *,
    rank: int,
) -> dict[str, Any] | None:
    for turn in reversed(candidates):
        if _turn_has_material(turn) and _has_evidence_gap(turn):
            return _slot_from_turn(
                state,
                turn,
                reason="evidence_gap",
                rank=rank,
            )
    return None


def _core_skill_anchor_slot(
    state: InterviewState,
    candidates: list[dict[str, Any]],
    *,
    rank: int,
) -> dict[str, Any] | None:
    required = {
        str(skill).strip().lower()
        for skill in (state.get("job_spec") or {}).get("required_skills") or []
        if str(skill).strip()
    }
    with_anchor = [
        turn
        for turn in candidates
        if _passed_turn(turn) and _turn_has_material(turn) and _anchor(turn)
    ]
    if not with_anchor:
        return None
    if required:
        for turn in reversed(with_anchor):
            skills = {
                str(skill).strip().lower()
                for skill in _anchor(turn).get("skills") or []
                if str(skill).strip()
            }
            if skills & required:
                return _slot_from_turn(
                    state,
                    turn,
                    reason="core_skill_anchor",
                    rank=rank,
                )
    return _slot_from_turn(
        state,
        with_anchor[-1],
        reason="core_skill_anchor",
        rank=rank,
    )


def select_depth_followup_slot(state: InterviewState) -> dict[str, Any] | None:
    """Pick the next high-value depth follow-up slot, or ``None``.

    Selection priority:
    1. recover the most recent failed depth follow-up once;
    2. revisit a turn that was weak and then passed;
    3. probe the lowest-scoring passed turn;
    4. close an evidence gap;
    5. deepen a core-skill/high-priority resume anchor.
    """

    if not should_consider_depth_followup(state):
        return None

    history = _qa_history(state)
    rank = _depth_slot_rank(history)
    recovery = _failed_depth_followup_recovery_slot(state, history, rank=rank)
    if recovery is not None:
        return recovery

    used_sources = _used_depth_source_turns(history)
    candidates = [
        turn
        for turn in history
        if _is_valid_source_turn(turn)
        and not _is_depth_followup_turn(turn)
        and ((idx := _turn_idx(turn)) is not None)
        and idx not in used_sources
    ]

    for selector in (
        _recent_refine_then_passed_slot,
        _lowest_passed_score_slot,
        _evidence_gap_slot,
        _core_skill_anchor_slot,
    ):
        slot = selector(state, candidates, rank=rank)
        if slot is not None:
            return slot
    return None


def preserve_depth_followup_dimension_status(
    *,
    state: InterviewState,
    status: dict[str, str],
    dimension: str,
) -> dict[str, str]:
    """Keep a previously passed dimension passed after depth follow-up scoring."""

    question = state.get("current_question") or {}
    is_depth = (
        isinstance(question, dict)
        and (
            question.get("phase") == DEPTH_FOLLOWUP_PHASE
            or isinstance(question.get("depth_followup"), dict)
        )
    )
    if not is_depth or not dimension:
        return status
    previous = state.get("dimension_status") or {}
    if previous.get(dimension) != "passed":
        return status
    next_status = dict(status or {})
    next_status[dimension] = "passed"
    return next_status
