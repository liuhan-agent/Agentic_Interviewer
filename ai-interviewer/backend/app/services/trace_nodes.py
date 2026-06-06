"""Trace node naming helpers.

The persisted workflow node id can outlive a UI/semantic rename. Keep
that compatibility rule in one place so Admin APIs, trace payloads, and
Trace Explorer do not grow separate hard-coded alias maps.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

TRACE_NODE_ALIASES: dict[str, str] = {
    "compress_context": "turn_finalize",
}

TRACE_NODE_DISPLAY_NAMES_ZH: dict[str, str] = {
    "resume_parse": "简历准备",
    "self_intro_question": "开场问题",
    "self_intro_parse": "开场解析",
    "turn_finalize": "轮次收尾",
}

TRACE_STATUS_SUMMARY_FIELDS = (
    "status",
    "source_type",
    "mode",
    "chunk_count",
    "cache_hit",
    "wait_timed_out",
    "wait_timeout_ms",
    "skipped_reason",
)

TRACE_NODE_REVERSE_ALIASES: dict[str, list[str]] = {}
for alias, canonical in TRACE_NODE_ALIASES.items():
    TRACE_NODE_REVERSE_ALIASES.setdefault(canonical, []).append(alias)


def normalize_trace_node(node: str | None) -> str:
    """Return the persisted workflow node id for a trace node or alias."""
    raw = str(node or "").strip()
    return TRACE_NODE_ALIASES.get(raw, raw)


def trace_node_aliases(node: str | None) -> list[str]:
    """Return semantic aliases for a persisted workflow node id."""
    canonical = normalize_trace_node(node)
    return list(TRACE_NODE_REVERSE_ALIASES.get(canonical, []))


def trace_node_display_name(node: str | None) -> str:
    """Return the Chinese operator-facing display name when one exists."""
    canonical = normalize_trace_node(node)
    return TRACE_NODE_DISPLAY_NAMES_ZH.get(canonical, canonical or "—")


def trace_node_semantic_name(node: str | None) -> str | None:
    """Return the preferred semantic name for a node, if defined."""
    canonical = normalize_trace_node(node)
    return canonical if canonical else None


def trace_node_metadata(node: str | None) -> dict[str, object]:
    """Compact metadata block safe to attach to trace payloads."""
    canonical = normalize_trace_node(node)
    aliases = trace_node_aliases(canonical)
    metadata: dict[str, object] = {
        "workflow_node": canonical,
        "node_aliases": aliases,
        "display_name_zh": trace_node_display_name(canonical),
    }
    semantic = trace_node_semantic_name(canonical)
    if semantic:
        metadata["semantic_node"] = semantic
    return metadata


def trace_status_summary(
    status: Mapping[str, Any] | None,
    *,
    presence_fields: tuple[str, ...] = (),
) -> dict[str, object]:
    """Return a bounded status snapshot safe for trace payloads."""
    if not isinstance(status, Mapping):
        return {"status": "unknown"}

    summary: dict[str, object] = {}
    for key in TRACE_STATUS_SUMMARY_FIELDS:
        value = status.get(key)
        if value is None:
            continue
        if isinstance(value, str | int | float | bool):
            summary[key] = value
    for key in presence_fields:
        summary[f"has_{key}"] = bool(status.get(key))
    return summary or {"status": "unknown"}
