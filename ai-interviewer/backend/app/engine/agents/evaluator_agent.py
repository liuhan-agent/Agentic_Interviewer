"""Evaluator ("Critic") agent.

Scores a single answer against the pre-signed :class:`PlanContract`
(or, for backwards compat, the legacy ``rubric_points``). Returns
numeric scores, strengths, weaknesses, per-check results and a
recommended next action / next plan template.

Acceptance check shape
----------------------
``acceptance_check_results`` is canonicalised by
:func:`_normalize_check_result` into::

    {"<check>": {"verdict": "yes|partial|no", "evidence": ["quote", ...]}}

Evidence is a list of short verbatim quotes from the candidate's
answer that justify the verdict - the Verifier uses these to
stress-test the evaluator's call (see
``app/engine/agents/verification.py``). Three incoming shapes are
accepted:

1. ``"yes" | "partial" | "no"`` (legacy string) - evidence becomes
   an empty list.
2. ``{"verdict": "..."}`` - evidence becomes an empty list.
3. ``{"verdict": "...", "evidence": [str, ...]}`` - full new shape.

Invalid verdicts degrade to ``"no"``; non-list evidence is dropped.
Older snapshots in the DB / trainset are NEVER rewritten; only new
evaluations emit the full dict shape. Downstream code must therefore
treat either a string OR a dict as valid.
"""
from __future__ import annotations

import difflib
from typing import Any

from app.core.logging import get_logger
from app.core.settings import get_settings
from app.engine.context import (
    build_context_frame_for_evaluator,
    frame_to_evaluator_messages,
)

from .llm_client import call_chat, classify_llm_error_kind, parse_json_response

log = get_logger(__name__)


_VALID_FAILURE_CATEGORIES: set[str] = set()


def _failure_category_vocabulary() -> set[str]:
    """Resolve the legal :data:`FailureCategory` enum lazily.

    The ``state`` module imports a fair chunk of LangGraph machinery, so
    we defer the import to first use to keep ``evaluator_agent`` cheap
    to import for tooling. The result is cached because the enum is
    fixed for the life of the process.
    """
    global _VALID_FAILURE_CATEGORIES
    if not _VALID_FAILURE_CATEGORIES:
        from app.engine.workflow.state import FailureCategory  # noqa: WPS433

        _VALID_FAILURE_CATEGORIES = set(FailureCategory.__args__)  # type: ignore[attr-defined]
    return _VALID_FAILURE_CATEGORIES


def _normalize_failure_categories(raw: Any, *, max_items: int = 3) -> list[str]:
    """Clean up the model's ``failure_categories`` field.

    Drops unknown / blank values, collapses duplicates while preserving
    order, and hard-caps the result at ``max_items`` so prompt budgets
    downstream stay bounded. Non-list inputs degrade to ``[]`` rather
    than raising — the evaluator is on a hot path and a malformed LLM
    response must never break scoring.
    """
    if not isinstance(raw, list):
        return []
    vocab = _failure_category_vocabulary()
    seen: set[str] = set()
    out: list[str] = []
    for item in raw:
        value = str(item or "").strip()
        if not value or value not in vocab or value in seen:
            continue
        out.append(value)
        seen.add(value)
        if len(out) >= max_items:
            break
    return out


def _normalize_check_result(
    raw: Any,
    *,
    answer: str | None = None,
    enable_spans: bool = False,
    fuzzy_threshold: float = 0.6,
) -> dict[str, Any]:
    """Coerce one ``acceptance_check_results[key]`` value into canonical shape.

    See the module docstring for the three accepted input shapes. The
    output is always ``{"verdict": "yes|partial|no", "evidence":
    [str, ...]}``; invalid verdicts become ``"no"`` and non-list
    evidence is dropped.

    When ``enable_spans`` is True and ``answer`` is provided, the
    returned dict additively carries an ``"evidence_spans"`` list with
    the **same length and order** as ``evidence`` — each entry is the
    ``{"text","start","end","match"}`` object produced by
    :func:`_align_one_span`. Keeping ``evidence`` untouched preserves
    byte-identical output for all existing consumers; the spans are an
    additive upgrade (see ``docs/PLAN_EVIDENCE_SPAN_ALIGNMENT.md``).

    The ``enable_spans`` / ``answer`` / ``fuzzy_threshold`` parameters
    all default to the pre-rollout behaviour so callers that omit them
    get zero shape diff.
    """
    if isinstance(raw, str):
        verdict_raw = raw.strip().lower()
        verdict = verdict_raw if verdict_raw in {"yes", "partial", "no"} else "no"
        return _with_spans(verdict, [], answer, enable_spans, fuzzy_threshold)
    if isinstance(raw, dict):
        verdict_raw = str(raw.get("verdict", "")).strip().lower()
        verdict = verdict_raw if verdict_raw in {"yes", "partial", "no"} else "no"
        evidence_raw = raw.get("evidence") or []
        if not isinstance(evidence_raw, list):
            evidence_raw = []
        evidence = [str(e) for e in evidence_raw if e]
        return _with_spans(verdict, evidence, answer, enable_spans, fuzzy_threshold)
    return _with_spans("no", [], answer, enable_spans, fuzzy_threshold)


def _with_spans(
    verdict: str,
    evidence: list[str],
    answer: str | None,
    enable_spans: bool,
    fuzzy_threshold: float,
) -> dict[str, Any]:
    """Assemble the canonical result dict and append ``evidence_spans``.

    Only emits the ``evidence_spans`` key when the caller opted in AND
    an answer was supplied. This keeps the old
    ``{"verdict", "evidence"}`` shape byte-identical for every
    non-opt-in call site (``rg`` covers: legacy tests, other agents
    reading the dict shape, final_report snapshot equality).
    """
    result: dict[str, Any] = {"verdict": verdict, "evidence": evidence}
    if enable_spans and answer is not None:
        result["evidence_spans"] = [
            _align_one_span(q, answer, fuzzy_threshold=fuzzy_threshold)
            for q in evidence
        ]
    return result


def _verdict_of(value: Any) -> str:
    """Extract the verdict string from either legacy or canonical shape.

    Small helper so downstream consumers (final_report, Verifier
    prompt wiring) don't have to re-implement the isinstance branch.
    """
    if isinstance(value, dict):
        v = str(value.get("verdict", "")).strip().lower()
    else:
        v = str(value).strip().lower()
    return v if v in {"yes", "partial", "no"} else "no"


def _align_one_span(
    quote: str,
    answer: str,
    *,
    fuzzy_threshold: float = 0.6,
) -> dict[str, Any]:
    """Locate ``quote`` inside ``answer`` and return an offset span.

    Strategy, in order:

    1. **exact**: ``answer.find(quote)`` — cheap, succeeds when the
       evaluator actually obeyed the "verbatim" prompt instruction.
    2. **fuzzy**: ``difflib.SequenceMatcher.find_longest_match`` on
       the raw strings. Accepts if
       ``block.size / max(len(quote), 1) >= fuzzy_threshold``.
    3. **none**: give up, return ``{"text": quote, "start": -1,
       "end": -1, "match": "none"}``.

    Never raises. Returns a canonical-shape dict on every path so
    the caller can blindly append to ``evidence_spans``. ``autojunk``
    is disabled because difflib's default junk heuristic drops
    high-frequency chars (spaces, punctuation, common CJK glyphs),
    which would inflate fuzzy-match ratios on Chinese text.
    """
    if not quote or not answer:
        return {"text": quote, "start": -1, "end": -1, "match": "none"}

    exact = answer.find(quote)
    if exact >= 0:
        return {
            "text": quote,
            "start": exact,
            "end": exact + len(quote),
            "match": "exact",
        }

    matcher = difflib.SequenceMatcher(a=answer, b=quote, autojunk=False)
    block = matcher.find_longest_match(0, len(answer), 0, len(quote))
    overlap_ratio = block.size / max(len(quote), 1)
    if overlap_ratio >= fuzzy_threshold:
        return {
            "text": quote,
            "start": block.a,
            "end": block.a + block.size,
            "match": "fuzzy",
        }

    return {"text": quote, "start": -1, "end": -1, "match": "none"}


def _derive_rubric_coverage(
    contract: dict[str, Any] | None,
    acceptance_check_results: dict[str, Any],
    rubric_points: list[str],
) -> dict[str, str]:
    """Best-effort mapping from acceptance checks to rubric coverage.

    Many downstream consumers still read ``rubric_coverage``; we
    keep it populated by treating each ``must_cover`` entry as
    "covered" if *any* acceptance check mentioning it (case-insensitive
    substring) came back "yes", "partial" on "partial", else
    "missing". When no contract is supplied, fall back to the flat
    rubric_points list.

    Accepts both the legacy string shape and the canonical dict shape
    on ``acceptance_check_results`` values; the verdict is extracted
    via :func:`_verdict_of`.
    """
    keys: list[str] = []
    if contract and contract.get("must_cover"):
        keys = list(contract.get("must_cover") or [])
    if not keys:
        keys = list(rubric_points)

    coverage: dict[str, str] = {}
    check_items = list(acceptance_check_results.items())
    for key in keys:
        key_l = key.lower()
        status = "missing"
        for check_text, check_value in check_items:
            if key_l in check_text.lower():
                verdict = _verdict_of(check_value)
                if verdict == "yes":
                    status = "covered"
                    break
                if verdict == "partial" and status != "covered":
                    status = "partial"
        coverage[key] = status
    return coverage


def _fallback_acceptance_check_results(
    *,
    contract: dict[str, Any],
    answer: str,
    enable_spans: bool,
) -> dict[str, dict[str, Any]]:
    """Create conservative acceptance results when the evaluator LLM is down."""
    checks = contract.get("acceptance_checks") or []
    verdict = "partial" if len(answer.strip()) >= 80 else "no"
    entry: dict[str, Any] = {"verdict": verdict, "evidence": []}
    if enable_spans:
        entry["evidence_spans"] = []
    return {
        str(check): dict(entry)
        for check in checks
        if str(check).strip()
    }


def _fallback_evaluation(
    *,
    exc: BaseException,
    contract: dict[str, Any],
    rubric_points: list[str],
    answer: str,
    quality_threshold: float,
    enable_spans: bool,
) -> dict[str, Any]:
    """Fail open when evaluator LLM is unavailable.

    At this point the user's answer has already been accepted by the HITL
    runtime. A provider/network failure should not turn the whole interview
    into a terminal connection error. We return a low-confidence structured
    evaluation that preserves the transcript and asks for one more simple
    follow-up.
    """
    score = 5.0 if len(answer.strip()) < 40 else min(6.5, quality_threshold - 0.5)
    score = max(0.0, round(float(score), 2))
    acceptance = _fallback_acceptance_check_results(
        contract=contract,
        answer=answer,
        enable_spans=enable_spans,
    )
    coverage = _derive_rubric_coverage(contract, acceptance, rubric_points)
    return {
        "source": "fallback",
        "fallback_reason": "llm_failed",
        "error_kind": classify_llm_error_kind(exc),
        "score": score,
        "passed": False,
        "strengths": ["本轮回答已记录到面试 transcript 中。"],
        "weaknesses": [],
        "system_warnings": ["评估模型暂时不可用，已使用保守兜底评价。"],
        "rubric_coverage": coverage,
        "acceptance_check_results": acceptance,
        "recommended_next": "refine",
        "recommended_next_plan": "simple",
        "failure_categories": [],
        "rationale": (
            "评估模型在返回评分前失败。系统已保留本轮回答，但本轮不作为能力弱项。"
        ),
    }


def evaluate_answer(
    *,
    dimension: str,
    question: str,
    rubric_points: list[str],
    answer: str,
    quality_threshold: float,
    contract: dict[str, Any] | None = None,
    drift_negatives: str = "",
    video_signals: dict[str, Any] | None = None,
    context_flags: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the structured evaluation payload.

    The function never raises on unparsable LLM output; it degrades
    gracefully to a neutral 5/10 with empty coverage so the graph
    keeps flowing rather than deadlocking.

    ``contract`` is the co-signed :class:`PlanContract`. Older callers
    can still pass only ``rubric_points`` - in that case the
    evaluator falls back to the original rubric grid and the new
    ``acceptance_check_results`` / ``recommended_next_plan`` fields
    come back empty.

    ``drift_negatives`` (``PLAN_DRIFT_FEEDBACK`` Step 3) is a rendered
    Markdown block of prior evaluator drift patterns, threaded
    through to the Evaluator's ``dynamic_system`` context slot. Empty
    string keeps behaviour identical to Phase 1 (the default) and is
    what the legacy branch always produces; the drift-feedback
    feature flag opts call-sites into building a non-empty block via
    :func:`app.ml.drift.prompt_feedback.build_evaluator_drift_negatives`.
    """
    contract_payload = contract or {}
    settings = get_settings()
    # ``drift_negatives`` is a slot-based feature delivered via the
    # context builder's dynamic-system layer (see
    # ``app/engine/context/builder.py::build_context_frame_for_evaluator``).
    # Legacy callers that opted out of the builder (``use_context_builder=False``)
    # must see the Phase-1 two-message shape regardless of what they
    # pass here, so pin the value to ``""`` on the legacy branch. This
    # matches the contract pinned by
    # ``tests/unit/test_evaluator_drift_injection.py::test_legacy_branch_ignores_drift_negatives``.
    effective_drift_negatives = (
        drift_negatives
        if getattr(settings, "use_context_builder", True)
        else ""
    )
    frame = build_context_frame_for_evaluator(
        dimension=dimension,
        question=question,
        rubric_points=rubric_points,
        answer=answer,
        quality_threshold=quality_threshold,
        contract=contract_payload,
        drift_negatives=effective_drift_negatives,
        video_signals=video_signals,
        context_flags=context_flags,
    )
    messages = frame_to_evaluator_messages(frame)
    evaluator_max_tokens = int(
        getattr(
            settings,
            "evaluator_llm_max_tokens",
            getattr(settings, "llm_max_tokens", 2048),
        )
        or getattr(settings, "llm_max_tokens", 2048)
    )
    try:
        raw = call_chat(
            messages,
            json_mode=True,
            agent_role="evaluator",
            max_tokens=evaluator_max_tokens,
        )
    except Exception as e:
        enable_spans = bool(getattr(settings, "evidence_span_alignment", False))
        log.warning(
            "evaluator LLM failed; using conservative fallback (%s)",
            classify_llm_error_kind(e),
        )
        return _fallback_evaluation(
            exc=e,
            contract=contract_payload,
            rubric_points=rubric_points,
            answer=answer,
            quality_threshold=quality_threshold,
            enable_spans=enable_spans,
        )
    data = parse_json_response(raw)

    try:
        score = float(data.get("score", 5.0))
    except (TypeError, ValueError):
        score = 5.0

    # Evidence-span alignment is additive. When enabled, the
    # per-check normaliser also emits an ``evidence_spans`` list aligned
    # to the candidate answer (see
    # ``docs/PLAN_EVIDENCE_SPAN_ALIGNMENT.md``). Reading via ``getattr`` keeps
    # test fixtures that pass a trimmed-down ``SimpleNamespace``
    # settings stub working without having to re-declare every knob.
    enable_spans = bool(getattr(settings, "evidence_span_alignment", False))
    fuzzy_threshold = float(getattr(settings, "evidence_span_fuzzy_threshold", 0.6))

    raw_acceptance = data.get("acceptance_check_results")
    acceptance_checks_out: dict[str, dict[str, Any]] = {}
    if isinstance(raw_acceptance, dict):
        for k, v in raw_acceptance.items():
            if not isinstance(k, str):
                continue
            acceptance_checks_out[k] = _normalize_check_result(
                v,
                answer=answer if enable_spans else None,
                enable_spans=enable_spans,
                fuzzy_threshold=fuzzy_threshold,
            )

    must_cover = list(contract_payload.get("must_cover") or [])
    # If the model returned nothing, synthesise one-off entries so
    # downstream code doesn't have to special-case empty dicts. Use
    # the canonical dict shape with empty evidence (there is nothing
    # to quote since the model failed to reply). When spans are enabled
    # we also attach an empty ``evidence_spans`` list so the shape
    # contract (len(evidence_spans) == len(evidence)) still holds.
    if not acceptance_checks_out and contract_payload.get("acceptance_checks"):
        fallback_entry: dict[str, Any] = {"verdict": "partial", "evidence": []}
        if enable_spans:
            fallback_entry["evidence_spans"] = []
        acceptance_checks_out = {
            check: dict(fallback_entry)
            for check in (contract_payload.get("acceptance_checks") or [])
        }

    # Default coverage: reuse evaluator output if present, otherwise
    # derive from acceptance_check_results, otherwise fall back to the
    # legacy per-rubric_point "partial" grid.
    coverage_out = data.get("rubric_coverage")
    if not isinstance(coverage_out, dict) or not coverage_out:
        coverage_out = _derive_rubric_coverage(
            contract_payload, acceptance_checks_out, rubric_points
        )

    # ``passed`` respects both thresholds: numeric score AND that every
    # must_cover entry has at least partial coverage. This is stricter
    # than the previous version (numeric only) but only when a
    # contract was actually supplied.
    hit_threshold = score >= quality_threshold
    must_cover_ok = True
    if must_cover:
        must_cover_ok = all(
            coverage_out.get(key) in {"covered", "partial"} for key in must_cover
        )
    passed_default = hit_threshold and must_cover_ok
    model_passed = bool(data.get("passed", passed_default))
    passed = model_passed and passed_default

    rec = data.get("recommended_next") or ("advance" if passed else "refine")
    rec_plan = data.get("recommended_next_plan")
    if rec_plan not in {
        "simple", "adaptive", "deep_probe", None,
    }:
        rec_plan = None

    from app.engine.workflow.state import ProbeIntent  # noqa: E402 — avoid circular at module level

    valid_probe_intents: set[str] = set(ProbeIntent.__args__)  # type: ignore[attr-defined]
    rec_probe_intent = data.get("recommended_probe_intent")
    if rec_probe_intent not in valid_probe_intents:
        rec_probe_intent = None
    failure_reason = data.get("failure_reason")
    if not isinstance(failure_reason, str) or not failure_reason.strip():
        failure_reason = None
    failure_categories = _normalize_failure_categories(data.get("failure_categories"))

    result = {
        "score": score,
        "passed": passed,
        "strengths": data.get("strengths") or [],
        "weaknesses": data.get("weaknesses") or [],
        "rubric_coverage": coverage_out,
        "acceptance_check_results": acceptance_checks_out,
        "recommended_next": rec,
        "recommended_next_plan": rec_plan,
        "recommended_probe_intent": rec_probe_intent,
        "failure_reason": failure_reason,
        "failure_categories": failure_categories,
        "rationale": data.get("rationale", ""),
    }
    log.debug(
        "evaluator dim=%s score=%.2f passed=%s rec=%s next_plan=%s",
        dimension,
        score,
        passed,
        rec,
        rec_plan,
    )
    return result
