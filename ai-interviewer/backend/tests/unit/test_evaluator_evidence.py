"""Tests for the evidence-spans upgrade in ``evaluator_agent``.

The evaluator now emits ``acceptance_check_results[*]`` as the
canonical dict shape ``{"verdict": "yes|partial|no", "evidence":
[str, ...]}`` instead of a flat verdict string. This is the hook
that lets the Verifier catch "yes"-but-handwavy verdicts (the whole
point of P0-2 in ``docs/PLAN_EVIDENCE_SPANS.md``).

What this file pins down:

1. ``_normalize_check_result`` coerces all three accepted inputs
   (legacy string, partial dict, full canonical dict) to the same
   output shape and never raises.
2. The end-to-end ``evaluate_answer`` path keeps the new shape intact
   when the stubbed LLM already returns it.
3. The legacy-string stub (kept in ``test_plan_contract_p0.py``) is
   transparently upgraded by the agent; no caller downstream needs
   to see the old flat strings.
4. Invalid verdicts / non-list evidence are defensively corrected
   rather than propagated.
5. When the LLM returns *no* ``acceptance_check_results`` but the
   contract declared some, the synthetic fallback still matches the
   canonical shape so downstream consumers don't need a special case.
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from app.engine.agents import evaluator_agent as eval_mod
from app.engine.agents.evaluator_agent import (
    _derive_rubric_coverage,
    _normalize_check_result,
    _verdict_of,
)
from app.engine.agents.llm_client import LLMTransient


def _assert_check_core(
    check: dict[str, Any],
    *,
    verdict: str,
    evidence: list[str],
) -> None:
    assert check["verdict"] == verdict
    assert check["evidence"] == evidence
    assert isinstance(check.get("evidence_spans", []), list)

# ---------------------------------------------------------------------------
# _normalize_check_result — shape contract
# ---------------------------------------------------------------------------


def test_normalize_check_result_accepts_legacy_string_shape() -> None:
    out = _normalize_check_result("yes")

    assert out == {"verdict": "yes", "evidence": []}


def test_normalize_check_result_accepts_canonical_dict_shape() -> None:
    raw = {
        "verdict": "partial",
        "evidence": ["we use shadow tables", "backfills nightly"],
    }

    out = _normalize_check_result(raw)

    assert out == {
        "verdict": "partial",
        "evidence": ["we use shadow tables", "backfills nightly"],
    }


def test_normalize_check_result_dict_without_evidence_backfills_empty_list() -> None:
    """A dict with only ``verdict`` (older migration window) is still
    valid: evidence becomes an empty list rather than None, so
    ``iter(evidence)`` in the Verifier prompt never blows up."""
    out = _normalize_check_result({"verdict": "no"})

    assert out == {"verdict": "no", "evidence": []}


def test_normalize_check_result_invalid_verdict_becomes_no() -> None:
    """Defensive path: LLMs occasionally emit ``"maybe"`` or
    uppercase verdicts. We don't want those to poison the rubric
    coverage grid, so invalid verdicts collapse to ``"no"``.
    """
    assert _normalize_check_result("maybe") == {"verdict": "no", "evidence": []}
    assert _normalize_check_result({"verdict": "MAYBE"}) == {
        "verdict": "no",
        "evidence": [],
    }
    assert _normalize_check_result({"verdict": "YES"}) == {
        "verdict": "yes",
        "evidence": [],
    }


def test_normalize_check_result_drops_non_list_evidence() -> None:
    """Guardrail against a model returning ``"evidence": "quote"``
    (string instead of list); we coerce to an empty list rather than
    iterate over the characters.
    """
    out = _normalize_check_result({"verdict": "yes", "evidence": "a quote"})

    assert out == {"verdict": "yes", "evidence": []}


def test_normalize_check_result_filters_empty_evidence_items() -> None:
    out = _normalize_check_result(
        {"verdict": "partial", "evidence": ["", None, "only real quote"]}
    )

    assert out == {"verdict": "partial", "evidence": ["only real quote"]}


def test_normalize_check_result_garbage_input_is_safe() -> None:
    """Integers / None / list inputs should not raise."""
    assert _normalize_check_result(None) == {"verdict": "no", "evidence": []}
    assert _normalize_check_result(42) == {"verdict": "no", "evidence": []}
    assert _normalize_check_result(["yes"]) == {"verdict": "no", "evidence": []}


# ---------------------------------------------------------------------------
# _verdict_of — legacy + canonical unification
# ---------------------------------------------------------------------------


def test_verdict_of_extracts_from_string_and_dict() -> None:
    assert _verdict_of("yes") == "yes"
    assert _verdict_of({"verdict": "partial", "evidence": []}) == "partial"


def test_verdict_of_invalid_inputs_fall_back_to_no() -> None:
    assert _verdict_of({"verdict": "bogus"}) == "no"
    assert _verdict_of({}) == "no"
    assert _verdict_of(None) == "no"


# ---------------------------------------------------------------------------
# _derive_rubric_coverage — reads canonical dict shape via _verdict_of
# ---------------------------------------------------------------------------


def test_derive_rubric_coverage_reads_dict_shape_verdicts() -> None:
    """The coverage helper must not regress to treating the dict
    shape as ``"[object Object]"``; it should pull the verdict out
    via ``_verdict_of``.
    """
    contract = {"must_cover": ["zero-downtime", "rollback"]}
    acceptance = {
        "Discusses zero-downtime strategies.": {
            "verdict": "yes",
            "evidence": ["we use shadow tables"],
        },
        "Mentions a rollback plan.": {
            "verdict": "partial",
            "evidence": [],
        },
    }

    coverage = _derive_rubric_coverage(contract, acceptance, rubric_points=[])

    assert coverage == {"zero-downtime": "covered", "rollback": "partial"}


def test_derive_rubric_coverage_mixed_shapes_are_supported() -> None:
    """A live trace can contain an old-shape entry (before the
    migration commit) sitting alongside a new-shape one; both must
    resolve cleanly.
    """
    contract = {"must_cover": ["consistency", "failover"]}
    acceptance = {
        "Discusses consistency.": "yes",  # legacy
        "Discusses failover.": {  # canonical
            "verdict": "no",
            "evidence": [],
        },
    }

    coverage = _derive_rubric_coverage(contract, acceptance, rubric_points=[])

    assert coverage == {"consistency": "covered", "failover": "missing"}


# ---------------------------------------------------------------------------
# evaluate_answer — end-to-end with new shape
# ---------------------------------------------------------------------------


def test_evaluate_answer_preserves_new_shape_evidence(monkeypatch) -> None:
    """The evaluator LLM stub returns a *canonical* dict shape;
    ``evaluate_answer`` must pass it through unchanged so the Verifier
    can quote the ``evidence`` list in its prompt.
    """

    def fake_call(messages, *, json_mode=False, **kwargs):  # type: ignore[no-untyped-def]
        return (
            '{"score": 8.0, "passed": true, '
            '"strengths": ["concrete trade-offs"], "weaknesses": [], '
            '"acceptance_check_results": {'
            '"Names a CAP trade-off.": {'
            '"verdict": "yes", '
            '"evidence": ["we prefer AP for availability"]'
            "}, "
            '"Explains a failure mode.": {'
            '"verdict": "partial", '
            '"evidence": ["mostly discusses partitions"]'
            "}}, "
            '"recommended_next": "advance", '
            '"recommended_next_plan": "adaptive", '
            '"rationale": "strong"}'
        )

    monkeypatch.setattr(eval_mod, "call_chat", fake_call)

    result = eval_mod.evaluate_answer(
        dimension="system_design",
        question="Explain CAP trade-offs.",
        rubric_points=["CAP", "failure mode"],
        answer="We prefer AP for availability and tolerate partitions...",
        quality_threshold=7.5,
        contract={
            # NOTE: must_cover terms deliberately match the acceptance
            # check wording (``_derive_rubric_coverage`` does a
            # substring match, so ``failure mode`` -> ``Explains a
            # failure mode.``).
            "must_cover": ["CAP", "failure mode"],
            "acceptance_checks": [
                "Names a CAP trade-off.",
                "Explains a failure mode.",
            ],
        },
    )

    acceptance = result["acceptance_check_results"]
    _assert_check_core(
        acceptance["Names a CAP trade-off."],
        verdict="yes",
        evidence=["we prefer AP for availability"],
    )
    _assert_check_core(
        acceptance["Explains a failure mode."],
        verdict="partial",
        evidence=["mostly discusses partitions"],
    )
    # Coverage grid is derived from the verdicts and reaches the
    # downstream consumers untouched.
    assert result["rubric_coverage"]["CAP"] == "covered"
    assert result["rubric_coverage"]["failure mode"] == "partial"


def test_evaluate_answer_uses_evaluator_output_token_budget(monkeypatch) -> None:
    """Evaluator emits evidence-heavy JSON, so it needs its own output budget."""

    captured: dict[str, Any] = {}

    def fake_call(messages, *, json_mode=False, **kwargs):  # type: ignore[no-untyped-def]
        captured.update(kwargs)
        return (
            '{"score": 8.0, "passed": true, '
            '"strengths": [], "weaknesses": [], '
            '"acceptance_check_results": {"Names metrics.": '
            '{"verdict": "yes", "evidence": ["p95 latency"]}}, '
            '"recommended_next": "advance", '
            '"rationale": "ok"}'
        )

    monkeypatch.setattr(eval_mod, "call_chat", fake_call)
    monkeypatch.setattr(
        eval_mod,
        "get_settings",
        lambda: SimpleNamespace(
            evaluator_llm_max_tokens=4096,
            use_context_builder=True,
            evidence_span_alignment=False,
            evidence_span_fuzzy_threshold=0.6,
        ),
    )

    eval_mod.evaluate_answer(
        dimension="technical_depth",
        question="How did you tune it?",
        rubric_points=["metrics"],
        answer="We tracked p95 latency before changing the batch size.",
        quality_threshold=7.0,
        contract={
            "must_cover": ["metrics"],
            "acceptance_checks": ["Names metrics."],
        },
    )

    assert captured.get("max_tokens") == 4096


def test_evaluate_answer_upgrades_legacy_string_shape(monkeypatch) -> None:
    """Some providers (or older snapshots replayed through the
    pipeline) still emit the flat-string shape. ``evaluate_answer``
    must upgrade it to the canonical dict shape with empty evidence
    so every downstream consumer sees one schema.
    """

    def fake_call(messages, *, json_mode=False, **kwargs):  # type: ignore[no-untyped-def]
        return (
            '{"score": 7.8, "passed": true, '
            '"strengths": ["clear"], "weaknesses": [], '
            '"acceptance_check_results": {'
            '"Names one technique.": "yes", '
            '"Mentions risks.": "partial"'
            "}, "
            '"recommended_next": "advance", '
            '"recommended_next_plan": "adaptive", '
            '"rationale": "ok"}'
        )

    monkeypatch.setattr(eval_mod, "call_chat", fake_call)

    result = eval_mod.evaluate_answer(
        dimension="technical_depth",
        question="How do you handle schema migrations?",
        rubric_points=["technique", "risks"],
        answer="We use shadow tables...",
        quality_threshold=7.5,
        contract={
            "must_cover": ["technique", "risks"],
            "acceptance_checks": ["Names one technique.", "Mentions risks."],
        },
    )

    acceptance = result["acceptance_check_results"]
    _assert_check_core(acceptance["Names one technique."], verdict="yes", evidence=[])
    _assert_check_core(acceptance["Mentions risks."], verdict="partial", evidence=[])


def test_evaluate_answer_mixed_shape_response(monkeypatch) -> None:
    """Some providers mix shapes in a single JSON blob (e.g. when
    the prompt partially converts during a rollout). Every entry
    must come out canonical.
    """

    def fake_call(messages, *, json_mode=False, **kwargs):  # type: ignore[no-untyped-def]
        return (
            '{"score": 7.0, "passed": true, '
            '"strengths": [], "weaknesses": [], '
            '"acceptance_check_results": {'
            '"CheckA": "yes", '
            '"CheckB": {"verdict": "partial", '
            '"evidence": ["quote B"]}, '
            '"CheckC": {"verdict": "MAYBE", "evidence": "not a list"}'
            "}, "
            '"recommended_next": "advance", '
            '"rationale": "mixed"}'
        )

    monkeypatch.setattr(eval_mod, "call_chat", fake_call)

    result = eval_mod.evaluate_answer(
        dimension="communication",
        question="Walk me through a failure.",
        rubric_points=[],
        answer="We had a Redis outage...",
        quality_threshold=7.0,
    )

    acceptance = result["acceptance_check_results"]
    _assert_check_core(acceptance["CheckA"], verdict="yes", evidence=[])
    _assert_check_core(acceptance["CheckB"], verdict="partial", evidence=["quote B"])
    # Invalid verdict collapses to "no"; non-list evidence drops.
    _assert_check_core(acceptance["CheckC"], verdict="no", evidence=[])


def test_evaluate_answer_synthesises_canonical_fallback_when_llm_silent(
    monkeypatch,
) -> None:
    """If the contract declared acceptance_checks but the LLM returned
    none (degraded model / timeout), we synthesise fallback entries
    in the *new* canonical shape so downstream code can safely
    ``check["verdict"]`` without isinstance-guards everywhere.
    """

    def fake_call(messages, *, json_mode=False, **kwargs):  # type: ignore[no-untyped-def]
        return (
            '{"score": 5.0, "passed": false, '
            '"strengths": [], "weaknesses": [], '
            '"recommended_next": "refine", '
            '"rationale": "n/a"}'
        )

    monkeypatch.setattr(eval_mod, "call_chat", fake_call)

    contract: dict[str, Any] = {
        "must_cover": ["A", "B"],
        "acceptance_checks": ["Names A.", "Names B."],
    }

    result = eval_mod.evaluate_answer(
        dimension="x",
        question="q",
        rubric_points=["A", "B"],
        answer="blank",
        quality_threshold=7.0,
        contract=contract,
    )

    acceptance = result["acceptance_check_results"]
    # Entries exist, carry a valid verdict, AND have the evidence key
    # so Verifier prompt rendering (``json.dumps``) doesn't KeyError.
    assert set(acceptance.keys()) == {"Names A.", "Names B."}
    for check in acceptance.values():
        assert {"verdict", "evidence"} <= set(check.keys())
        assert set(check.keys()) <= {"verdict", "evidence", "evidence_spans"}
        assert check["verdict"] in {"yes", "partial", "no"}
        assert check["evidence"] == []
        assert check.get("evidence_spans", []) == []


def test_evaluate_answer_falls_back_when_llm_call_fails(monkeypatch) -> None:
    """A provider/network failure in the evaluator must not abort the session.

    The answer is already accepted at this point in the HITL flow. If the
    evaluator LLM is unavailable, we keep the graph moving with a conservative
    structured evaluation instead of surfacing a connection error to the user.
    """

    def fake_call(*_args: Any, **_kwargs: Any) -> str:
        raise LLMTransient("Connection error.")

    monkeypatch.setattr(eval_mod, "call_chat", fake_call)

    result = eval_mod.evaluate_answer(
        dimension="technical_depth",
        question="How did you tune the batch size?",
        rubric_points=["metrics", "trade-offs"],
        answer=(
            "I measured p95 latency, query count, and memory usage before "
            "choosing the batch size, then adjusted it based on Redis hit rate."
        ),
        quality_threshold=7.5,
        contract={
            "must_cover": ["metrics", "trade-offs"],
            "acceptance_checks": [
                "Mentions concrete metrics.",
                "Explains trade-offs.",
            ],
        },
    )

    assert result["source"] == "fallback"
    assert result["fallback_reason"] == "llm_failed"
    assert result["error_kind"] == "network"
    assert result["passed"] is False
    assert result["weaknesses"] == []
    assert result["system_warnings"] == ["评估模型暂时不可用，已使用保守兜底评价。"]
    assert result["recommended_next"] == "refine"
    assert result["recommended_next_plan"] == "simple"
    assert set(result["acceptance_check_results"]) == {
        "Mentions concrete metrics.",
        "Explains trade-offs.",
    }
    assert all(
        item["verdict"] in {"partial", "no"}
        for item in result["acceptance_check_results"].values()
    )
