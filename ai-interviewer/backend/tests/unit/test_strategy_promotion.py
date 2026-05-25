from __future__ import annotations

from datetime import datetime

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.models.base import Base
from app.models.strategy_memory import StrategyMemory, StrategySignal
from app.services.strategy_promotion import (
    StrategyPromotionResult,
    promote_strategy_signals,
)


def _session_factory():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)


def _add_signal(
    sess: Session,
    *,
    idx: int,
    group_key: str = "qa:score_recovery:senior:system_design:plan_hint",
    reward: float | None = None,
    score_before: float | None = 5.0,
    score_after: float | None = 8.5,
    score_delta: float | None = 3.5,
    overruled: bool = False,
    signal_type: str = "score_recovery",
    action_id: str = "plan_hint",
) -> None:
    sess.add(
        StrategySignal(
            id=f"signal-{idx}",
            signal_key=f"sess-{idx}:{group_key}",
            group_key=group_key,
            session_id=f"sess-{idx}",
            turn_idx=idx,
            dimension="system_design",
            job_level="senior",
            action_id=action_id,
            plan_template="simple",
            probe_intent="metric_probe",
            failure_categories=["missing_metrics"],
            score_before=score_before,
            score_after=score_after,
            score_delta=score_delta,
            immediate_reward=reward,
            verifier_overruled=overruled,
            signal_type=signal_type,
            status="observed",
        )
    )


def test_promote_strategy_signals_ignores_under_supported_groups() -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as sess:
        for idx in range(1, 10):
            _add_signal(sess, idx=idx)
        result = promote_strategy_signals(session=sess)
        sess.commit()
        memories = list(sess.scalars(select(StrategyMemory)))

    assert result.promoted == 0
    assert result.skipped == 1
    assert memories == []


def test_promote_strategy_signals_creates_low_confidence_active_strategy_from_qa_recovery_without_reward() -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as sess:
        for idx in range(1, 31):
            _add_signal(sess, idx=idx)
        result = promote_strategy_signals(session=sess)
        second = promote_strategy_signals(session=sess)
        sess.commit()

        memories = list(sess.scalars(select(StrategyMemory)))
        signals = list(sess.scalars(select(StrategySignal)))

    assert result.promoted == 1
    assert second.unchanged == 1
    assert len(memories) == 1

    memory = memories[0]
    assert memory.id.startswith("promoted:")
    assert memory.source == "promoted_signal"
    assert memory.status == "active"
    assert memory.promotion_stage == "low_confidence"
    assert memory.dimensions == ["system_design"]
    assert memory.job_levels == ["senior"]
    assert memory.failure_categories == ["missing_metrics"]
    assert memory.recommended_action == "plan_hint"
    assert memory.recommended_plan_template == "plan_hint"
    assert memory.recommended_probe_intent == "metric_probe"
    assert memory.support_count == 30
    assert memory.confidence == 0.35
    assert "## 适用场景" in memory.body_markdown
    assert "## 推荐动作" in memory.body_markdown
    assert "## 使用方式" in memory.body_markdown
    assert "## 证据" in memory.body_markdown
    assert "## 使用边界" in memory.body_markdown
    assert "- 维度：`system_design`" in memory.body_markdown
    assert "- 级别：`senior`" in memory.body_markdown
    assert "- 失败类型：`missing_metrics`" in memory.body_markdown
    assert "- 信号类型：`score_recovery`" in memory.body_markdown
    assert "- action：`plan_hint`" in memory.body_markdown
    assert "- probe_intent：`metric_probe`" in memory.body_markdown
    assert "- 支持 session：30" in memory.body_markdown
    assert "- 平均后验分：8.50" in memory.body_markdown
    assert "- 平均分数提升：3.50" in memory.body_markdown
    assert "- Verifier 否决率：0%" in memory.body_markdown
    assert "- 晋升阶段：`low_confidence`" in memory.body_markdown
    assert "同维度、同级别、相似失败类型" in memory.body_markdown
    assert "只在相近上下文使用" in memory.body_markdown
    assert "Average QA score delta" not in memory.body_markdown
    assert "Average immediate reward" not in memory.body_markdown

    assert {signal.status for signal in signals} == {"promoted"}


def test_qa_recovery_requires_post_score_delta_and_overrule_thresholds() -> None:
    cases = [
        {"score_after": 6.9, "score_delta": 3.5},
        {"score_after": 8.5, "score_delta": 2.9},
        {"score_after": 8.5, "score_delta": 3.5, "overruled": True},
    ]

    for case_idx, kwargs in enumerate(cases, start=1):
        SessionLocal = _session_factory()
        with SessionLocal() as sess:
            for idx in range(1, 31):
                _add_signal(
                    sess,
                    idx=idx,
                    group_key=(
                        "qa:score_recovery:senior:"
                        f"system_design:plan_hint_{case_idx}"
                    ),
                    action_id=f"plan_hint_{case_idx}",
                    **kwargs,
                )
            result = promote_strategy_signals(session=sess)
            sess.commit()
            memories = list(sess.scalars(select(StrategyMemory)))

        assert result.promoted == 0
        assert result.skipped == 1
        assert memories == []


def test_qa_hint_effective_promotes_without_score_delta() -> None:
    SessionLocal = _session_factory()
    group_key = "qa:hint_effective:senior:system_design"
    with SessionLocal() as sess:
        for idx in range(1, 31):
            _add_signal(
                sess,
                idx=idx,
                group_key=group_key,
                score_after=7.2,
                score_delta=None,
                signal_type="hint_effective",
                action_id="give_hint",
            )
        result = promote_strategy_signals(session=sess)
        sess.commit()
        memory = sess.scalar(select(StrategyMemory))

    assert result.promoted == 1
    assert memory is not None
    assert memory.recommended_action == "plan_hint"
    assert memory.recommended_plan_template == "plan_hint"
    assert "## 证据" in memory.body_markdown
    assert "- 信号类型：`hint_effective`" in memory.body_markdown
    assert "- action：`plan_hint`" in memory.body_markdown
    assert "- 平均 hint 后得分：7.20" in memory.body_markdown
    assert "平均 reward" not in memory.body_markdown
    assert "平均分数提升" not in memory.body_markdown


def test_promoted_strategy_memory_canonicalizes_legacy_signal_action() -> None:
    SessionLocal = _session_factory()
    group_key = "qa:score_recovery:senior:system_design:plan_switch"
    with SessionLocal() as sess:
        for idx in range(1, 31):
            _add_signal(
                sess,
                idx=idx,
                group_key=group_key,
                action_id="switch_dimension",
                signal_type="score_recovery",
            )
        result = promote_strategy_signals(session=sess)
        sess.commit()
        memory = sess.scalar(select(StrategyMemory))

    assert result.promoted == 1
    assert memory is not None
    assert memory.recommended_action == "plan_switch"
    assert memory.recommended_plan_template == "plan_switch"
    assert memory.memory_key == f"promoted:{group_key}"


def test_negative_qa_decline_signal_is_not_promoted() -> None:
    SessionLocal = _session_factory()
    group_key = "qa:score_decline:senior:system_design:plan_hint"
    with SessionLocal() as sess:
        for idx in range(1, 101):
            _add_signal(
                sess,
                idx=idx,
                group_key=group_key,
                score_before=8.5,
                score_after=5.0,
                score_delta=-3.5,
                signal_type="score_decline",
            )
        result = promote_strategy_signals(session=sess)
        sess.commit()
        memories = list(sess.scalars(select(StrategyMemory)))
        signals = list(sess.scalars(select(StrategySignal)))

    assert result.promoted == 0
    assert result.skipped == 1
    assert memories == []
    assert {signal.status for signal in signals} == {"observed"}


def test_high_reward_bandit_promotes_without_post_score() -> None:
    SessionLocal = _session_factory()
    group_key = "bandit:high_reward_arm:senior:system_design:plan_deep_probe"
    with SessionLocal() as sess:
        for idx in range(1, 31):
            _add_signal(
                sess,
                idx=idx,
                group_key=group_key,
                reward=0.74,
                score_before=None,
                score_after=None,
                score_delta=None,
                signal_type="high_reward_arm",
                action_id="plan_deep_probe",
            )
        result = promote_strategy_signals(session=sess)
        sess.commit()
        memory = sess.scalar(select(StrategyMemory))

    assert result.promoted == 1
    assert memory is not None
    assert memory.promotion_stage == "low_confidence"
    assert memory.confidence > 0.35
    assert "## 适用场景" in memory.body_markdown
    assert "## 推荐动作" in memory.body_markdown
    assert "## 证据" in memory.body_markdown
    assert "- group_key：`bandit:high_reward_arm:senior:system_design:plan_deep_probe`" in memory.body_markdown
    assert "- action：`plan_deep_probe`" in memory.body_markdown
    assert "- 平均 reward：0.74" in memory.body_markdown
    assert "- 晋升阶段：`low_confidence`" in memory.body_markdown
    assert "平均后验分" not in memory.body_markdown
    assert "平均分数提升" not in memory.body_markdown


def test_negative_low_reward_bandit_signal_is_not_promoted() -> None:
    SessionLocal = _session_factory()
    group_key = "bandit:low_reward_arm:senior:system_design:plan_deep_probe"
    with SessionLocal() as sess:
        for idx in range(1, 101):
            _add_signal(
                sess,
                idx=idx,
                group_key=group_key,
                reward=0.2,
                score_before=None,
                score_after=None,
                score_delta=None,
                signal_type="low_reward_arm",
                action_id="plan_deep_probe",
            )
        result = promote_strategy_signals(session=sess)
        sess.commit()
        memories = list(sess.scalars(select(StrategyMemory)))

    assert result.promoted == 0
    assert result.skipped == 1
    assert memories == []


def test_positive_qa_and_bandit_groups_can_promote_directly_to_stable() -> None:
    SessionLocal = _session_factory()
    qa_group_key = "qa:score_recovery:senior:system_design:plan_hint"
    bandit_group_key = "bandit:high_reward_arm:senior:system_design:plan_deep_probe"
    with SessionLocal() as sess:
        for idx in range(1, 101):
            _add_signal(sess, idx=idx, group_key=qa_group_key)
        for idx in range(101, 201):
            _add_signal(
                sess,
                idx=idx,
                group_key=bandit_group_key,
                reward=0.74,
                score_before=None,
                score_after=None,
                score_delta=None,
                signal_type="high_reward_arm",
                action_id="plan_deep_probe",
            )
        result = promote_strategy_signals(session=sess)
        sess.commit()
        memories = list(sess.scalars(select(StrategyMemory)))

    assert result.promoted == 2
    assert {memory.promotion_stage for memory in memories} == {"stable"}
    assert {memory.confidence for memory in memories} == {0.75}


def test_run_strategy_promotion_now_wraps_service(monkeypatch) -> None:
    from app.tasks import strategy_promotion_tasks as tasks

    calls: list[str] = []

    class _Session:
        pass

    class _Context:
        def __enter__(self):
            calls.append("enter")
            return _Session()

        def __exit__(self, exc_type, exc, tb):
            calls.append("exit")
            return False

    monkeypatch.setattr(tasks, "get_session", lambda: _Context())
    monkeypatch.setattr(
        tasks,
        "refresh_strategy_memory_stats",
        lambda *, session: calls.append("refresh"),
        raising=False,
    )
    monkeypatch.setattr(
        tasks,
        "promote_strategy_signals",
        lambda *, session: calls.append("promote")
        or StrategyPromotionResult(promoted=1, unchanged=2, skipped=3),
    )
    monkeypatch.setattr(
        tasks,
        "apply_strategy_quality_transitions",
        lambda *, session: calls.append("quality")
        or StrategyPromotionResult(unchanged=4, disabled=5, stabilized=6),
    )

    result = tasks.run_strategy_promotion_now()

    assert calls == ["enter", "refresh", "promote", "quality", "exit"]
    assert result == {
        "promoted": 1,
        "unchanged": 6,
        "skipped": 3,
        "disabled": 5,
        "stabilized": 6,
    }


def test_strategy_promotion_scheduler_settings_default_disabled() -> None:
    from app.core.settings import Settings

    settings = Settings()

    assert settings.enable_strategy_promotion_scheduler is False
    assert settings.strategy_promotion_interval_minutes == 60
    assert settings.strategy_promotion_startup_delay_minutes == 5


def test_start_strategy_promotion_scheduler_registers_interval_job() -> None:
    from app.tasks.strategy_promotion_tasks import start_strategy_promotion_scheduler

    scheduler = start_strategy_promotion_scheduler(
        interval_minutes=7,
        startup_delay_minutes=3,
    )
    try:
        jobs = scheduler.get_jobs()
        assert [job.id for job in jobs] == ["strategy_promotion"]

        job = jobs[0]
        assert "0:07:00" in str(job.trigger)
        assert job.max_instances == 1
        assert job.coalesce is True

        seconds_until_first_run = (
            job.next_run_time - datetime.now(job.next_run_time.tzinfo)
        ).total_seconds()
        assert 120 <= seconds_until_first_run <= 240
    finally:
        scheduler.shutdown(wait=False)


def test_strategy_promotion_scheduler_tick_logs_success(monkeypatch) -> None:
    from app.tasks import strategy_promotion_tasks as tasks

    calls: list[str] = []
    logs: list[tuple[str, dict[str, int]]] = []
    result = {
        "promoted": 1,
        "unchanged": 2,
        "skipped": 3,
        "disabled": 4,
        "stabilized": 5,
    }

    monkeypatch.setattr(
        tasks,
        "run_strategy_promotion_now",
        lambda: calls.append("run") or result,
    )
    monkeypatch.setattr(
        tasks.log,
        "info",
        lambda msg, payload: logs.append((msg, payload)),
    )

    assert tasks._run_strategy_promotion_tick() == result
    assert calls == ["run"]
    assert logs == [("strategy promotion tick completed: %s", result)]


def test_strategy_promotion_scheduler_tick_swallows_and_logs_errors(
    monkeypatch,
) -> None:
    from app.tasks import strategy_promotion_tasks as tasks

    logs: list[str] = []

    def fail() -> dict[str, int]:
        raise RuntimeError("boom")

    monkeypatch.setattr(tasks, "run_strategy_promotion_now", fail)
    monkeypatch.setattr(
        tasks.log,
        "exception",
        lambda msg: logs.append(msg),
    )

    assert tasks._run_strategy_promotion_tick() is None
    assert logs == ["strategy promotion tick failed"]
