"""Adversarial verification agent (three-Agent pattern).

The Evaluator already scored the answer against the signed
:class:`PlanContract`. The Verifier's job is NOT to re-score: it is
to *try to break* the evaluator's judgement. It reads the contract,
the answer, and the evaluator's evidence report, then either:

- confirms the verdict with ``verdict="pass"``;
- downgrades marginal passes to ``verdict="partial"`` with reasons;
- flips contentious passes to ``verdict="fail"`` when the answer
  doesn't actually hold up under scrutiny.

This is the Claude Code ``verification`` subagent pattern (see
``reference/claude-code/multi-agent-architecture.md`` §4.11.7):
keep the reviewer structurally independent from the grader, and
force it to adopt an adversarial stance rather than "looks fine".

Trigger policy lives in :func:`should_trigger`; by default we keep it
focused on suspicious passes: near-threshold scores, partial contract
checks, senior-level review, or evidence gaps on deep/high-risk turns.
"""
from __future__ import annotations

from typing import Any, Literal

from app.core.logging import get_logger
from app.core.settings import get_settings
from app.engine.context import (
    build_context_frame_for_verifier,
    frame_to_verifier_messages,
)

from .llm_client import call_chat, parse_json_response

log = get_logger(__name__)

VerifierVerdict = Literal["pass", "partial", "fail"]


def _verdict_of(value: Any) -> str:
    """Extract the verdict from either legacy string or canonical dict shape.

    ``evaluation.acceptance_check_results[*]`` was historically a flat
    ``"yes|partial|no"`` string; the evidence-spans upgrade switched it
    to ``{"verdict": ..., "evidence": [...]}``. Old DB snapshots may
    still carry the legacy shape, so the trigger policy has to cope
    with both.
    """
    if isinstance(value, dict):
        v = str(value.get("verdict", "")).strip().lower()
    else:
        v = str(value).strip().lower()
    return v if v in {"yes", "partial", "no"} else "no"


def _has_unsupported_yes(value: Any) -> bool:
    """True when the evaluator says "yes" but provides no evidence quote."""
    if not isinstance(value, dict) or _verdict_of(value) != "yes":
        return False
    evidence = value.get("evidence")
    if not isinstance(evidence, list):
        return True
    return not any(str(item).strip() for item in evidence)


def _default_verdict(evaluator_report: dict[str, Any]) -> dict[str, Any]:
    """Degrade-path verdict used when the LLM call fails.

    We trust the evaluator one time, but tag ``confidence=0.0`` so
    the audit trail shows no independent verification happened.
    """
    return {
        "verdict": "pass" if evaluator_report.get("passed") else "fail",
        "reasons_to_doubt": [],
        "would_ask_next": "",
        "confidence": 0.0,
        "rationale": "Verifier unavailable; evaluator verdict passed through.",
        "verifier_available": False,
    }


def verify_answer(
    *,
    dimension: str,
    question: str,
    answer: str,
    contract: dict[str, Any],
    evaluator_report: dict[str, Any],
) -> dict[str, Any]:
    """Run the verifier and return a structured verdict.

    Never raises: LLM failures degrade to ``_default_verdict`` so the
    graph keeps flowing.
    """
    frame = build_context_frame_for_verifier(
        dimension=dimension,
        question=question,
        answer=answer,
        contract=contract or {},
        evaluator_report=evaluator_report or {},
    )
    messages = frame_to_verifier_messages(frame)
    try:
        raw = call_chat(messages, json_mode=True, agent_role="verifier")
        data = parse_json_response(raw)
    except Exception as e:  # pragma: no cover
        log.warning("verifier call failed, degrading: %s", e)
        return _default_verdict(evaluator_report)

    if not isinstance(data, dict) or not data:
        return _default_verdict(evaluator_report)

    verdict_raw = str(data.get("verdict", "")).lower().strip()
    verdict: VerifierVerdict
    if verdict_raw in {"pass", "partial", "fail"}:
        verdict = verdict_raw  # type: ignore[assignment]
    else:
        verdict = "partial" if evaluator_report.get("passed") else "fail"

    reasons = data.get("reasons_to_doubt")
    if not isinstance(reasons, list):
        reasons = []

    try:
        confidence = float(data.get("confidence", 0.6))
    except (TypeError, ValueError):
        confidence = 0.6
    confidence = max(0.0, min(1.0, confidence))

    return {
        "verdict": verdict,
        "reasons_to_doubt": [str(r) for r in reasons if r],
        "would_ask_next": str(data.get("would_ask_next") or ""),
        "confidence": confidence,
        "rationale": str(data.get("rationale") or ""),
        "verifier_available": True,
    }


def _base_should_trigger(
    *,
    evaluation: dict[str, Any],
    contract: dict[str, Any] | None,
    quality_threshold: float,
    job_level: str,
    dimension: str,
    settings: Any,
) -> bool:
    """Pure rule-based trigger decision used as the baseline.

    Separated out so the adaptive feedback layer can compose over it
    without duplicating the rule list. ``passed=False`` short-circuits
    are handled by the outer ``should_trigger`` so this helper only
    covers the True-positive gates.
    """
    try:
        score = float(evaluation.get("score", 0.0))
    except (TypeError, ValueError):
        score = 0.0

    margin = float(settings.verifier_margin)
    if score <= quality_threshold + margin:
        return True

    acceptance = evaluation.get("acceptance_check_results") or {}
    if isinstance(acceptance, dict):
        values = list(acceptance.values())
        if any(_verdict_of(v) == "partial" for v in values):
            return True

        high_risk_turn = (contract or {}).get("bar_level") == "deep_probe" or (
            dimension in set(settings.verifier_dimensions_bluff_prone or [])
        )
        if high_risk_turn and any(_has_unsupported_yes(v) for v in values):
            return True

    if settings.verifier_senior_always and job_level == "senior":
        return True

    return False


def _adaptive_trigger_override(
    *,
    dimension: str,
    evaluation: dict[str, Any],
    quality_threshold: float,
    settings: Any,
) -> bool | None:
    """Return ``True`` / ``False`` / ``None`` depending on drift.

    ``None`` means "adaptive gate is not engaged" (disabled, no drift
    monitor, drift monitor empty, or dimension hasn't accumulated
    enough calls to be statistically meaningful yet). The caller
    uses the baseline rules in that case.

    ``True`` force-triggers even when baseline rules would skip.
    This is the "high-drift dimension deserves extra scrutiny" path:
    the verifier has historically overruled this dimension's
    evaluator verdicts at a rate above ``verifier_adaptive_high_
    threshold``, so we want to keep catching those bluffs until the
    rate subsides (and/or prompts / models improve).

    ``False`` force-skips even when baseline rules would fire. This
    is the "low-drift dimension has earned trust" path: the verifier
    rarely disagrees with the evaluator here, so for *clean*
    passes (score comfortably above threshold) we can pocket the
    LLM call. We never return ``False`` for marginal passes because
    the margin is exactly where verifier signal is most valuable.
    """
    if not getattr(settings, "verifier_adaptive_trigger", False):
        return None
    if not getattr(settings, "enable_verifier_drift_monitor", False):
        return None

    try:  # Lazy import so the verifier module has no build-time
        # dependency on the drift package (and so a monitor import
        # failure cannot ever take the graph down).
        from app.ml.drift.verifier_drift import get_verifier_drift_monitor

        snapshot = get_verifier_drift_monitor().snapshot()
    except Exception as e:  # pragma: no cover - observation-only path
        log.debug("adaptive verifier trigger skipped (drift snapshot failed): %s", e)
        return None

    if snapshot.get("backend_unavailable"):
        log.debug("adaptive verifier trigger skipped (drift backend unavailable)")
        return None

    per_dim = (snapshot.get("per_dimension") or {}).get(dimension) or {}
    try:
        calls = int(per_dim.get("calls", 0))
    except (TypeError, ValueError):
        calls = 0

    min_samples = int(getattr(settings, "verifier_adaptive_min_samples", 30))
    if calls < min_samples:
        return None

    try:
        override_rate = float(per_dim.get("override_rate", 0.0))
    except (TypeError, ValueError):
        override_rate = 0.0

    high = float(getattr(settings, "verifier_adaptive_high_threshold", 0.25))
    low = float(getattr(settings, "verifier_adaptive_low_threshold", 0.05))

    if override_rate >= high:
        return True

    if override_rate <= low:
        # Only skip on a comfortably-clean pass; marginal passes
        # still need the verifier regardless of historical drift.
        try:
            score = float(evaluation.get("score", 0.0))
        except (TypeError, ValueError):
            score = 0.0
        margin = float(getattr(settings, "verifier_margin", 1.0))
        if score > quality_threshold + margin:
            return False
        return None

    return None


def should_trigger(
    *,
    evaluation: dict[str, Any],
    contract: dict[str, Any] | None,
    quality_threshold: float,
    job_level: str,
    dimension: str,
) -> bool:
    """Decide whether to invoke the verifier on this turn.

    Two layers of decision:

    1. **Baseline rules** (:func:`_base_should_trigger`):

       - marginal pass: score no more than ``settings.verifier_margin``
         above ``quality_threshold`` (the most likely false positive);
       - ``job_level == "senior"`` AND
         ``settings.verifier_senior_always``;
       - ``acceptance_check_results`` contains a ``partial`` despite
         ``passed=True`` (contract inconsistency);
       - deep-probe or bluff-prone turns where an acceptance check is
         marked ``yes`` without any supporting evidence quote.

    2. **Adaptive feedback** (:func:`_adaptive_trigger_override`):
       uses the :mod:`app.ml.drift.verifier_drift` rolling-window
       ``override_rate`` per dimension to dial the trigger rate up
       (high drift) or down (low drift + clean pass). Opt-in via
       ``settings.verifier_adaptive_trigger``; requires the drift
       monitor to be on and at least
       ``settings.verifier_adaptive_min_samples`` calls in the
       dimension's window.

    Verification runs are skipped for outright failures and clean
    passes to keep LLM cost bounded, unless the adaptive layer
    explicitly flips that decision.
    """
    if not evaluation:
        return False

    passed = bool(evaluation.get("passed"))
    if not passed:
        return False

    s = get_settings()

    base = _base_should_trigger(
        evaluation=evaluation,
        contract=contract,
        quality_threshold=quality_threshold,
        job_level=job_level,
        dimension=dimension,
        settings=s,
    )

    override = _adaptive_trigger_override(
        dimension=dimension,
        evaluation=evaluation,
        quality_threshold=quality_threshold,
        settings=s,
    )
    if override is None:
        return base
    return override
