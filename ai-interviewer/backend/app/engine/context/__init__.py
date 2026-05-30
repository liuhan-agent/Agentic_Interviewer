"""Slot-based context assembly for LLM agents.

Phase 2 complete (legacy downsize). See
``reference/topics/context-engineering.md`` for the design intent:
layered context (static / dynamic / per-turn) replaces ad-hoc
prompt string concatenation inside individual agents.

Every agent in the interview workflow now goes through this package
unconditionally — the ``use_context_builder`` feature flag and the
inline ``ChatMessage(...) + render_prompt(...)`` legacy branches
that each agent carried during Phase 0/0.5/1 have been removed.
Callers import the relevant ``build_context_frame_for_<role>`` /
``frame_to_<role>_messages`` pair and the runtime behaviour is
deterministic.

Roles covered:

- Generator / Evaluator (established in Phase 0/0.5)
- Verifier / Guard / Contract-Negotiator / Session-Summarizer /
  Coach (migrated in Phase 1, legacy branches removed in Phase 2;
  see ``backend/docs/PLAN_CONTEXT_BUILDER_PHASE1.md``)

Public API
----------
- :class:`ContextFrame` - typed data class holding all slots.
- ``build_context_frame_for_<role>`` - pure builders per role; each
  mirrors the matching agent-function kwargs 1:1.
- ``frame_to_<role>_messages`` - renderers producing the exact
  ``list[ChatMessage]`` that ``call_chat`` expects.
"""
from __future__ import annotations

from .builder import (
    build_context_frame_for_coach,
    build_context_frame_for_contract_negotiator,
    build_context_frame_for_evaluator,
    build_context_frame_for_generator,
    build_context_frame_for_guard,
    build_context_frame_for_session_summarizer,
    build_context_frame_for_verifier,
)
from .frame import AgentRole, ContextFrame
from .history_context import build_history_context
from .renderer import (
    frame_to_coach_messages,
    frame_to_contract_negotiator_messages,
    frame_to_evaluator_messages,
    frame_to_generator_messages,
    frame_to_guard_messages,
    frame_to_session_summarizer_messages,
    frame_to_verifier_messages,
)

__all__ = [
    "AgentRole",
    "ContextFrame",
    "build_context_frame_for_generator",
    "build_context_frame_for_evaluator",
    "build_context_frame_for_verifier",
    "build_context_frame_for_guard",
    "build_context_frame_for_contract_negotiator",
    "build_context_frame_for_session_summarizer",
    "build_context_frame_for_coach",
    "build_history_context",
    "frame_to_generator_messages",
    "frame_to_evaluator_messages",
    "frame_to_verifier_messages",
    "frame_to_guard_messages",
    "frame_to_contract_negotiator_messages",
    "frame_to_session_summarizer_messages",
    "frame_to_coach_messages",
]
