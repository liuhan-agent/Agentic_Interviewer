"""End-to-end contract for the raw-answer PII hand-off.

The raw, un-redacted candidate answer lives in a process-local
side-channel for exactly the span ``wait_answer → evaluator →
verification`` and is cleared by ``compress_context_node`` or the
SessionManager error cleanup. This file pins the invariants that keep
PII out of the LangGraph checkpoint:

1. Evaluator sees the raw text for scoring.
2. Verifier sees the same raw text (not the sanitised copy).
3. ``compress_context_node`` erases it regardless of whether a
   compression pass actually ran.
4. ``SessionManager`` erases it if a graph segment fails before
   ``compress_context`` can run.
"""
from __future__ import annotations

from typing import Any

import pytest

from app.engine.workflow.nodes import compress_context as compress_mod
from app.engine.workflow.nodes import verification as verification_node_mod
from app.engine.workflow.nodes import wait_answer as wait_answer_mod

RAW = "My phone is 13812345678"
SANITISED = "My phone is [phone redacted]"


# --------------------------------------------------------------------
# Verifier side of the contract
# --------------------------------------------------------------------


def test_verifier_receives_raw_answer_not_sanitised(monkeypatch) -> None:
    """Regression: the verifier must score against the raw text.

    Before the fix the evaluator cleared ``current_answer_raw`` in its
    own update, which meant this node ran against an empty raw channel
    and silently fell back to ``current_answer`` (sanitised). This
    test fails under that old behaviour.
    """
    captured: dict[str, Any] = {}

    def _fake_should_trigger(**_kwargs: Any) -> bool:
        return True

    def _fake_verify(**kwargs: Any) -> dict[str, Any]:
        captured["answer"] = kwargs["answer"]
        return {
            "verdict": "pass",
            "reasons_to_doubt": [],
            "would_ask_next": "",
            "confidence": 0.9,
            "rationale": "ok",
            "verifier_available": True,
        }

    monkeypatch.setattr(
        verification_node_mod, "should_trigger", _fake_should_trigger
    )
    monkeypatch.setattr(verification_node_mod, "verify_answer", _fake_verify)

    state = {
        "session_id": "sess",
        "trace_id": "trace",
        "turn_idx": 1,
        "job_spec": {"level": "senior"},
        "current_question": {"question": "Q", "dimension": "system_design"},
        "current_dimension": "system_design",
        "quality_threshold": 7.5,
        "current_contract": {"must_cover": [], "acceptance_checks": []},
        "evaluation": {
            "score": 8.0,
            "passed": True,
            "recommended_next": "advance",
        },
        "current_answer": SANITISED,
        "current_answer_raw": RAW,
    }

    verification_node_mod.verification_node(state)  # type: ignore[arg-type]

    assert captured["answer"] == RAW, (
        f"verifier saw {captured['answer']!r}; expected the raw, "
        "unredacted answer"
    )


# --------------------------------------------------------------------
# Compress-context side of the contract
# --------------------------------------------------------------------


def _base_compress_state(**overrides: Any) -> dict[str, Any]:
    """Minimal state for driving ``compress_context_node`` in isolation."""
    state = {
        "qa_history": [],
        "qa_summary": "",
        "qa_summary_through_turn": -1,
        "runtime_config": {},
        "current_answer_raw": RAW,
    }
    state.update(overrides)
    return state


def test_compress_context_clears_raw_even_when_nothing_to_summarise() -> None:
    """Short sessions still pass through compress_context; it must clear.

    ``COMPRESS_AFTER=3`` means the deterministic path short-circuits
    for turns 0-2, but the raw-answer clear contract is owned by this
    node regardless of the summarisation branch.
    """
    out = compress_mod.compress_context_node(_base_compress_state())  # type: ignore[arg-type]

    assert out.get("current_answer_raw") == "", (
        "compress_context must clear current_answer_raw even on the "
        "no-summary short-circuit"
    )
    assert "qa_summary" not in out, (
        "no summary should be produced on the short-circuit path"
    )


def test_compress_context_noop_when_raw_already_empty() -> None:
    """When raw is already empty we must NOT inject a redundant clear.

    Downstream reducer contracts treat "key absent from update" as
    "no change", so a redundant raw clear is not *incorrect* but
    needlessly re-writes the checkpoint byte.
    """
    state = _base_compress_state(current_answer_raw="")
    out = compress_mod.compress_context_node(state)  # type: ignore[arg-type]

    assert "current_answer_raw" not in out


def test_compress_context_clears_raw_on_no_new_turns_branch() -> None:
    qa_history = [
        {
            "turn_idx": i,
            "dimension": "technical_depth",
            "question": f"Q{i}",
            "answer": f"A{i}",
            "selected_action": "plan_adaptive",
            "evaluation": {"score": 7.0, "passed": True},
        }
        for i in range(3)
    ]
    state = _base_compress_state(
        qa_history=qa_history,
        qa_summary_through_turn=3,
    )

    out = compress_mod.compress_context_node(state)  # type: ignore[arg-type]

    assert out.get("current_answer_raw") == ""


def test_session_manager_clears_raw_side_channel_on_segment_error(
    monkeypatch,
) -> None:
    from app.services import session_manager as session_manager_mod

    raw_ref = wait_answer_mod._store_raw_answer(RAW)  # type: ignore[attr-defined]

    class _Workflow:
        def stream(self, *_args, **_kwargs):
            yield {"current_answer_raw_ref": raw_ref}
            raise RuntimeError("boom")

    manager = session_manager_mod.SessionManager.__new__(
        session_manager_mod.SessionManager
    )
    manager._workflow = _Workflow()
    manager._persist_completed = lambda *_args, **_kwargs: None
    handle = session_manager_mod.SessionHandle(
        session_id="sess-raw-error",
        trace_id="trace-raw-error",
    )

    manager._run_segment(handle, None)

    assert wait_answer_mod.get_raw_answer_for_state(
        {"current_answer_raw_ref": raw_ref}
    ) == ""
    assert handle.done_event.is_set()
    assert handle.error


def test_compress_context_clears_raw_without_updating_qa_summary(
    monkeypatch,
) -> None:
    """Long histories still clear raw text, but summary projection now
    belongs to ask_question rather than compress_context."""
    qa_history = [
        {
            "turn_idx": i,
            "dimension": "technical_depth",
            "question": f"Q{i}",
            "answer": f"A{i}",
            "selected_action": "plan_adaptive",
            "evaluation": {
                "score": 7.0,
                "passed": True,
                "strengths": ["clear"],
                "weaknesses": [],
            },
        }
        for i in range(3)
    ]
    state = _base_compress_state(qa_history=qa_history)
    out = compress_mod.compress_context_node(state)  # type: ignore[arg-type]

    assert out.get("current_answer_raw") == ""
    assert "qa_summary" not in out
    assert "qa_summary_through_turn" not in out


# --------------------------------------------------------------------
# Evaluator-level invariant documentation
# --------------------------------------------------------------------


@pytest.mark.parametrize("had_raw", [True, False])
def test_evaluator_never_clears_raw_answer(had_raw, monkeypatch) -> None:
    """Evaluator's update must not touch ``current_answer_raw``.

    Clearing there would starve the verifier node that runs right
    after; the contract is "compress_context owns the clear". Two
    input shapes are exercised to show the invariant holds even when
    there was no PII redaction in the first place.
    """
    from app.engine.workflow.nodes import evaluator as evaluator_node_mod

    def _fake_evaluate(**_kwargs: Any) -> dict[str, Any]:
        return {
            "score": 7.5,
            "passed": True,
            "strengths": [],
            "weaknesses": [],
            "rubric_coverage": {},
            "acceptance_check_results": {},
            "recommended_next": "advance",
            "recommended_next_plan": None,
            "rationale": "",
        }

    class _NullTracer:
        def trace_evaluator(self, *_a: Any, **_kw: Any) -> None:
            return None

    monkeypatch.setattr(evaluator_node_mod, "evaluate_answer", _fake_evaluate)
    monkeypatch.setattr(evaluator_node_mod, "get_tracer", lambda: _NullTracer())

    state = {
        "session_id": "sess",
        "trace_id": "trace",
        "turn_idx": 0,
        "current_question": {"question": "Q", "dimension": "d"},
        "current_dimension": "d",
        "current_answer": "sanitised",
        "current_answer_raw": RAW if had_raw else "",
        "scores_per_dim": {},
        "dimension_status": {},
        "quality_threshold": 7.0,
        "turn_budget_remaining": 3,
        "selected_action": {"id": "plan_adaptive"},
        "qa_history": [],
    }

    out = evaluator_node_mod.evaluator_node(state)  # type: ignore[arg-type]

    assert "current_answer_raw" not in out
