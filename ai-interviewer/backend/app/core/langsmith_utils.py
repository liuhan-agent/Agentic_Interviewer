"""LangSmith ``RunnableConfig`` helpers.

Purpose
-------
When the graph is invoked via ``workflow.stream(input, config=config)``,
LangChain / LangGraph forward any ``metadata`` / ``tags`` / ``run_name``
keys on that config into the LangSmith callback pipeline, which attaches
them to every span of the run tree. Without this, the LangSmith UI only
shows the node name - operators cannot filter by
``session_id`` / ``job_level`` / ``dimension`` when a specific interview
misbehaves.

This module centralises the conversion from "business state" (session
+ candidate + job spec) to that ``config`` slice so both the API /
WebSocket path (``session_manager``) and the CLI demo
(``scripts/run_demo``) agree on the same shape. The alternative -
sprinkling ``"metadata": {...}`` dicts across callers - tends to drift.

PII policy
----------
``candidate_name`` is deliberately **never** forwarded as plain text.
We hash the name via SHA-256 and keep only the first 12 hex chars; the
resulting ``candidate_hash`` is stable across invocations (so an ops
engineer can link multiple interviews for the same candidate) but
cannot be reversed even by a LangSmith admin. Empty / missing names
collapse to ``None`` so the LangSmith UI displays a blank value rather
than a synthetic hash of the empty string.

Zero-overhead when tracing is off
---------------------------------
When ``langsmith_tracing=False``, :func:`build_langsmith_config`
returns an empty dict. The caller merges it into its existing
``_graph_config`` so the hot path is byte-identical to the
pre-rollout shape.
"""
from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Any

__all__ = [
    "candidate_hash",
    "build_langsmith_config",
]


_HASH_PREFIX_LEN = 12  # ~48 bits; collision-safe across interview volumes.


def candidate_hash(name: str | None) -> str | None:
    """Stable, irreversible candidate identifier for LangSmith metadata.

    Returns ``None`` when ``name`` is falsy / whitespace-only so the
    metadata key can be dropped entirely rather than sending a
    hash-of-empty-string to the LangSmith UI.

    The hash is SHA-256-based, truncated to 12 hex chars. We do not
    attach a salt: the goal is pseudonymisation (two interviews for
    the same candidate should be linkable), not cryptographic privacy
    against a brute-force attacker. When that stronger guarantee is
    needed, add a ``LANGSMITH_HASH_SALT`` setting and HMAC here.
    """
    if not name:
        return None
    cleaned = name.strip()
    if not cleaned:
        return None
    digest = hashlib.sha256(cleaned.encode("utf-8")).hexdigest()
    return digest[:_HASH_PREFIX_LEN]


def build_langsmith_config(
    *,
    tracing_enabled: bool,
    session_id: str,
    trace_id: str,
    app_env: str,
    candidate_name: str | None = None,
    job_level: str | None = None,
    job_title: str | None = None,
    mode: str | None = None,
    turn_idx: int | None = None,
    extra_tags: list[str] | None = None,
    extra_metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the LangSmith-related slice of a LangGraph ``RunnableConfig``.

    Returns an empty dict when ``tracing_enabled`` is False so callers
    can unconditionally ``config.update(build_langsmith_config(...))``
    without branching on the tracing flag. When tracing is enabled,
    returns a dict with (some of) these keys set:

    - ``metadata``: dict of business fields attached to every span.
      Candidate identity is only present as ``candidate_hash`` — never
      as raw text (see module docstring).
    - ``tags``: flat list of string tags. Used for LangSmith's tag
      filter UI. We emit ``env:<env>`` / ``level:<job_level>`` /
      ``mode:<mode>`` so the most common drill-downs are one click
      away.
    - ``run_name``: short human-readable name shown in the run tree.
      Format ``interview.<sess8>.turn<n>`` so ops can eyeball the
      session from the run list without expanding spans.

    The caller is expected to merge this dict into its existing
    graph config, e.g.::

        cfg = {"configurable": {"thread_id": session_id}, "recursion_limit": 120}
        cfg.update(build_langsmith_config(tracing_enabled=s.langsmith_tracing, ...))

    Values that are ``None`` / empty are deliberately omitted from
    ``metadata`` so the LangSmith filter UI does not render empty
    columns. ``turn_idx`` similarly defaults the ``run_name`` suffix
    to ``"turn?"`` when unknown, so the session-id prefix remains
    legible.
    """
    if not tracing_enabled:
        return {}

    metadata: dict[str, Any] = {
        "session_id": session_id,
        "trace_id": trace_id,
        "app_env": app_env,
    }

    hashed = candidate_hash(candidate_name)
    if hashed is not None:
        metadata["candidate_hash"] = hashed
    if job_level:
        metadata["job_level"] = job_level
    if job_title:
        metadata["job_title"] = job_title
    if mode:
        metadata["mode"] = mode
    if turn_idx is not None:
        metadata["turn_idx"] = int(turn_idx)
    if extra_metadata:
        for k, v in extra_metadata.items():
            if v is None:
                continue
            metadata.setdefault(k, v)

    tags: list[str] = [f"env:{app_env or 'dev'}"]
    if job_level:
        tags.append(f"level:{job_level}")
    if mode:
        tags.append(f"mode:{mode}")
    if extra_tags:
        for t in extra_tags:
            if t and t not in tags:
                tags.append(t)

    sess_prefix = (session_id or "")[:8] or "nosess"
    turn_part = f"turn{turn_idx}" if turn_idx is not None else "turn?"
    run_name = f"interview.{sess_prefix}.{turn_part}"

    return {
        "metadata": metadata,
        "tags": tags,
        "run_name": run_name,
    }
