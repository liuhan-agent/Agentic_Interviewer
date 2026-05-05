"""Integration test: Drift → Evaluator prompt feedback end-to-end.

Verifies that the Phase-2 feature flag
(``enable_evaluator_prompt_feedback``) threads the drift monitor
through ``evaluator_node`` into ``evaluate_answer`` and ends up in
the Evaluator's system-layer messages.

Covers three matrix cells:

1. drift monitor empty -> 2-message shape (no drift → no feedback).
2. drift monitor with only below-threshold events -> 2-message shape
   (the min-support filter rejects the pattern).
3. drift monitor with qualifying patterns -> 3-message shape; the
   new system message contains the rendered negative-examples block.

After the Phase-2 legacy downsize there is no ``use_context_builder``
flag left, so the test always exercises the single
ContextBuilder-based path.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from unittest.mock import patch

import pytest

from app.engine.agents import evaluator_agent as evaluator_module
from app.engine.agents.llm_client import ChatMessage
from app.ml.drift.verifier_drift import (
    DriftEvent,
    get_verifier_drift_monitor,
    reset_verifier_drift_monitor_for_tests,
)

_FAKE_RESPONSE = json.dumps(
    {
        "score": 7.5,
        "passed": True,
        "strengths": [],
        "weaknesses": [],
        "rubric_coverage": {},
        "acceptance_check_results": {},
        "recommended_next": "advance",
        "recommended_next_plan": "adaptive",
        "rationale": "",
    }
)


@pytest.fixture(autouse=True)
def _reset_singleton() -> None:
    reset_verifier_drift_monitor_for_tests()
    yield
    reset_verifier_drift_monitor_for_tests()


def _seed_drift_pattern(count: int = 3) -> None:
    monitor = get_verifier_drift_monitor()
    for _ in range(count):
        monitor.record(
            DriftEvent(
                dimension="system_design",
                job_level="senior",
                evaluator_passed=True,
                verifier_verdict="partial",
                verifier_confidence=0.8,
                verifier_abstained=False,
                overruled=True,
                span_miss_count=0,
                span_total=0,
                timestamp=datetime.now(UTC),
                overruled_check_name="explains isolation per user",
                evaluator_evidence_quotes=("token bucket",),
                verifier_reasons=("buzzword heavy",),
            )
        )


def _capture_messages(*, drift_negatives: str = "") -> list[ChatMessage]:
    """Run ``evaluate_answer`` once and return the exact message list
    the evaluator would have sent to ``call_chat``.
    """
    captured: list[list[ChatMessage]] = []

    def fake_call_chat(messages: list[ChatMessage], **_: Any) -> str:
        captured.append(messages)
        return _FAKE_RESPONSE

    with patch.object(
        evaluator_module, "call_chat", side_effect=fake_call_chat
    ):
        evaluator_module.evaluate_answer(
            dimension="system_design",
            question="Design a rate limiter.",
            rubric_points=["clarity", "trade_offs"],
            answer="I would use a token bucket in Redis.",
            quality_threshold=7.5,
            contract={"must_cover": ["clarity"]},
            drift_negatives=drift_negatives,
        )

    assert len(captured) == 1
    return captured[0]


def test_empty_monitor_produces_two_message_prompt() -> None:
    """Empty drift monitor -> drift_negatives='' -> dynamic layer
    collapses and the renderer emits the baseline 2-message shape."""
    messages = _capture_messages(drift_negatives="")
    assert len(messages) == 2
    assert messages[0].role == "system"
    assert messages[1].role == "user"
    # The Evaluator's static prefix carries the ephemeral cache hint.
    assert messages[0].cache_control == "ephemeral"


def test_below_threshold_monitor_produces_two_message_prompt() -> None:
    """One-off overrule → ``build_evaluator_drift_negatives`` filters it
    out by ``min_support=2`` → drift_negatives='' → 2-message shape."""
    from app.ml.drift.prompt_feedback import (
        build_evaluator_drift_negatives,
    )

    _seed_drift_pattern(count=1)
    assert build_evaluator_drift_negatives() == ""
    messages = _capture_messages(
        drift_negatives=build_evaluator_drift_negatives()
    )
    assert len(messages) == 2


def test_qualifying_pattern_adds_system_message() -> None:
    """Qualifying drift pattern → renderer emits a 3-message list, the
    new middle message carries the rendered negative-examples block
    with ``cache_control=None`` (dynamic layer is uncached)."""
    from app.ml.drift.prompt_feedback import (
        build_evaluator_drift_negatives,
    )

    _seed_drift_pattern(count=3)
    block = build_evaluator_drift_negatives(dimension="system_design")
    assert block  # sanity — the helper actually produced something

    messages = _capture_messages(drift_negatives=block)
    assert len(messages) == 3
    assert messages[0].role == "system"
    assert messages[0].cache_control == "ephemeral"  # static skeleton
    assert messages[1].role == "system"
    assert messages[1].cache_control is None  # dynamic layer
    assert "Prior Evaluator Drift" in messages[1].content
    assert "token bucket" in messages[1].content
    assert messages[2].role == "user"
