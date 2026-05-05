"""Tests for Verifier <-> evidence-spans integration.

The Verifier's whole purpose is to catch evaluator bluffs. Before
P0-2 it could only see the evaluator's scalar ``"yes"`` label; now
``acceptance_check_results[*]`` carries ``evidence`` quotes from the
candidate's answer, so the Verifier can actually check that the
evaluator's "yes" is grounded.

What this file pins down:

1. ``should_trigger`` reads the **new dict shape** correctly when
   deciding whether to fire on a "passed + partial acceptance"
   contract inconsistency.
2. ``should_trigger`` still triggers on the **legacy string shape**
   (back-compat; otherwise replayed old sessions would silently stop
   verifying).
3. ``should_trigger`` does **not** false-fire on the partial branch
   when the dict shape's verdicts are all ``"yes"``.
4. ``verify_answer`` forwards the ``evidence`` field intact into the
   Verifier's prompt payload (the LLM needs to see the quotes; if
   they vanished in wiring the whole feature is useless).
5. A verifier stub that reads ``evidence`` can still drive
   ``_apply_verification`` correctly — end-to-end handoff works.
"""
from __future__ import annotations

import json
from typing import Any

from app.engine.agents import verification as verif_mod
from app.engine.agents.verification import should_trigger
from app.engine.workflow.nodes.verification import _apply_verification

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _base_contract(**overrides: Any) -> dict[str, Any]:
    c: dict[str, Any] = {
        "must_cover": ["trade-offs", "failure modes"],
        "acceptance_checks": [
            "Names a trade-off.",
            "Explains a failure mode.",
        ],
        "bar_level": "standard",
        "signed_by": ["generator", "evaluator"],
    }
    c.update(overrides)
    return c


def _evaluation(
    *,
    score: float = 9.0,  # well above threshold; avoids "marginal pass" trigger
    passed: bool = True,
    acceptance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "score": score,
        "passed": passed,
        "strengths": ["clear"],
        "weaknesses": [],
        "rubric_coverage": {"trade-offs": "covered", "failure modes": "covered"},
        "acceptance_check_results": acceptance or {},
        "recommended_next": "advance",
        "recommended_next_plan": "adaptive",
        "rationale": "solid",
    }


# ---------------------------------------------------------------------------
# should_trigger — acceptance partial branch, both shapes
# ---------------------------------------------------------------------------


def test_should_trigger_fires_on_partial_in_new_dict_shape() -> None:
    """The contract-inconsistency branch (passed=True but some
    acceptance is partial) must activate when the verdicts live under
    the canonical dict shape.

    We pick a non-bluff-prone dimension (``communication``) and a
    comfortably-passing score so the partial branch is the *only*
    reason the trigger can fire — if it still returns True, we know
    the new shape is being read correctly.
    """
    evaluation = _evaluation(
        acceptance={
            "Names a trade-off.": {"verdict": "yes", "evidence": ["we use CQRS"]},
            "Explains a failure mode.": {
                "verdict": "partial",
                "evidence": [],
            },
        }
    )

    fired = should_trigger(
        evaluation=evaluation,
        contract=_base_contract(),
        quality_threshold=7.0,
        job_level="mid",
        dimension="communication",
    )

    assert fired is True


def test_should_trigger_fires_on_partial_in_legacy_string_shape() -> None:
    """Same test but legacy string shape, ensuring replayed old
    sessions don't silently stop running the verifier.
    """
    evaluation = _evaluation(
        acceptance={
            "Names a trade-off.": "yes",
            "Explains a failure mode.": "partial",
        }
    )

    fired = should_trigger(
        evaluation=evaluation,
        contract=_base_contract(),
        quality_threshold=7.0,
        job_level="mid",
        dimension="communication",
    )

    assert fired is True


def test_should_trigger_skips_clean_pass_with_new_dict_shape() -> None:
    """Clean pass (all verdicts ``yes``, comfortably above threshold,
    non-bluff dimension) must NOT trigger — otherwise we'd waste LLM
    budget on every well-answered turn.
    """
    evaluation = _evaluation(
        acceptance={
            "Names a trade-off.": {"verdict": "yes", "evidence": ["we use CQRS"]},
            "Explains a failure mode.": {
                "verdict": "yes",
                "evidence": ["partitions lead to split brain"],
            },
        }
    )

    fired = should_trigger(
        evaluation=evaluation,
        contract=_base_contract(),
        quality_threshold=7.0,
        job_level="mid",
        dimension="communication",
    )

    assert fired is False


def test_should_trigger_ignores_garbage_verdicts_in_dict_shape() -> None:
    """A malformed ``{"verdict": "maybe"}`` must NOT accidentally
    count as partial (``_verdict_of`` collapses unknown to "no", so
    the trigger should stay off on that alone).
    """
    evaluation = _evaluation(
        acceptance={
            "Names a trade-off.": {"verdict": "yes", "evidence": []},
            "Explains a failure mode.": {"verdict": "maybe", "evidence": []},
        }
    )

    fired = should_trigger(
        evaluation=evaluation,
        contract=_base_contract(),
        quality_threshold=7.0,
        job_level="mid",
        dimension="communication",
    )

    assert fired is False


# ---------------------------------------------------------------------------
# verify_answer — evidence field reaches the verifier prompt
# ---------------------------------------------------------------------------


def test_verify_answer_forwards_evidence_into_verifier_prompt(monkeypatch) -> None:
    """The whole point of P0-2 is that the Verifier LLM gets to see
    the evidence quotes. If wiring drops the field somewhere, the
    feature is invisible to the model even though the shape is
    correct at the Python level. This test asserts the evidence
    string appears in the user-message payload that ``call_chat``
    receives.
    """
    captured: dict[str, Any] = {}

    def fake_call(messages, *, json_mode=False, **kwargs):  # type: ignore[no-untyped-def]
        captured["messages"] = messages
        return json.dumps(
            {
                "verdict": "partial",
                "reasons_to_doubt": ["evidence quotes are vague"],
                "would_ask_next": "quantify the trade-off",
                "confidence": 0.8,
                "rationale": "the quotes do not actually ground the claim",
            }
        )

    monkeypatch.setattr(verif_mod, "call_chat", fake_call)

    evaluator_report = {
        "score": 8.2,
        "passed": True,
        "strengths": ["plausible narrative"],
        "weaknesses": [],
        "rubric_coverage": {"trade-offs": "covered"},
        "acceptance_check_results": {
            "Names a trade-off.": {
                "verdict": "yes",
                "evidence": ["we prefer availability under partitions"],
            },
        },
        "recommended_next": "advance",
        "recommended_next_plan": "adaptive",
        "rationale": "sounds ok",
    }

    result = verif_mod.verify_answer(
        dimension="system_design",
        question="What's your stance on CAP?",
        answer="We prefer availability under partitions, sort of.",
        contract=_base_contract(),
        evaluator_report=evaluator_report,
    )

    assert result["verdict"] == "partial"
    assert result["verifier_available"] is True

    # The user message is the 2nd ChatMessage; it must contain the
    # verbatim evidence quote, otherwise the verifier LLM is judging
    # blind.
    user_text = captured["messages"][1].content
    assert "we prefer availability under partitions" in user_text
    # And the verdict label must still be present alongside it.
    assert '"verdict": "yes"' in user_text or '"verdict":"yes"' in user_text


def test_verify_answer_still_works_with_legacy_shape_evaluator_report(
    monkeypatch,
) -> None:
    """Old checkpoints can resume into the new code path; the
    verifier prompt just won't have evidence to quote, but the call
    itself must not raise.
    """
    captured: dict[str, Any] = {}

    def fake_call(messages, *, json_mode=False, **kwargs):  # type: ignore[no-untyped-def]
        captured["messages"] = messages
        return json.dumps({"verdict": "pass", "confidence": 0.9})

    monkeypatch.setattr(verif_mod, "call_chat", fake_call)

    evaluator_report = {
        "score": 8.0,
        "passed": True,
        "acceptance_check_results": {  # legacy flat string shape
            "Names a trade-off.": "yes",
            "Explains a failure mode.": "yes",
        },
    }

    result = verif_mod.verify_answer(
        dimension="system_design",
        question="q",
        answer="a",
        contract=_base_contract(),
        evaluator_report=evaluator_report,
    )

    assert result["verdict"] == "pass"
    # Legacy shape is still JSON-serialisable and makes it into the prompt.
    user_text = captured["messages"][1].content
    assert "Names a trade-off." in user_text


# ---------------------------------------------------------------------------
# end-to-end: verifier reads evidence -> _apply_verification updates evaluation
# ---------------------------------------------------------------------------


def test_apply_verification_handoff_with_evidence_shape() -> None:
    """The evidence upgrade is about what the verifier *sees* in its
    prompt; ``_apply_verification`` downstream only cares about the
    verifier's own verdict/confidence. This test confirms the handoff
    still works when the evaluator carries the new-shape
    ``acceptance_check_results`` (regression guard against anyone
    adding a shape check inside ``_apply_verification``).
    """
    evaluation = {
        "score": 7.8,
        "passed": True,
        "strengths": ["clear"],
        "weaknesses": [],
        "recommended_next": "advance",
        "recommended_next_plan": "adaptive",
        "rubric_coverage": {"trade-offs": "covered"},
        "acceptance_check_results": {
            "Names a trade-off.": {
                "verdict": "yes",
                "evidence": ["we trade consistency for availability"],
            }
        },
    }
    verification = {
        "verifier_available": True,
        "verdict": "partial",
        "reasons_to_doubt": ["evidence was a restatement, not a trade-off"],
        "would_ask_next": "name a concrete alternative",
        "confidence": 0.8,
        "rationale": "quote cited does not actually name a trade-off",
    }

    updated = _apply_verification(evaluation, verification)

    assert updated["passed"] is False
    assert updated["recommended_next"] == "refine"
    assert updated["recommended_next_plan"] == "deep_probe"
    # Acceptance check results (including the dict shape) must be
    # preserved untouched so downstream final_report can still quote
    # the evidence in audit trails.
    assert updated["acceptance_check_results"] == evaluation["acceptance_check_results"]
