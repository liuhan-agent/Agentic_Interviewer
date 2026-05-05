"""Classify candidate answers before they affect scoring feedback."""
from __future__ import annotations

from typing import Literal

AnswerIntent = Literal[
    "normal",
    "empty",
    "clarification",
    "repeat",
    "too_short",
    "skipped",
]

_CLARIFICATION_MARKERS = (
    "能再解释",
    "没听懂",
    "什么意思",
    "请重复",
    "再说一遍",
    "clarify",
    "repeat the question",
)


def _normalise_answer(answer: str) -> str:
    return " ".join((answer or "").strip().split())


def classify_answer_intent(
    answer: str,
    previous_answers: list[str] | None = None,
) -> AnswerIntent:
    """Return whether an answer should be treated as normal scoring input."""
    text = _normalise_answer(answer)
    if not text:
        return "empty"
    if text == "__skip_question__":
        return "skipped"

    lowered = text.lower()
    if any(marker in lowered or marker in text for marker in _CLARIFICATION_MARKERS):
        return "clarification"

    previous = [_normalise_answer(item) for item in (previous_answers or [])]
    if text in previous[-3:]:
        return "repeat"

    if len(text) < 12:
        return "too_short"

    return "normal"
