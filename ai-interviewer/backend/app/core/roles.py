"""Canonical LLM agent role identifiers.

Single source of truth for all role strings used in call_chat routing,
per-agent model overrides, and BYOK role_overrides. Consumers should
import from here instead of maintaining parallel Literal definitions.

Recognised roles (keep in sync with settings.py llm_model_per_agent
comment and frontend llm-config.ts LLMRoleKey):
"""
from __future__ import annotations

from typing import Literal, get_args

AgentRole = Literal[
    "generator",
    "evaluator",
    "verifier",
    "guard",
    "contract_negotiator",
    "rubric_negotiator",
    "session_summarizer",
    "coach",
    "llm_planner",
    "strategy_dream",
    "memory_selector",
    "resume_parser",
    "jd_parser",
    "self_intro_parser",
]

ALL_AGENT_ROLES: frozenset[str] = frozenset(get_args(AgentRole))

# Subset exposed to frontend BYOK configuration via the API.
# strategy_dream and memory_selector are backend-internal roles
# not configurable through the user-facing LLM settings dialog.
ApiExposedRole = Literal[
    "generator",
    "llm_planner",
    "rubric_negotiator",
    "contract_negotiator",
    "memory_selector",
    "evaluator",
    "verifier",
    "coach",
    "session_summarizer",
    "guard",
    "resume_parser",
    "jd_parser",
    "self_intro_parser",
]

ALL_API_EXPOSED_ROLES: frozenset[str] = frozenset(get_args(ApiExposedRole))
