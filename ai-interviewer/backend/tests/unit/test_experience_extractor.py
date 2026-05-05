from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from app.engine.workflow.nodes import experience_extractor as ex
from app.memory import strategy_store as ss


def _patch_strategy_dir(tmp_path, monkeypatch):
    strategy_dir = tmp_path / "strategy"
    strategy_dir.mkdir()
    settings = SimpleNamespace(knowledge_dir=tmp_path)
    monkeypatch.setattr(ss, "get_settings", lambda: settings)
    monkeypatch.setattr(ex, "list_strategies", ss.list_strategies)
    monkeypatch.setattr(ex, "save_strategy", ss.save_strategy)
    return strategy_dir


def test_qa_pattern_memory_key_makes_extraction_idempotent(
    tmp_path,
    monkeypatch,
) -> None:
    strategy_dir = _patch_strategy_dir(tmp_path, monkeypatch)

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

    strategy_files = [
        p for p in strategy_dir.glob("*.md") if p.name != "MEMORY.md"
    ]
    assert len(strategy_files) == 1
    text = strategy_files[0].read_text(encoding="utf-8")
    assert "memory_key: qa:score_recovery:mid:communication:plan_hint" in text

    assert traced[0]["payload"]["saved"] == 1
    assert traced[0]["payload"]["skipped_existing"] == 0
    assert traced[0]["payload"]["candidates"] == 1
    assert traced[1]["payload"]["saved"] == 0
    assert traced[1]["payload"]["skipped_existing"] == 1
    assert traced[1]["payload"]["candidates"] == 1


def test_bandit_insight_memory_key_is_idempotent(tmp_path, monkeypatch) -> None:
    strategy_dir = _patch_strategy_dir(tmp_path, monkeypatch)

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

    strategy_files = [
        p for p in strategy_dir.glob("*.md") if p.name != "MEMORY.md"
    ]
    assert len(strategy_files) == 1
    text = strategy_files[0].read_text(encoding="utf-8")
    assert (
        "memory_key: bandit:high_reward_arm:"
        "java_backend:senior:system_design:plan_deep_probe"
    ) in text
    assert payloads[0]["saved_keys"] == [
        "bandit:high_reward_arm:java_backend:senior:system_design:plan_deep_probe"
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
    monkeypatch.setattr(ex, "strategy_exists_by_memory_key", lambda _key: False)
    monkeypatch.setattr(ex, "save_strategy", lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("disk full")))
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
