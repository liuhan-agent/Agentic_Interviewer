"""Verification node: adversarial review of the evaluator verdict.

Sits between ``evaluator`` and ``route_after_eval``. When
:func:`app.engine.agents.verification.should_trigger` says we should
double-check, the verifier runs and may amend
``state.evaluation.passed`` / ``recommended_next`` /
``recommended_next_plan`` so the downstream router and
``refine_followup_node`` see the post-verification decision.

Writes a side-channel payload on ``state.verification`` so audits
and future training-set builders can recover "evaluator said X,
verifier said Y, final was Z".

Abstain path
------------
A low-confidence verifier verdict should not single-handedly flip
the evaluator's decision: the interview experience becomes jittery
and the bandit reward signal gets noisy. When
``verdict in {partial, fail}`` but ``confidence <
MIN_OVERRIDE_CONFIDENCE``, the node keeps ``passed`` as evaluated
and instead records the reasons as ``evaluation.soft_warnings``.
``refine_followup_node`` propagates those warnings into the next
round's ``pending_contract_hints.prior_soft_warnings`` so the
upcoming contract explicitly re-asks the shaky points. This is the
"verify without overruling" pattern.
"""
from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any

from app.core.logging import get_logger
from app.core.settings import get_settings
from app.core.tracer import get_tracer
from app.engine.agents.verification import should_trigger, verify_answer
from app.engine.workflow.evaluation_consistency import (
    normalize_evaluation_consistency,
    sync_dimension_status,
)
from app.engine.workflow.state import InterviewState

from .wait_answer import get_raw_answer_for_state

log = get_logger(__name__)


def _min_override_confidence() -> float:
    """Read the abstain-floor from settings (audit P3).

    Wrapped in a function so monkeypatching settings in tests just
    works; the previous module-level constant ``MIN_OVERRIDE_CONFIDENCE``
    snapshotted the value at import time and made tuning awkward.
    """
    try:
        return float(get_settings().verifier_min_override_confidence)
    except Exception:
        return 0.55


def _count_span_misses(evaluation: dict[str, Any]) -> tuple[int, int]:
    """Return ``(miss_count, total)`` across all acceptance checks.

    Reads ``evaluation.acceptance_check_results[*].evidence_spans``
    which is only populated when
    :attr:`Settings.evidence_span_alignment` is ON (see
    ``docs/PLAN_EVIDENCE_SPAN_ALIGNMENT.md``). When spans are absent,
    both counts come back as 0 and the drift monitor treats the
    ``0 / 0`` case as a zero ``span_miss_rate``.
    """
    miss = 0
    total = 0
    checks = evaluation.get("acceptance_check_results") or {}
    if not isinstance(checks, dict):
        return 0, 0
    for v in checks.values():
        if not isinstance(v, dict):
            continue
        spans = v.get("evidence_spans")
        if not isinstance(spans, list):
            continue
        for span in spans:
            if not isinstance(span, dict):
                continue
            total += 1
            if span.get("match") == "none":
                miss += 1
    return miss, total


def _pick_overruled_check(
    evaluation: dict[str, Any],
) -> tuple[str | None, tuple[str, ...]]:
    """Pick a single representative acceptance_check for an overruled event.

    Heuristic: find the ``verdict == "yes"`` check whose evidence list is
    the longest, and return ``(check_name, tuple(evidence_quotes))``. When
    the evaluator returned no "yes" checks we fall back to the first
    ``"partial"`` check with evidence; failing that we return
    ``(None, ())`` and the drift monitor drops the pattern-level signal
    (the top-level override count still increments).

    Rationale: the verifier overruled this turn, which means at least
    one acceptance_check the evaluator passed is shaky. Choosing the
    "yes" check with the most evidence captures the mistake the
    evaluator was most confident about — the same "confident mistake"
    that's most useful as a future cautionary example for the prompt
    feedback pipeline.
    """
    checks = evaluation.get("acceptance_check_results") or {}
    if not isinstance(checks, dict):
        return None, ()

    best_yes: tuple[str, list[str]] | None = None
    best_partial: tuple[str, list[str]] | None = None

    for name, raw in checks.items():
        if not isinstance(name, str) or not isinstance(raw, dict):
            continue
        verdict = str(raw.get("verdict", "")).strip().lower()
        evidence_raw = raw.get("evidence") or []
        if not isinstance(evidence_raw, list):
            evidence_raw = []
        evidence = [str(e) for e in evidence_raw if e]

        if verdict == "yes":
            if best_yes is None or len(evidence) > len(best_yes[1]):
                best_yes = (name, evidence)
        elif verdict == "partial" and best_partial is None and evidence:
            best_partial = (name, evidence)

    chosen = best_yes or best_partial
    if chosen is None:
        return None, ()
    return chosen[0], tuple(chosen[1])


def _record_drift_event(
    *,
    evaluation: dict[str, Any],
    updated_evaluation: dict[str, Any],
    verification: dict[str, Any],
    dimension: str,
    job_level: str,
) -> None:
    """Push one :class:`DriftEvent` into the rolling monitor.

    Wraps the record call so the caller can ``try/except`` around a
    single line: the monitor is observation-only and must never
    propagate an error into the workflow.
    """
    from app.ml.drift.verifier_drift import (
        DriftEvent,
        get_verifier_drift_monitor,
    )

    miss, total = _count_span_misses(evaluation)
    verifier_verdict = str(verification.get("verdict", "pass")).lower()
    if verifier_verdict not in {"pass", "partial", "fail"}:
        verifier_verdict = "fail"
    try:
        confidence = float(verification.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0

    evaluator_passed = bool(evaluation.get("passed"))
    final_passed = bool(updated_evaluation.get("passed"))
    overruled = evaluator_passed and not final_passed
    abstained = bool(updated_evaluation.get("verifier_abstained"))

    # PLAN_DRIFT_FEEDBACK pattern signal: only extract the
    # representative check when this turn was actually overruled.
    # Non-overruled events carry no pattern material the feedback
    # pipeline could use, so leaving the fields as their defaults
    # keeps the ``overruled_patterns`` aggregation clean.
    overruled_check_name: str | None = None
    evaluator_evidence_quotes: tuple[str, ...] = ()
    if overruled:
        overruled_check_name, evaluator_evidence_quotes = (
            _pick_overruled_check(evaluation)
        )

    verifier_reasons_raw = verification.get("reasons_to_doubt") or []
    if not isinstance(verifier_reasons_raw, list):
        verifier_reasons_raw = []
    verifier_reasons: tuple[str, ...] = tuple(
        str(r) for r in verifier_reasons_raw[:5] if r
    )

    event = DriftEvent(
        dimension=str(dimension or "unknown"),
        job_level=str(job_level or "mid"),
        evaluator_passed=evaluator_passed,
        verifier_verdict=verifier_verdict,  # type: ignore[arg-type]
        verifier_confidence=confidence,
        verifier_abstained=abstained,
        overruled=overruled,
        span_miss_count=miss,
        span_total=total,
        timestamp=datetime.now(UTC),
        overruled_check_name=overruled_check_name,
        evaluator_evidence_quotes=evaluator_evidence_quotes,
        verifier_reasons=verifier_reasons,
    )
    get_verifier_drift_monitor().record(event)


def _apply_verification(
    evaluation: dict[str, Any],
    verification: dict[str, Any],
) -> dict[str, Any]:
    """Fold the verifier's verdict back into ``evaluation``.

    Rules:
    - ``verdict == "pass"``:   no change.
    - ``confidence < MIN_OVERRIDE_CONFIDENCE`` (abstain path):
      keep ``passed`` as evaluated, attach ``soft_warnings`` and
      mark ``verifier_abstained=True`` for the audit trail.
    - ``verdict == "partial"``: downgrade ``passed`` to False, keep
      ``recommended_next`` as ``refine`` and push
      ``recommended_next_plan`` to ``deep_probe`` so the interviewer
      revisits the dimension.
    - ``verdict == "fail"``:    same as partial, but mark
      ``verifier_forced_refine=True`` for audit trails.
    """
    if not verification or not verification.get("verifier_available"):
        return dict(evaluation)

    verdict = verification.get("verdict", "pass")
    out = dict(evaluation)
    if verdict == "pass":
        return out

    try:
        confidence = float(verification.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
    reasons = [r for r in (verification.get("reasons_to_doubt") or []) if r]

    if confidence < _min_override_confidence():
        # Abstain path: verifier is unsure, do not overrule.
        existing_soft = list(out.get("soft_warnings") or [])
        for r in reasons:
            if r not in existing_soft:
                existing_soft.append(r)
        out["soft_warnings"] = existing_soft
        out["verifier_abstained"] = True
        return out

    # High-confidence partial / fail -> force another refine round
    out["passed"] = False
    out["recommended_next"] = "refine"
    # Prefer deep_probe for refine rounds triggered by the verifier
    # because by definition the current question already passed once.
    out["recommended_next_plan"] = "deep_probe"
    out.setdefault("weaknesses", [])
    for r in reasons:
        if r not in out["weaknesses"]:
            out["weaknesses"].append(r)
    if verdict == "fail":
        out["verifier_forced_refine"] = True
    return out


def verification_node(state: InterviewState) -> dict[str, Any]:
    """Optionally verify the evaluator's verdict.

    Early-returns (empty update) when ``should_trigger`` is False so
    the graph remains idempotent for cheap passes / clear fails.
    """
    node_started_at = time.perf_counter()
    evaluation = state.get("evaluation") or {}
    contract = state.get("current_contract") or (
        (state.get("current_question") or {}).get("contract")
    )
    job_level = (state.get("job_spec") or {}).get("level", "mid")
    dimension = (
        (state.get("current_question") or {}).get("dimension")
        or state.get("current_dimension")
        or "unknown"
    )
    quality_threshold = float(state.get("quality_threshold") or 7.5)
    answer_turn_idx = max(0, int(state.get("turn_idx", 0)) - 1)

    if not should_trigger(
        evaluation=evaluation,
        contract=contract,
        quality_threshold=quality_threshold,
        job_level=job_level,
        dimension=dimension,
    ):
        try:
            get_tracer().trace_node_event(
                dict(state),
                node="verification",
                payload={
                    "triggered": False,
                    "dimension": dimension,
                    "elapsed_ms": int((time.perf_counter() - node_started_at) * 1000),
                },
                logical_turn_idx=answer_turn_idx,
            )
        except Exception as e:  # pragma: no cover - side channel
            log.warning("verification tracer side-channel failed: %s", e)
        return {}

    question_payload = state.get("current_question") or {}
    # Verifier also sees the raw answer (when one is kept); keeping
    # it symmetrical with the evaluator avoids verdict drift from
    # "looks different to two independent reviewers".
    answer = get_raw_answer_for_state(state) or state.get("current_answer", "") or ""
    verification = verify_answer(
        dimension=dimension,
        question=question_payload.get("question", ""),
        answer=answer,
        contract=contract or {},
        evaluator_report=evaluation,
    )
    updated_evaluation = _apply_verification(evaluation, verification)
    updated_evaluation = normalize_evaluation_consistency(
        updated_evaluation,
        contract=contract or {},
        quality_threshold=quality_threshold,
        verification=verification,
        verifier_min_override_confidence=_min_override_confidence(),
    )
    dimension_status = sync_dimension_status(
        dict(state.get("dimension_status") or {}),
        str(dimension),
        updated_evaluation,
    )
    log.info(
        "verification dim=%s verdict=%s forced_refine=%s conf=%.2f",
        dimension,
        verification.get("verdict"),
        updated_evaluation.get("verifier_forced_refine", False),
        verification.get("confidence", 0.0),
    )

    # Drift observability (opt-in). Anything that can go wrong here is
    # non-critical: the monitor is an observation surface, not a
    # decision input, so we log-and-swallow every exception.
    if getattr(get_settings(), "enable_verifier_drift_monitor", False):
        try:
            _record_drift_event(
                evaluation=evaluation,
                updated_evaluation=updated_evaluation,
                verification=verification,
                dimension=dimension,
                job_level=job_level,
            )
        except Exception as e:  # pragma: no cover - monitor is non-critical
            log.debug("drift monitor record failed: %s", e)

    update = {
        "evaluation": updated_evaluation,
        "verification": verification,
        "dimension_status": dimension_status,
    }
    evaluator_passed = bool(evaluation.get("passed", False))
    updated_passed = bool(updated_evaluation.get("passed", False))
    try:
        get_tracer().trace_node_event(
            {**state, **update},
            node="verification",
            payload={
                "triggered": True,
                "dimension": dimension,
                "verdict": verification.get("verdict"),
                "confidence": verification.get("confidence"),
                "forced_refine": updated_evaluation.get(
                    "verifier_forced_refine",
                    False,
                ),
                "evaluator_passed": evaluator_passed,
                "updated_passed": updated_passed,
                "verdict_changed": updated_evaluation != evaluation,
                "verifier_abstained": bool(updated_evaluation.get("verifier_abstained")),
                "elapsed_ms": int((time.perf_counter() - node_started_at) * 1000),
            },
            logical_turn_idx=answer_turn_idx,
        )
    except Exception as e:  # pragma: no cover - side channel
        log.warning("verification tracer side-channel failed: %s", e)
    return update
