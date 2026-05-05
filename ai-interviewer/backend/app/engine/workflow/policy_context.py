"""Policy context-key helpers for direction-scoped bandit learning."""
from __future__ import annotations

from typing import Any


def global_policy_context_key(job_level: str | None, dimension: str | None) -> str:
    return f"{job_level or 'mid'}:{dimension or 'general'}"


def policy_context_keys(
    job_spec: dict[str, Any] | None,
    dimension: str | None,
) -> list[str]:
    spec = job_spec or {}
    job_level = spec.get("level") or "mid"
    dim = dimension or "general"
    global_key = global_policy_context_key(job_level, dim)
    direction = spec.get("interview_direction") or spec.get("direction")
    keys: list[str] = []
    if direction:
        keys.append(f"{direction}:{global_key}")
    keys.append(global_key)

    deduped: list[str] = []
    seen: set[str] = set()
    for key in keys:
        if key not in seen:
            deduped.append(key)
            seen.add(key)
    return deduped
