"""Adaptive difficulty adjustment based on candidate performance.

The interviewer should not hammer a weak candidate with hard
questions or bore a strong one with easy ones.  This module computes
a ``target_difficulty`` from the score trajectory on the current
dimension (and optionally the global average), which the generator
is then instructed to honour.

Algorithm
---------
1. Collect the last N scores for the current dimension.
2. Compute a weighted average (recent scores matter more).
3. Map the average to a difficulty band via configurable thresholds.
4. Apply a "momentum" adjustment: if the last two scores both rose
   or both fell by at least ``MOMENTUM_DELTA``, nudge one step in
   that direction.  This keeps the interview responsive to sudden
   shifts without overreacting to noise.

The output is one of ``"easy"`` / ``"medium"`` / ``"hard"`` which
maps directly to the generator's ``difficulty`` field and the
contract's ``bar_level`` (``intro`` / ``standard`` / ``deep_probe``).
"""
from __future__ import annotations

from typing import Literal

from app.engine.workflow.state import InterviewState, QATurn

Difficulty = Literal["easy", "medium", "hard"]

EASY_CEILING = 4.5
HARD_FLOOR = 7.0

MOMENTUM_DELTA = 2.0

LOOKBACK = 4

RECENT_WEIGHT = 0.6
OLDER_WEIGHT = 0.4

_BAR_LEVEL_MAP: dict[Difficulty, str] = {
    "easy": "intro",
    "medium": "standard",
    "hard": "deep_probe",
}

_STEP_UP: dict[Difficulty, Difficulty] = {
    "easy": "medium",
    "medium": "hard",
    "hard": "hard",
}

_STEP_DOWN: dict[Difficulty, Difficulty] = {
    "hard": "medium",
    "medium": "easy",
    "easy": "easy",
}


def difficulty_to_bar_level(difficulty: Difficulty) -> str:
    return _BAR_LEVEL_MAP.get(difficulty, "standard")


def _dim_scores(qa_history: list[QATurn], dimension: str) -> list[float]:
    scores: list[float] = []
    for qa in qa_history:
        if qa.get("dimension") != dimension:
            continue
        ev = qa.get("evaluation") or {}
        try:
            scores.append(float(ev.get("score", 0)))
        except (TypeError, ValueError):
            pass
    return scores


def _weighted_average(scores: list[float]) -> float:
    if not scores:
        return 5.0
    if len(scores) == 1:
        return scores[0]
    recent = scores[-1]
    older = scores[:-1]
    older_avg = sum(older) / len(older)
    return RECENT_WEIGHT * recent + OLDER_WEIGHT * older_avg


def _base_difficulty(avg: float) -> Difficulty:
    if avg < EASY_CEILING:
        return "easy"
    if avg >= HARD_FLOOR:
        return "hard"
    return "medium"


def _apply_momentum(
    base: Difficulty,
    scores: list[float],
) -> Difficulty:
    if len(scores) < 2:
        return base
    delta_1 = scores[-1] - scores[-2]
    if len(scores) >= 3:
        delta_2 = scores[-2] - scores[-3]
    else:
        delta_2 = delta_1

    if delta_1 >= MOMENTUM_DELTA and delta_2 >= 0:
        return _STEP_UP[base]
    if delta_1 <= -MOMENTUM_DELTA and delta_2 <= 0:
        return _STEP_DOWN[base]
    return base


def compute_target_difficulty(
    state: InterviewState,
    dimension: str,
) -> Difficulty:
    """Determine the target difficulty for the next question.

    First turn defaults to ``"medium"``.  Subsequent turns adapt
    based on the candidate's score trajectory on *dimension*.
    """
    qa_history = state.get("qa_history", [])
    if not qa_history:
        return "medium"

    scores = _dim_scores(qa_history, dimension)
    if not scores:
        global_scores = [
            float((qa.get("evaluation") or {}).get("score", 5.0))
            for qa in qa_history
            if (qa.get("evaluation") or {}).get("score") is not None
        ]
        if not global_scores:
            return "medium"
        scores = global_scores

    window = scores[-LOOKBACK:]
    avg = _weighted_average(window)
    base = _base_difficulty(avg)
    return _apply_momentum(base, window)
