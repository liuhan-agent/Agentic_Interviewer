"""Regression tests for Trace Explorer workflow turn alignment."""
from __future__ import annotations

from contextlib import contextmanager
from typing import Any


def test_trace_node_event_can_write_explicit_logical_turn(monkeypatch) -> None:
    from app.core import tracer as tracer_mod

    captured: list[Any] = []

    class _Session:
        def add(self, row: Any) -> None:
            captured.append(row)

    @contextmanager
    def _fake_get_session():
        yield _Session()

    monkeypatch.setattr(tracer_mod, "_ensure_db", lambda: None)
    monkeypatch.setattr(tracer_mod, "get_session", _fake_get_session)

    state = {
        "session_id": "sess-align",
        "trace_id": "trace-align",
        "turn_idx": 1,
        "current_dimension": "system_design",
        "current_question": {"question": "Q", "dimension": "system_design"},
        "current_answer": "A",
        "evaluation": {"score": 8.0, "passed": True},
        "selected_action": {"id": "deep_probe"},
    }

    tracer_mod.Tracer().trace_node_event(
        state,
        node="verification",
        payload={"triggered": False},
        logical_turn_idx=0,
    )

    assert len(captured) == 1
    assert captured[0].turn_idx == 0


def test_verification_and_reward_trace_the_answer_turn(monkeypatch) -> None:
    from app.engine.workflow.nodes import reward_update as reward_mod
    from app.engine.workflow.nodes import verification as verification_mod

    calls: list[dict[str, Any]] = []

    class _Tracer:
        def trace_node_event(self, _state: dict[str, Any], **kwargs: Any) -> None:
            calls.append(kwargs)

    class _Bandit:
        def update(self, _context_key: str, _action_id: str, _reward: float) -> None:
            return None

    monkeypatch.setattr(verification_mod, "get_tracer", lambda: _Tracer())
    monkeypatch.setattr(reward_mod, "get_tracer", lambda: _Tracer())
    monkeypatch.setattr(reward_mod, "get_bandit", lambda: _Bandit())

    state = {
        "session_id": "sess-align",
        "trace_id": "trace-align",
        "turn_idx": 1,
        "current_dimension": "system_design",
        "current_question": {"question": "Q", "dimension": "system_design"},
        "current_answer": "A",
        "evaluation": {"score": 8.0, "passed": True},
        "selected_action": {"id": "deep_probe"},
        "job_spec": {"level": "senior"},
        "quality_threshold": 7.5,
    }

    verification_mod.verification_node(state)  # type: ignore[arg-type]
    reward_mod.reward_update_node(state)  # type: ignore[arg-type]

    by_node = {call["node"]: call for call in calls}
    assert by_node["verification"]["logical_turn_idx"] == 0
    assert by_node["reward_update"]["logical_turn_idx"] == 0
