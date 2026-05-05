"""Drift → prompt feedback renderers.

Reads the ``overruled_patterns`` aggregate exposed by
:class:`VerifierDriftMonitor.snapshot` and renders **two** Markdown
blocks from the same data source:

- :func:`build_evaluator_drift_negatives` — splices into the
  Evaluator's ``dynamic_system`` context layer so it grades the
  *current* answer while seeing "prior shallow evidence that got
  overruled". Documented in ``PLAN_DRIFT_FEEDBACK.md``.
- :func:`build_generator_avoid_patterns` — splices into the
  Generator's ``avoid_patterns`` payload slot so it drafts the
  *next* question while seeing "shallow evidence shapes to design
  questions *away* from". Documented in
  ``PLAN_DRIFT_RAG_FEEDBACK.md``.

Same ``overruled_patterns`` → two renderers → two agent-side slots.
Neither function makes an LLM call; both fall back to empty string
when there is nothing meeting ``min_support`` to say.

Design constraints
------------------
- **Pure aggregation**: no LLM calls, no network I/O.
- **Caller-agnostic**: returning an empty string when there is
  nothing to say means the caller can unconditionally forward the
  result to
  :func:`app.engine.context.builder.build_context_frame_for_evaluator`
  /
  :func:`app.engine.context.builder.build_context_frame_for_generator`;
  an empty value collapses back to the pre-feedback prompt shape.
- **Bounded token footprint**: hard caps on top-N, per-pattern
  evidence count, and per-quote character length keep each rendered
  block ≤ ~600 chars even when the window holds dozens of drift
  events.
"""
from __future__ import annotations

from typing import Any

from app.ml.drift.verifier_drift import get_verifier_drift_monitor

__all__ = [
    "build_evaluator_drift_negatives",
    "build_generator_avoid_patterns",
]


_MAX_QUOTE_CHARS = 80
_MAX_REASON_CHARS = 120


def _truncate(text: str, cap: int) -> str:
    """Bound a single quote / reason so a single pathological event
    cannot inflate the rendered block past the agreed ceiling.
    """
    text = text.strip().replace("\n", " ")
    if len(text) <= cap:
        return text
    return text[: cap - 1].rstrip() + "…"


def _render_pattern_line(pattern: dict[str, Any]) -> str:
    """Render one ``{dimension, check, count, sample_evidence,
    reasons_sample}`` bucket as a single bullet line."""
    dim = pattern.get("dimension", "unknown")
    check = pattern.get("check", "unknown")
    count = int(pattern.get("count", 0))

    evidence = [
        f"`\"{_truncate(q, _MAX_QUOTE_CHARS)}\"`"
        for q in (pattern.get("sample_evidence") or [])[:3]
    ]
    reasons = [
        f"\"{_truncate(r, _MAX_REASON_CHARS)}\""
        for r in (pattern.get("reasons_sample") or [])[:3]
    ]

    parts: list[str] = [
        f"- On dimension `{dim}`, the check \"{check}\" was marked \"yes\" "
        f"{count} time(s)"
    ]
    if evidence:
        parts.append("based on evidence like " + ", ".join(evidence))
    if reasons:
        parts.append(
            "the Verifier downgraded with reasons: " + "; ".join(reasons)
        )
    return "; ".join(parts) + "."


def build_evaluator_drift_negatives(
    *,
    dimension: str | None = None,
    top_n: int = 3,
    min_support: int = 2,
) -> str:
    """Render a Markdown negative-examples block for the Evaluator.

    The caller typically passes the current ``dimension`` to focus the
    feedback on the axis the evaluator is about to grade on; passing
    ``None`` surfaces patterns from every dimension.

    Parameters
    ----------
    dimension
        When set, filter patterns to this dimension only. ``None``
        returns patterns across all dimensions.
    top_n
        Maximum number of pattern bullets in the output. Must be >= 1.
    min_support
        Minimum per-pattern ``count`` required to surface a bullet.
        Defaults to 2 so a one-off false positive does not permanently
        poison the evaluator prompt.

    Returns
    -------
    str
        A Markdown block starting with
        ``"## Prior Evaluator Drift (negative examples)"`` when at
        least one pattern meets the thresholds, or the empty string
        when there is nothing to show. An empty return value is the
        signal the Evaluator builder uses to collapse the dynamic
        system layer back to the pre-feedback shape.
    """
    if top_n < 1:
        return ""

    snap = get_verifier_drift_monitor().snapshot()
    patterns = snap.get("overruled_patterns") or []
    if not isinstance(patterns, list):
        return ""

    filtered: list[dict[str, Any]] = []
    for p in patterns:
        if not isinstance(p, dict):
            continue
        try:
            count = int(p.get("count", 0))
        except (TypeError, ValueError):
            continue
        if count < min_support:
            continue
        if dimension is not None and p.get("dimension") != dimension:
            continue
        filtered.append(p)
        if len(filtered) >= top_n:
            break

    if not filtered:
        return ""

    lines = [
        "## Prior Evaluator Drift (negative examples)",
        "",
        "The Verifier has recently overruled evaluator \"pass\" calls on",
        "similar answers. When grading the current answer, treat these",
        "as cautionary patterns — do NOT repeat the same call if the",
        "current answer exhibits the same shallow evidence:",
        "",
    ]
    lines.extend(_render_pattern_line(p) for p in filtered)
    return "\n".join(lines)


def _render_avoid_pattern_line(pattern: dict[str, Any]) -> str:
    """Render one overruled-pattern bucket as a Generator-facing bullet.

    Shaped differently from :func:`_render_pattern_line`:

    - The Evaluator renderer says "similar evidence got overruled, grade
      stricter".
    - This one says "design the next question so the evidence below
      CANNOT satisfy it" — the framing is about question authoring, not
      answer grading.
    """
    check = pattern.get("check", "unknown")
    count = int(pattern.get("count", 0))
    evidence = [
        f"`\"{_truncate(q, _MAX_QUOTE_CHARS)}\"`"
        for q in (pattern.get("sample_evidence") or [])[:3]
    ]

    parts: list[str] = [
        f"- Check \"{check}\" was gamed {count} time(s)"
    ]
    if evidence:
        parts.append("with evidence like " + ", ".join(evidence))
    parts.append(
        "— reframe the question so these quotes ALONE cannot satisfy it"
    )
    return "; ".join(parts) + "."


def build_generator_avoid_patterns(
    *,
    dimension: str | None = None,
    top_n: int = 3,
    min_support: int = 2,
) -> str:
    """Render a Markdown block for the Generator's ``avoid_patterns`` slot.

    Companion to :func:`build_evaluator_drift_negatives`. Both read the
    same ``overruled_patterns`` snapshot but render them into different
    agent-facing messages:

    - Evaluator gets "grade stricter, these evidence shapes got
      overruled last time they earned a yes".
    - Generator gets "design questions so these evidence shapes ALONE
      cannot satisfy them" — the framing is question authoring, not
      answer grading.

    Parameters mirror the Evaluator helper exactly so the callers can
    share ``drift_feedback_top_n`` / ``drift_feedback_min_support``
    settings.

    Returns
    -------
    str
        A Markdown block starting with
        ``"## Avoid Patterns (historical verifier signal)"`` when at
        least one pattern meets the thresholds, or the empty string
        when there is nothing to show. The caller forwards that
        empty string into the Generator builder; the builder then
        uses its default placeholder so the prompt stays shape-stable.
    """
    if top_n < 1:
        return ""

    snap = get_verifier_drift_monitor().snapshot()
    patterns = snap.get("overruled_patterns") or []
    if not isinstance(patterns, list):
        return ""

    filtered: list[dict[str, Any]] = []
    for p in patterns:
        if not isinstance(p, dict):
            continue
        try:
            count = int(p.get("count", 0))
        except (TypeError, ValueError):
            continue
        if count < min_support:
            continue
        if dimension is not None and p.get("dimension") != dimension:
            continue
        filtered.append(p)
        if len(filtered) >= top_n:
            break

    if not filtered:
        return ""

    dim_text = (
        f"dimension `{dimension}`" if dimension else "recent dimensions"
    )
    lines = [
        "## Avoid Patterns (historical verifier signal)",
        "",
        f"Prior evaluator \"pass\" verdicts on {dim_text} were later",
        "overruled by the Verifier because the answer relied on shallow",
        "framings. When drafting THIS question, design it so the",
        "quotes below can NOT satisfy the acceptance checks on their",
        "own:",
        "",
    ]
    lines.extend(_render_avoid_pattern_line(p) for p in filtered)
    return "\n".join(lines)
