from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.engine.workflow.nodes import experience_extractor as ex
from app.models.base import Base
from app.models.strategy_memory import StrategySignal


def _patch_signal_db(monkeypatch):
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)

    @contextmanager
    def get_session():
        with Session() as sess:
            yield sess
            sess.commit()

    monkeypatch.setattr(ex, "get_session", get_session)
    return Session


def test_qa_pattern_memory_key_makes_extraction_idempotent(
    monkeypatch,
) -> None:
    Session = _patch_signal_db(monkeypatch)

    class _Settings:
        experience_score_spread_threshold = 1.0
        experience_min_observations = 99
        experience_high_reward_mean = 0.8
        experience_low_reward_mean = 0.2

    monkeypatch.setattr(ex, "get_settings", lambda: _Settings())
    monkeypatch.setattr(ex, "_extract_bandit_insights", lambda: [])
    monkeypatch.setattr(ex, "increment_session_count", lambda: None)

    traced: list[dict[str, Any]] = []

    class _Tracer:
        def trace_node_event(self, _state, *, node, payload, **_kwargs):
            traced.append({"node": node, "payload": payload})

    monkeypatch.setattr(ex, "get_tracer", lambda: _Tracer())

    state = {
        "session_id": "sess",
        "trace_id": "trace",
        "job_spec": {"level": "mid"},
        "qa_history": [
            {
                "dimension": "communication",
                "selected_action": "plan_hint",
                "evaluation": {"score": 4.0},
            },
            {
                "dimension": "communication",
                "selected_action": "plan_hint",
                "evaluation": {"score": 7.5},
            },
        ],
    }

    ex.experience_extractor_node(state)  # type: ignore[arg-type]
    ex.experience_extractor_node(state)  # type: ignore[arg-type]

    with Session() as sess:
        signals = list(sess.scalars(select(StrategySignal)))

    assert len(signals) == 1
    assert signals[0].signal_key == (
        "sess:qa:score_recovery:mid:communication:plan_hint"
    )
    assert signals[0].group_key == "qa:score_recovery:mid:communication:plan_hint"

    assert traced[0]["payload"]["saved"] == 1
    assert traced[0]["payload"]["skipped_existing"] == 0
    assert traced[0]["payload"]["candidates"] == 1
    assert traced[1]["payload"]["saved"] == 0
    assert traced[1]["payload"]["skipped_existing"] == 1
    assert traced[1]["payload"]["candidates"] == 1


def test_bandit_insight_memory_key_is_idempotent(monkeypatch) -> None:
    Session = _patch_signal_db(monkeypatch)

    monkeypatch.setattr(ex, "_extract_qa_patterns", lambda _state: [])
    monkeypatch.setattr(
        ex,
        "_extract_bandit_insights",
        lambda: [
            {
                "type": "high_reward_arm",
                "context_key": "java_backend:senior:system_design",
                "action_id": "plan_deep_probe",
                "action_label": "Plan: Deep Probe",
                "mean_reward": 0.91,
                "observations": 8,
            }
        ],
    )
    monkeypatch.setattr(ex, "increment_session_count", lambda: None)

    payloads: list[dict[str, Any]] = []

    class _Tracer:
        def trace_node_event(self, _state, *, node, payload, **_kwargs):
            payloads.append(payload)

    monkeypatch.setattr(ex, "get_tracer", lambda: _Tracer())

    state = {"session_id": "sess", "trace_id": "trace", "qa_history": []}

    ex.experience_extractor_node(state)  # type: ignore[arg-type]
    ex.experience_extractor_node(state)  # type: ignore[arg-type]

    with Session() as sess:
        signals = list(sess.scalars(select(StrategySignal)))

    assert len(signals) == 1
    assert signals[0].group_key == (
        "bandit:high_reward_arm:"
        "java_backend:senior:system_design:plan_deep_probe"
    )
    assert payloads[0]["saved_keys"] == [
        "sess:bandit:high_reward_arm:java_backend:senior:system_design:plan_deep_probe"
    ]
    assert payloads[1]["skipped_existing"] == 1


def test_experience_extractor_counts_failed_candidates(monkeypatch) -> None:
    monkeypatch.setattr(
        ex,
        "_extract_qa_patterns",
        lambda _state: [
            {
                "type": "score_recovery",
                "dimension": "technical_depth",
                "job_level": "mid",
                "recovery_action": "plan_adaptive",
                "score_delta": 3.0,
                "detail": "safe detail",
            }
        ],
    )
    monkeypatch.setattr(ex, "_extract_bandit_insights", lambda: [])
    monkeypatch.setattr(
        ex,
        "_persist_strategy_signal",
        lambda _payload: (_ for _ in ()).throw(RuntimeError("db full")),
    )
    monkeypatch.setattr(ex, "increment_session_count", lambda: None)

    payloads: list[dict[str, Any]] = []

    class _Tracer:
        def trace_node_event(self, _state, *, node, payload, **_kwargs):
            payloads.append(payload)

    monkeypatch.setattr(ex, "get_tracer", lambda: _Tracer())

    ex.experience_extractor_node({"session_id": "sess"})  # type: ignore[arg-type]

    assert payloads[0]["saved"] == 0
    assert payloads[0]["failed"] == 1
    assert payloads[0]["candidates"] == 1


def test_experience_extractor_trace_groups_qa_and_bandit_counts(monkeypatch) -> None:
    monkeypatch.setattr(
        ex,
        "_extract_qa_patterns",
        lambda _state, qa_history=None: [
            {
                "type": "score_recovery",
                "dimension": "communication",
                "job_level": "junior",
                "recovery_action": "plan_hint",
            },
            {
                "type": "score_decline",
                "dimension": "communication",
                "job_level": "junior",
                "decline_action": "plan_simple",
            },
        ],
    )
    monkeypatch.setattr(
        ex,
        "_extract_bandit_insights",
        lambda: (
            [
                {
                    "type": "high_reward_arm",
                    "context_key": "java_backend:junior:communication",
                    "action_id": "plan_hint",
                    "mean_reward": 0.88,
                    "observations": 12,
                }
            ],
            "posterior",
        ),
    )

    def persist(payload):
        signal_type = payload.get("signal_type")
        if signal_type == "score_recovery":
            return "saved", "qa-saved"
        if signal_type == "score_decline":
            return "skipped_existing", "qa-skipped"
        return "saved", "bandit-saved"

    monkeypatch.setattr(ex, "_persist_strategy_signal", persist)
    monkeypatch.setattr(ex, "increment_session_count", lambda: None)

    payloads: list[dict[str, Any]] = []

    class _Tracer:
        def trace_node_event(self, _state, *, node, payload, **_kwargs):
            payloads.append(payload)

    monkeypatch.setattr(ex, "get_tracer", lambda: _Tracer())

    ex.experience_extractor_node({"session_id": "sess", "qa_history": []})  # type: ignore[arg-type]

    payload = payloads[0]
    assert payload["candidates"] == 3
    assert payload["saved"] == 2
    assert payload["skipped_existing"] == 1
    assert payload["qa_candidates"] == 2
    assert payload["qa_saved"] == 1
    assert payload["qa_skipped_existing"] == 1
    assert payload["qa_failed"] == 0
    assert payload["bandit_candidates"] == 1
    assert payload["bandit_saved"] == 1
    assert payload["bandit_skipped_existing"] == 0
    assert payload["bandit_failed"] == 0
    assert payload["saved_keys"] == ["qa-saved", "bandit-saved"]
    assert payload["skipped_keys"] == ["qa-skipped"]
    assert payload["bandit_source"] == "posterior"


def test_qa_pattern_hint_effective_accepts_plan_hint(monkeypatch) -> None:
    class _Settings:
        experience_score_spread_threshold = 3.0
        experience_min_observations = 99
        experience_high_reward_mean = 0.8
        experience_low_reward_mean = 0.2

    monkeypatch.setattr(ex, "get_settings", lambda: _Settings())

    patterns = ex._extract_qa_patterns(  # noqa: SLF001
        {
            "job_spec": {"level": "junior"},
            "qa_history": [
                {
                    "dimension": "communication",
                    "selected_action": "plan_hint",
                    "evaluation": {"score": 7.2},
                },
                {
                    "dimension": "communication",
                    "selected_action": "plan_hint",
                    "evaluation": {"score": 7.4},
                },
            ],
        }
    )

    assert patterns == [
        {
            "type": "hint_effective",
            "dimension": "communication",
            "job_level": "junior",
            "hint_action": "plan_hint",
            "avg_hint_score": 7.3,
            "detail": (
                "'plan_hint' was effective in communication "
                "(avg score 7.3 across 2 uses)."
            ),
        }
    ]


def test_qa_hint_effective_payload_uses_plan_hint_action() -> None:
    payload = ex._signal_payload_from_qa_pattern(  # noqa: SLF001
        {
            "session_id": "sess",
            "turn_idx": 2,
            "qa_history": [],
        },
        {
            "type": "hint_effective",
            "dimension": "communication",
            "job_level": "junior",
            "hint_action": "plan_hint",
            "avg_hint_score": 7.3,
        },
    )

    assert payload["action_id"] == "plan_hint"
    assert payload["plan_template"] == "plan_hint"
    assert payload["original_action_id"] == "plan_hint"
