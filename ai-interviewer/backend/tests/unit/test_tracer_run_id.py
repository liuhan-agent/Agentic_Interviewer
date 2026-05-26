"""Tests for LangSmith ``run_id`` write-back in ``app.core.tracer``.

What we are locking in
----------------------
- ``_current_langsmith_run_id`` returns ``None`` when the LangSmith
  package is absent OR the run tree has not been set up (the default
  ``langsmith_tracing=False`` world). The tracer row's
  ``langsmith_run_id`` column MUST be ``None`` in that case — producing
  a spurious value would poison ``/admin/*`` drill-down queries.
- When a run tree IS present, ``trace_evaluator`` and
  ``trace_director_sample`` attach the ``run_id`` to the persisted
  ``GenerationTrace`` row so ops can follow the link from an
  anomalous immediate-reward row to the full LangSmith run.

Testing strategy
----------------
We monkeypatch ``langsmith.run_helpers.get_current_run_tree`` to a
stub that returns a lightweight object with an ``id`` attribute. The
DB is captured in-memory by patching ``tracer.get_session`` with a
fake session that appends adds to a list, so the tests never touch
the real sqlite / Postgres engine or boot ``init_db``.
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Any

import pytest

from app.core import tracer as tracer_mod

# ---------------------------------------------------------------------------
# Fake session + run-tree plumbing
# ---------------------------------------------------------------------------


class _RunTree:
    def __init__(self, run_id: str) -> None:
        self.id = run_id


class _FakeSession:
    def __init__(self, adds: list[Any]) -> None:
        self._adds = adds

    def add(self, obj: Any) -> None:
        self._adds.append(obj)


def _patch_db(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    """Replace ``tracer.get_session`` so writes land in a list.

    ``_ensure_db`` is also neutered because it would otherwise try to
    call the real ``init_db`` which touches the SQLAlchemy engine.
    """
    adds: list[Any] = []

    @contextmanager
    def fake_session():
        yield _FakeSession(adds)

    monkeypatch.setattr(tracer_mod, "get_session", fake_session)
    monkeypatch.setattr(tracer_mod, "_ensure_db", lambda: None)
    return adds


def _patch_run_tree(
    monkeypatch: pytest.MonkeyPatch, tree: _RunTree | None
) -> None:
    """Install a fake ``get_current_run_tree`` inside ``langsmith``.

    The helper imports lazily from ``langsmith.run_helpers`` to keep
    the optional dependency truly optional at runtime. We reproduce
    the module path here so the lazy import resolves our stub.
    """
    import types

    module_name = "langsmith.run_helpers"
    stub = types.ModuleType(module_name)
    stub.get_current_run_tree = lambda: tree  # type: ignore[attr-defined]
    monkeypatch.setitem(__import__("sys").modules, module_name, stub)


# ---------------------------------------------------------------------------
# _current_langsmith_run_id
# ---------------------------------------------------------------------------


def test_current_run_id_returns_none_when_run_tree_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_run_tree(monkeypatch, None)
    assert tracer_mod._current_langsmith_run_id() is None


def test_current_run_id_extracts_id_from_run_tree(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_run_tree(monkeypatch, _RunTree("run-abc123"))
    assert tracer_mod._current_langsmith_run_id() == "run-abc123"


def test_current_run_id_swallows_import_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The tracer must survive ``langsmith`` being absent from the
    environment; the function is wrapped in a broad try/except for
    that exact reason."""
    import sys
    import types

    broken = types.ModuleType("langsmith.run_helpers")

    def _raise() -> Any:
        raise RuntimeError("simulated import boom")

    broken.get_current_run_tree = _raise  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "langsmith.run_helpers", broken)
    assert tracer_mod._current_langsmith_run_id() is None


# ---------------------------------------------------------------------------
# trace_evaluator + trace_director_sample write-back
# ---------------------------------------------------------------------------


def _minimal_state() -> dict[str, Any]:
    """The smallest state dict the tracer methods will accept.

    Mirrors the shape produced by ``build_initial_state`` after a
    turn has been evaluated; only fields actually read by the tracer
    methods under test need to be present.
    """
    return {
        "session_id": "sess-xyz",
        "trace_id": "trace-xyz",
        "turn_idx": 2,
        "current_dimension": "system_design",
        "selected_action": {"id": "plan_adaptive"},
        "policy_id": "template",
        "job_spec": {"level": "senior"},
        "current_question": {"question": "Q?"},
        "current_answer": "A.",
        "evaluation": {"score": 8.0, "passed": True},
    }


def test_trace_evaluator_writes_run_id_when_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adds = _patch_db(monkeypatch)
    _patch_run_tree(monkeypatch, _RunTree("run-eval-42"))

    tracer = tracer_mod.Tracer(enabled=True)
    tracer.trace_evaluator(_minimal_state(), immediate_reward=0.8)

    assert len(adds) == 1
    row = adds[0]
    assert row.langsmith_run_id == "run-eval-42"
    # Existing fields must still be populated so the change is purely
    # additive.
    assert row.score == pytest.approx(8.0)
    assert row.passed is True
    assert row.immediate_reward == pytest.approx(0.8)


def test_trace_evaluator_writes_null_run_id_when_tracing_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adds = _patch_db(monkeypatch)
    _patch_run_tree(monkeypatch, None)

    tracer = tracer_mod.Tracer(enabled=True)
    tracer.trace_evaluator(_minimal_state(), immediate_reward=0.5)

    assert len(adds) == 1
    assert adds[0].langsmith_run_id is None


def test_trace_evaluator_embeds_llm_timing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core import timing

    adds = _patch_db(monkeypatch)
    _patch_run_tree(monkeypatch, None)

    token = timing.start_timing_trace()
    try:
        timing.record_llm_timing_event(
            role="evaluator",
            provider="deepseek",
            model="deepseek-v4-flash",
            status="success",
            elapsed_ms=1234,
            input_chars=1000,
            output_chars=300,
            messages=2,
            json_mode=True,
            max_tokens=1024,
            request_timeout=45.0,
            attempts=1,
            base_host="api.deepseek.com",
        )
        tracer_mod.Tracer(enabled=True).trace_evaluator(
            _minimal_state(),
            immediate_reward=0.5,
            node_elapsed_ms=1500,
        )
    finally:
        timing.reset_timing_trace(token)

    snapshot = adds[0].state_snapshot
    assert snapshot["timing"]["node_elapsed_ms"] == 1500
    assert snapshot["timing"]["llm_calls"][0]["role"] == "evaluator"
    assert snapshot["timing"]["llm_calls"][0]["elapsed_ms"] == 1234


def test_trace_director_sample_writes_run_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adds = _patch_db(monkeypatch)
    _patch_run_tree(monkeypatch, _RunTree("run-dir-7"))

    tracer = tracer_mod.Tracer(enabled=True)
    state = _minimal_state()
    state["dimension_status"] = {}
    tracer.trace_director_sample(state)

    assert len(adds) == 1
    row = adds[0]
    assert row.node == "director_sample"
    assert row.langsmith_run_id == "run-dir-7"


def test_trace_node_event_writes_generic_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adds = _patch_db(monkeypatch)
    _patch_run_tree(monkeypatch, _RunTree("run-node-9"))

    tracer = tracer_mod.Tracer(enabled=True)
    tracer.trace_node_event(
        _minimal_state(),
        node="verification",
        payload={"verdict": "partial"},
    )

    assert len(adds) == 1
    row = adds[0]
    assert row.node == "verification"
    assert row.langsmith_run_id == "run-node-9"
    assert row.state_snapshot["payload"] == {"verdict": "partial"}


def test_ask_question_trace_node_event_drops_stale_answer_and_evaluation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adds = _patch_db(monkeypatch)
    _patch_run_tree(monkeypatch, _RunTree("run-ask-1"))

    tracer = tracer_mod.Tracer(enabled=True)
    tracer.trace_node_event(
        _minimal_state(),
        node="ask_question",
        payload={"plan_template": "adaptive", "selection_artifacts": {}},
    )

    assert len(adds) == 1
    row = adds[0]
    assert row.node == "ask_question"
    assert row.question == "Q?"
    assert row.answer is None
    assert row.evaluation is None
    assert row.state_snapshot["payload"] == {
        "plan_template": "adaptive",
        "selection_artifacts": {},
    }
    assert "current_answer" not in row.state_snapshot["state"]


def test_trace_node_event_embeds_llm_timing_in_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core import timing

    adds = _patch_db(monkeypatch)
    _patch_run_tree(monkeypatch, None)

    token = timing.start_timing_trace()
    try:
        timing.record_llm_timing_event(
            role="contract_negotiator",
            provider="qwen",
            model="qwen3.6-plus",
            status="success",
            elapsed_ms=2345,
            input_chars=1800,
            output_chars=500,
            messages=2,
            json_mode=True,
            max_tokens=1024,
            request_timeout=45.0,
            attempts=1,
            base_host="dashscope.aliyuncs.com",
        )
        tracer_mod.Tracer(enabled=True).trace_node_event(
            _minimal_state(),
            node="ask_question",
            payload={"plan_template": "adaptive", "elapsed_ms": 2600},
        )
    finally:
        timing.reset_timing_trace(token)

    payload = adds[0].state_snapshot["payload"]
    assert payload["elapsed_ms"] == 2600
    assert payload["timing"]["llm_calls"][0]["role"] == "contract_negotiator"
    assert payload["timing"]["llm_calls"][0]["elapsed_ms"] == 2345


def test_trace_write_failure_counter_increments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    @contextmanager
    def broken_session():
        raise RuntimeError("db down")
        yield  # pragma: no cover

    monkeypatch.setattr(tracer_mod, "get_session", broken_session)
    monkeypatch.setattr(tracer_mod, "_ensure_db", lambda: None)

    before = tracer_mod.trace_write_failures_total("evaluator")
    tracer_mod.Tracer(enabled=True).trace_evaluator(
        _minimal_state(),
        immediate_reward=0.5,
    )

    assert tracer_mod.trace_write_failures_total("evaluator") == before + 1
