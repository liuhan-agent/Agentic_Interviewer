"""Policy context-key helpers for direction-scoped bandit learning."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ParsedPolicyContextKey:
    direction: str | None
    job_level: str
    dimension: str


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


def parse_policy_context_key(key: str | None) -> ParsedPolicyContextKey:
    """Parse keys produced by :func:`policy_context_keys`.

    Valid keys are either ``level:dimension`` or
    ``direction:level:dimension``. Unknown shapes fall back to the same
    neutral context used elsewhere in the policy layer.
    """

    parts = [part.strip() for part in str(key or "").split(":") if part.strip()]
    if len(parts) == 2:
        return ParsedPolicyContextKey(
            direction=None,
            job_level=parts[0] or "mid",
            dimension=parts[1] or "general",
        )
    if len(parts) == 3:
        return ParsedPolicyContextKey(
            direction=parts[0] or None,
            job_level=parts[1] or "mid",
            dimension=parts[2] or "general",
        )
    return ParsedPolicyContextKey(
        direction=None,
        job_level="mid",
        dimension="general",
    )
