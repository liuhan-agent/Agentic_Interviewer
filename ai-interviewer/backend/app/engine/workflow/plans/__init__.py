"""In-node execution plans for the ``ask_question`` node.

P0 scope: three hand-written templates (``simple``, ``adaptive``,
``deep_probe``) plus a resolver that maps ``(selected_action,
refine_mode, pending_plan_template, runtime_config)`` to a concrete
plan object. The LLM-powered planner variant is out of scope in P0
and kept behind ``runtime_config.ask_planning`` for later.
"""

from .ask_plans import (
    PLAN_TEMPLATES,
    build_default_plan,
    resolve_ask_plan,
)
from .llm_planner import build_llm_ask_plan

__all__ = [
    "PLAN_TEMPLATES",
    "build_default_plan",
    "resolve_ask_plan",
    "build_llm_ask_plan",
]
