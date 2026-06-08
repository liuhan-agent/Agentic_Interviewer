"""Tests for the ``verification_node`` drift-persistence dual write.

PR2 of the drift-feedback persistence track: when
``enable_verifier_drift_persistence`` is on, ``verification_node`` keeps
calling ``monitor.record(event)`` AND inserts a :class:`VerifierDriftEvent`
row so the post-process aggregator can read historical drift across
restarts. The persistence path is best-effort: a DB failure must not
propagate into the workflow because verification observability is not
a decision input.
"""
from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
from app.models.verifier_drift import VerifierDriftEvent


def _session_factory():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)


def _state_with_overrule(**overrides: Any) -> dict[str, Any]:
    state: dict[str, Any] = {
        "session_id": "sess-drift",
        "trace_id": "trace-drift",
        "turn_idx": 3,
        "current_dimension": "system_design",
        "current_question": {
            "question": "请讲一次系统设计取舍。",
            "dimension": "system_design",
            "contract": {
                "must_cover": ["scale"],
                "acceptance_checks": ["Mentions concrete failure modes"],
            },
        },
        "current_contract": {
            "must_cover": ["scale"],
            "acceptance_checks": ["Mentions concrete failure modes"],
        },
        "evaluation": {
            "score": 8.5,
            "passed": True,
            "acceptance_check_results": {
                "Mentions concrete failure modes": {
                    "verdict": "yes",
                    "evidence": ["we used Redis", "cache layer scales"],
                },
            },
            "failure_categories": ["missing_metrics", "unclear_architecture"],
        },
        "current_answer": "we used Redis",
        "job_spec": {"level": "senior"},
        "dimension_status": {"system_design": "active"},
        "quality_threshold": 7.5,
    }
    state.update(overrides)
    return state


def _verification_payload() -> dict[str, Any]:
    return {
        "verifier_available": True,
        "verdict": "partial",
        "confidence": 0.85,
        "reasons_to_doubt": ["evidence is generic boilerplate"],
    }


def _install_common_patches(monkeypatch, *, persistence: bool, get_session) -> None:
    from app.engine.workflow.nodes import verification as verification_mod

    monkeypatch.setattr(verification_mod, "should_trigger", lambda **_kw: True)
    monkeypatch.setattr(
        verification_mod, "verify_answer", lambda **_kw: _verification_payload()
    )
    monkeypatch.setattr(
        verification_mod,
        "get_raw_answer_for_state",
        lambda state: state.get("current_answer", ""),
    )
    monkeypatch.setattr(
        verification_mod,
        "get_settings",
        lambda: SimpleNamespace(
            enable_verifier_drift_monitor=True,
            enable_verifier_drift_persistence=persistence,
            verifier_min_override_confidence=0.6,
        ),
    )
    monkeypatch.setattr(verification_mod, "get_session", get_session)

    class _Monitor:
        def record(self, _event: Any) -> None:
            return None

    monkeypatch.setattr(
        "app.ml.drift.verifier_drift.get_verifier_drift_monitor",
        lambda: _Monitor(),
    )

    class _Tracer:
        def trace_node_event(self, *_args: Any, **_kwargs: Any) -> None:
            return None

    monkeypatch.setattr(verification_mod, "get_tracer", lambda: _Tracer())


def test_verification_does_not_persist_drift_when_flag_off(monkeypatch) -> None:
    from app.engine.workflow.nodes import verification as verification_mod

    Session = _session_factory()

    @contextmanager
    def get_session():
        with Session() as sess:
            yield sess
            sess.commit()

    _install_common_patches(monkeypatch, persistence=False, get_session=get_session)

    verification_mod.verification_node(_state_with_overrule())  # type: ignore[arg-type]

    with Session() as sess:
        events = list(sess.scalars(select(VerifierDriftEvent)))

    assert events == []


def test_verification_rejoins_acceptance_check_result_items(monkeypatch) -> None:
    from app.engine.workflow.nodes import verification as verification_mod

    Session = _session_factory()

    @contextmanager
    def get_session():
        with Session() as sess:
            yield sess
            sess.commit()

    _install_common_patches(monkeypatch, persistence=False, get_session=get_session)
    captured: dict[str, Any] = {}

    def fake_verify_answer(**kwargs) -> dict[str, Any]:
        captured["scoring_contract"] = kwargs.get("contract")
        return _verification_payload()

    monkeypatch.setattr(verification_mod, "verify_answer", fake_verify_answer)
    state = _state_with_overrule(
        current_contract={
            "must_cover": ["scale"],
            "acceptance_checks": ["Mentions concrete failure modes"],
            "acceptance_check_items": [
                {
                    "check_id": "reviewed:failure-modes",
                    "text": "Mentions concrete failure modes",
                    "source": "reviewed",
                    "severity": "core",
                    "source_text": "failure modes",
                    "origin": "question_variant",
                    "seed_ref": {"seed_id": "seed"},
                    "metadata": {"criterion_source": "must_cover"},
                },
                {
                    "check_id": "reviewed:support:impact",
                    "text": "Explains operational impact",
                    "source": "reviewed",
                    "severity": "supporting",
                    "source_text": "impact",
                    "origin": "question_variant",
                },
                {
                    "check_id": "adaptive:project-context",
                    "text": "Connects the answer to the resume project",
                    "source": "adaptive_context",
                    "severity": "supporting",
                    "source_text": "",
                    "origin": "negotiated_contract",
                }
            ],
        }
    )
    state["evaluation"]["acceptance_check_results"] = {
        "Mentions concrete failure modes": {
            "verdict": "yes",
            "evidence": ["failure modes"],
        },
        "Explains operational impact": {
            "verdict": "partial",
            "evidence": ["latency impact"],
        },
        "Connects the answer to the resume project": {
            "verdict": "no",
            "evidence": [],
        },
    }

    update = verification_mod.verification_node(state)  # type: ignore[arg-type]

    items = update["evaluation"]["acceptance_check_result_items"]
    assert items[0]["check_id"] == "reviewed:failure-modes"
    assert items[0]["source"] == "reviewed"
    assert items[0]["severity"] == "core"
    assert items[0]["verdict"] == "yes"
    assert items[0]["result_present"] is True
    gate = update["evaluation"]["contract_gate_result"]
    assert gate["status"] == "passed"
    assert gate["eligible_count"] == 1
    assert gate["satisfied_count"] == 1
    assert gate["failed_count"] == 0
    summary = update["evaluation"]["contract_semantics_summary"]
    assert summary["reviewed_core"]["yes"] == 1
    assert summary["hard_gap_count"] == 0
    suggestions = update["evaluation"]["soft_gap_training_suggestions"]
    assert suggestions["counts"] == {"quality": 1, "context": 1, "total": 2}
    assert suggestions["quality_suggestions"][0]["check_id"] == (
        "reviewed:support:impact"
    )
    assert suggestions["context_suggestions"][0]["check_id"] == (
        "adaptive:project-context"
    )
    hints = update["evaluation"]["soft_followup_hints"]
    assert hints["mode"] == "shadow"
    assert hints["applied"] is False
    assert hints["quality_hints"][0]["intent"] == "probe_quality_gap"
    assert hints["context_hints"][0]["intent"] == "probe_context_gap"
    assert "acceptance_check_items" not in captured["scoring_contract"]
    assert captured["scoring_contract"]["acceptance_check_items_for_prompt"] == [
        {
            "check_id": "reviewed:failure-modes",
            "text": "Mentions concrete failure modes",
            "source": "reviewed",
            "severity": "core",
        },
        {
            "check_id": "reviewed:support:impact",
            "text": "Explains operational impact",
            "source": "reviewed",
            "severity": "supporting",
        },
        {
            "check_id": "adaptive:project-context",
            "text": "Connects the answer to the resume project",
            "source": "adaptive_context",
            "severity": "supporting",
        }
    ]


def test_verification_persists_drift_event_when_flag_on(monkeypatch) -> None:
    from app.engine.workflow.nodes import verification as verification_mod

    Session = _session_factory()

    @contextmanager
    def get_session():
        with Session() as sess:
            yield sess
            sess.commit()

    _install_common_patches(monkeypatch, persistence=True, get_session=get_session)

    verification_mod.verification_node(_state_with_overrule())  # type: ignore[arg-type]

    with Session() as sess:
        events = list(sess.scalars(select(VerifierDriftEvent)))

    assert len(events) == 1
    event = events[0]
    assert event.session_id == "sess-drift"
    assert event.trace_id == "trace-drift"
    assert event.turn_idx == 2  # answer_turn_idx = turn_idx - 1
    assert event.dimension == "system_design"
    assert event.job_level == "senior"
    assert event.evaluator_passed is True
    assert event.verifier_verdict == "partial"
    assert event.verifier_confidence == 0.85
    assert event.verifier_abstained is False
    assert event.overruled is True
    assert event.overruled_check_name == "Mentions concrete failure modes"
    assert event.evaluator_evidence_quotes == [
        "we used Redis",
        "cache layer scales",
    ]
    assert event.verifier_reasons == ["evidence is generic boilerplate"]
    assert event.failure_categories == [
        "missing_metrics",
        "unclear_architecture",
    ]


def test_verification_drift_db_failure_does_not_break_node(monkeypatch) -> None:
    """Best-effort: DB raising still lets the workflow return a clean
    state update so the LangGraph turn completes."""
    from app.engine.workflow.nodes import verification as verification_mod

    @contextmanager
    def broken_session():  # noqa: D401 - test helper
        raise RuntimeError("DB unavailable")
        yield None  # pragma: no cover

    _install_common_patches(
        monkeypatch, persistence=True, get_session=broken_session
    )

    update = verification_mod.verification_node(_state_with_overrule())  # type: ignore[arg-type]

    assert "evaluation" in update
    assert update["evaluation"]["passed"] is False
    assert update["evaluation"]["recommended_next"] == "refine"


def test_verification_drift_event_id_is_deterministic(monkeypatch) -> None:
    """Same (session, turn, dimension, check) must produce the same id
    so re-running a turn doesn't double-count events."""
    from app.engine.workflow.nodes import verification as verification_mod

    Session = _session_factory()

    @contextmanager
    def get_session():
        with Session() as sess:
            yield sess
            sess.commit()

    _install_common_patches(monkeypatch, persistence=True, get_session=get_session)

    state = _state_with_overrule()
    verification_mod.verification_node(state)  # type: ignore[arg-type]
    verification_mod.verification_node(state)  # type: ignore[arg-type]

    with Session() as sess:
        events = list(sess.scalars(select(VerifierDriftEvent)))

    assert len(events) == 1
    assert events[0].overruled is True
