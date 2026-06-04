"""Typed data class that carries all context slots for one agent call.

The design intent is to treat a single LLM prompt as a **layered
composition**, not a free-form string. Three stable layers plus a
per-turn ``payload`` cover every agent role we currently have:

1. ``static_system`` - hot prefix shared across a whole session (e.g.
   ``system_skeleton.md``). This is what Anthropic prompt cache hits
   on; OpenAI caches it automatically.
2. ``dynamic_system`` - session-scoped additions (e.g. the strategy
   index). Stable across turns but differs per session.
3. ``payload`` - per-turn variables that populate the user-message
   template (e.g. ``dimension``, ``retrieval``, ``history_section``).

Why a free-form ``payload`` dict rather than typed per-role dataclasses?
Phase 0 wires only the Generator role so the payload keys are driven by
``generator_task.md``'s frontmatter. Follow-up PRs (Evaluator, Verifier,
Guard) will add role-specific TypedDicts behind the same ``ContextFrame``
shell without a breaking change.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Literal

AgentRole = Literal[
    "generator",
    "evaluator",
    "verifier",
    "guard",
    "contract_negotiator",
    "session_summarizer",
]


@dataclass
class ContextFrame:
    """Slotted context bundle handed to a renderer.

    Instances are immutable-by-convention (not ``frozen=True`` to keep
    builder ergonomics simple). Renderers should treat the frame as
    read-only.

    ``cache_static`` controls whether the renderer attaches Anthropic's
    ``cache_control: {"type":"ephemeral"}`` marker to the static system
    block. Generator and Evaluator share the long ``system_skeleton.md``
    prefix so caching wins; the other five roles (Verifier / Guard /
    Contract-Negotiator / Session-Summarizer / Coach) have short,
    role-specific system strings where caching would be either
    negligible (~few hundred tokens) or actively harmful (cache key
    fragmentation across many roles). Default ``True`` preserves the
    pre-Phase-1 behaviour for Generator + Evaluator builders; the
    Phase-1 builders opt out by passing ``cache_static=False``.
    """

    agent_role: AgentRole
    turn_idx: int
    static_system: str = ""
    dynamic_system: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    cache_static: bool = True

    @property
    def system_text(self) -> str:
        """Join the two system layers the way legacy code does.

        The concatenator is ``"\\n\\n"`` which matches the current
        generator behaviour (``system_skeleton + "\\n\\n" + strategy_index``)
        bit-for-bit. An empty dynamic layer collapses to the static
        prefix, again matching legacy.
        """
        if self.dynamic_system:
            return f"{self.static_system}\n\n{self.dynamic_system}"
        return self.static_system

    def cache_key(self) -> str:
        """Stable short hash over the static + dynamic layers.

        Not consumed in Phase 0. Surfaced now so the future prompt-cache
        plumbing (PR-2) can key Anthropic ``cache_control`` writes on a
        deterministic id rather than raw string comparisons.
        """
        material = f"{self.agent_role}|{self.static_system}|{self.dynamic_system}"
        return hashlib.sha1(material.encode("utf-8")).hexdigest()[:12]
