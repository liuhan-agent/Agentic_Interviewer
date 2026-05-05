"""LLM-backed compliance guard.

Complements the cheap regex sweep in :mod:`app.engine.agents.security`.
Callers pick a ``guard_mode`` from ``runtime_config`` (or
``Settings.default_guard_mode``):

- ``regex_only`` — guard agent never runs; fastest and cheapest.
- ``hybrid``     — regex first; if regex is clean the agent is skipped,
  if regex flags anything we ask the agent for a second opinion +
  a principled ``redacted_text``.
- ``llm_only``   — every check goes through the agent regardless of
  what regex thinks.

The module never raises: any provider error degrades to a neutral
``GuardDecision(allowed=True, llm_available=False)`` so the graph
stays alive even when the guard LLM is down. The rule-based sweep is
always authoritative as a fallback.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

# ``get_settings`` / ``ChatMessage`` / ``render_prompt`` are re-exported
# for backwards compatibility: ``test_guard_equivalence.py`` patches
# ``guard.get_settings`` / ``guard.ChatMessage`` / ``guard.render_prompt``
# to pin the context-builder equivalence contract — both the legacy
# inline-prompt branch and the slot-based frame branch must emit
# byte-identical messages. Removing these aliases breaks the patch
# targets even though this module no longer calls the inline helpers
# directly.
from app.core.logging import get_logger
from app.core.settings import get_settings as get_settings
from app.engine.context import (
    build_context_frame_for_guard,
    frame_to_guard_messages,
)

from .llm_client import (
    ChatMessage as ChatMessage,
)
from .llm_client import (
    call_chat,
    parse_json_response,
)
from .prompts.loader import render_prompt as render_prompt

log = get_logger(__name__)


TargetKind = Literal["question", "answer"]

KNOWN_CATEGORIES = {
    "pii",
    "injection",
    "leading_question",
    "discrimination",
    "toxicity",
}


@dataclass
class GuardDecision:
    allowed: bool
    categories: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    redacted_text: str = ""
    llm_available: bool = True

    @classmethod
    def ok(cls) -> GuardDecision:
        return cls(allowed=True)

    @classmethod
    def degraded(cls, reason: str) -> GuardDecision:
        """Neutral fallback when the LLM is unavailable.

        The regex layer runs either way, so a degraded agent does not
        leave the system unguarded.
        """
        return cls(
            allowed=True,
            reasons=[reason],
            llm_available=False,
        )


def _coerce_categories(raw: object) -> list[str]:
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for item in raw:
        if isinstance(item, str) and item in KNOWN_CATEGORIES:
            out.append(item)
    return out


def _coerce_reasons(raw: object) -> list[str]:
    if not isinstance(raw, list):
        return []
    return [str(x) for x in raw if x]


def classify(text: str, *, target_kind: TargetKind) -> GuardDecision:
    """Ask the guard LLM to classify ``text`` for compliance issues.

    Returns :class:`GuardDecision` with ``llm_available=False`` on any
    provider failure so the caller can choose to fall back to the
    rule-based verdict. This function never raises.
    """
    if not text or not text.strip():
        return GuardDecision.ok()

    frame = build_context_frame_for_guard(
        target_kind=target_kind,
        text=text,
    )
    messages = frame_to_guard_messages(frame)
    try:
        raw = call_chat(
            messages,
            json_mode=True,
            agent_role="guard",
        )
        data = parse_json_response(raw)
    except Exception as e:  # pragma: no cover - provider flakes
        log.warning("guard_agent LLM call failed, degrading: %s", e)
        return GuardDecision.degraded(f"LLM error: {e}")

    if not isinstance(data, dict) or not data:
        return GuardDecision.degraded("guard_agent reply was not a JSON object")

    allowed = bool(data.get("allowed", True))
    categories = _coerce_categories(data.get("categories"))
    reasons = _coerce_reasons(data.get("reasons"))
    redacted = data.get("redacted_text") or ""
    if not isinstance(redacted, str):
        redacted = ""

    # Safety: if any category other than a clean PII mask shows up,
    # allowed must be false. Models sometimes return allowed=true
    # while also listing "injection" in categories; we trust the
    # categories over the flag to avoid false negatives.
    hard_blockers = {"injection", "discrimination", "toxicity", "leading_question"}
    if hard_blockers.intersection(categories):
        allowed = False

    return GuardDecision(
        allowed=allowed,
        categories=categories,
        reasons=reasons,
        redacted_text=redacted,
        llm_available=True,
    )
