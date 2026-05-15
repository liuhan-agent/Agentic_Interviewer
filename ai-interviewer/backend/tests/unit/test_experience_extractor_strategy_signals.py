from __future__ import annotations

from contextlib import contextmanager

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
from app.models.strategy_memory import StrategySignal


def test_experience_extractor_writes_qa_pattern_as_strategy_signal(monkeypatch) -> None:
    from app.engine.workflow.nodes import experience_extractor as extractor

    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)

    @contextmanager
    def get_session():
        with Session() as sess:
            yield sess
            sess.commit()

    class _Settings:
        experience_score_spread_threshold = 3.0
        experience_min_observations = 5
        experience_high_reward_mean = 0.70
        experience_low_reward_mean = 0.30

    class _Bandit:
        priors = {}

    class _Tracer:
        def trace_node_event(self, *_args, **_kwargs) -> None:
            return None

    monkeypatch.setattr(extractor, "get_settings", lambda: _Settings())
    monkeypatch.setattr(extractor, "get_bandit", lambda: _Bandit())
    monkeypatch.setattr(extractor, "get_session", get_session)
    monkeypatch.setattr(extractor, "get_tracer", lambda: _Tracer())
    monkeypatch.setattr(extractor, "increment_session_count", lambda: None)

    state = {
        "session_id": "sess-signal",
        "trace_id": "trace-signal",
        "status": "completed",
        "job_spec": {"level": "senior"},
        "qa_history": [
            {
                "dimension": "system_design",
                "selected_action": "plan_hint",
                "evaluation": {"score": 5.0},
            },
            {
                "dimension": "system_design",
                "selected_action": "plan_hint",
                "evaluation": {"score": 8.5},
            },
        ],
    }

    extractor.experience_extractor_node(state)  # type: ignore[arg-type]

    with Session() as sess:
        signals = list(sess.scalars(select(StrategySignal)))

    assert len(signals) == 1
    signal = signals[0]
    assert signal.signal_key == (
        "sess-signal:qa:score_recovery:senior:system_design:plan_hint"
    )
    assert signal.group_key == "qa:score_recovery:senior:system_design:plan_hint"
    assert signal.session_id == "sess-signal"
    assert signal.dimension == "system_design"
    assert signal.job_level == "senior"
    assert signal.action_id == "plan_hint"
    assert signal.score_before == 5.0
    assert signal.score_after == 8.5
    assert signal.score_delta == 3.5
    assert signal.signal_type == "score_recovery"
    assert signal.status == "observed"


def test_experience_extractor_parses_direction_scoped_bandit_context(
    monkeypatch,
) -> None:
    from app.engine.workflow.nodes import experience_extractor as extractor

    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)

    @contextmanager
    def get_session():
        with Session() as sess:
            yield sess
            sess.commit()

    class _Settings:
        experience_score_spread_threshold = 3.0
        experience_min_observations = 5
        experience_high_reward_mean = 0.70
        experience_low_reward_mean = 0.30

    class _Params:
        alpha = 8.0
        beta = 2.0

        def mean(self) -> float:
            return 0.8

    class _Bandit:
        priors = {("java_backend:senior:system_design", "plan_deep_probe"): _Params()}

    class _Tracer:
        def trace_node_event(self, *_args, **_kwargs) -> None:
            return None

    monkeypatch.setattr(extractor, "get_settings", lambda: _Settings())
    monkeypatch.setattr(extractor, "get_bandit", lambda: _Bandit())
    monkeypatch.setattr(extractor, "get_session", get_session)
    monkeypatch.setattr(extractor, "get_tracer", lambda: _Tracer())
    monkeypatch.setattr(extractor, "increment_session_count", lambda: None)

    state = {
        "session_id": "sess-bandit-signal",
        "status": "completed",
        "job_spec": {"level": "senior", "interview_direction": "java_backend"},
        "qa_history": [],
    }

    extractor.experience_extractor_node(state)  # type: ignore[arg-type]

    with Session() as sess:
        signals = list(sess.scalars(select(StrategySignal)))

    assert len(signals) == 1
    signal = signals[0]
    assert signal.group_key == (
        "bandit:high_reward_arm:java_backend:senior:system_design:plan_deep_probe"
    )
    assert signal.job_level == "senior"
    assert signal.dimension == "system_design"
    assert signal.action_id == "plan_deep_probe"
    assert signal.immediate_reward == 0.8


def test_qa_pattern_signal_carries_failure_categories_from_last_dim_turn(
    monkeypatch,
) -> None:
    """PR3: when the dimension's last QA turn carries
    ``evaluation.failure_categories``, the persisted signal must carry
    the same legal subset so downstream aggregation can group signals
    by structured failure type instead of free-form text."""
    from app.engine.workflow.nodes import experience_extractor as extractor

    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)

    @contextmanager
    def get_session():
        with Session() as sess:
            yield sess
            sess.commit()

    class _Settings:
        experience_score_spread_threshold = 3.0
        experience_min_observations = 5
        experience_high_reward_mean = 0.70
        experience_low_reward_mean = 0.30

    class _Bandit:
        priors = {}

    class _Tracer:
        def trace_node_event(self, *_args, **_kwargs) -> None:
            return None

    monkeypatch.setattr(extractor, "get_settings", lambda: _Settings())
    monkeypatch.setattr(extractor, "get_bandit", lambda: _Bandit())
    monkeypatch.setattr(extractor, "get_session", get_session)
    monkeypatch.setattr(extractor, "get_tracer", lambda: _Tracer())
    monkeypatch.setattr(extractor, "increment_session_count", lambda: None)

    state = {
        "session_id": "sess-failcat",
        "status": "completed",
        "job_spec": {"level": "senior"},
        "qa_history": [
            {
                "dimension": "system_design",
                "selected_action": "plan_hint",
                "evaluation": {
                    "score": 5.0,
                    "failure_categories": ["missing_metrics"],
                },
            },
            {
                "dimension": "system_design",
                "selected_action": "plan_hint",
                "evaluation": {
                    "score": 8.5,
                    # The latest turn surfaces a different failure mix;
                    # the signal should reflect it, not the older one.
                    "failure_categories": ["missing_evidence", "weak_debugging"],
                },
            },
        ],
    }

    extractor.experience_extractor_node(state)  # type: ignore[arg-type]

    with Session() as sess:
        signals = list(sess.scalars(select(StrategySignal)))

    assert len(signals) == 1
    assert signals[0].failure_categories == [
        "missing_evidence",
        "weak_debugging",
    ]


def test_qa_pattern_signal_failure_categories_empty_when_missing(monkeypatch) -> None:
    """No ``failure_categories`` on the latest dimension turn means the
    signal carries ``[]`` — never ``None`` and never the older turn's
    stale categories."""
    from app.engine.workflow.nodes import experience_extractor as extractor

    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)

    @contextmanager
    def get_session():
        with Session() as sess:
            yield sess
            sess.commit()

    class _Settings:
        experience_score_spread_threshold = 3.0
        experience_min_observations = 5
        experience_high_reward_mean = 0.70
        experience_low_reward_mean = 0.30

    class _Bandit:
        priors = {}

    class _Tracer:
        def trace_node_event(self, *_args, **_kwargs) -> None:
            return None

    monkeypatch.setattr(extractor, "get_settings", lambda: _Settings())
    monkeypatch.setattr(extractor, "get_bandit", lambda: _Bandit())
    monkeypatch.setattr(extractor, "get_session", get_session)
    monkeypatch.setattr(extractor, "get_tracer", lambda: _Tracer())
    monkeypatch.setattr(extractor, "increment_session_count", lambda: None)

    state = {
        "session_id": "sess-failcat-empty",
        "status": "completed",
        "job_spec": {"level": "senior"},
        "qa_history": [
            {
                "dimension": "system_design",
                "selected_action": "plan_hint",
                "evaluation": {
                    "score": 5.0,
                    # Older turn HAS a category — it must NOT leak forward.
                    "failure_categories": ["missing_evidence"],
                },
            },
            {
                "dimension": "system_design",
                "selected_action": "plan_hint",
                "evaluation": {"score": 8.5},
            },
        ],
    }

    extractor.experience_extractor_node(state)  # type: ignore[arg-type]

    with Session() as sess:
        signals = list(sess.scalars(select(StrategySignal)))

    assert len(signals) == 1
    assert signals[0].failure_categories == []


def test_bandit_insight_signal_carries_failure_categories_from_qa_history(
    monkeypatch,
) -> None:
    """Bandit-driven insights also enrich themselves from the current
    session's last matching dimension turn — when one exists. No match
    -> empty list (bandit context can span sessions; we don't fabricate
    categories from somewhere else)."""
    from app.engine.workflow.nodes import experience_extractor as extractor

    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)

    @contextmanager
    def get_session():
        with Session() as sess:
            yield sess
            sess.commit()

    class _Settings:
        experience_score_spread_threshold = 3.0
        experience_min_observations = 5
        experience_high_reward_mean = 0.70
        experience_low_reward_mean = 0.30

    class _Params:
        alpha = 8.0
        beta = 2.0

        def mean(self) -> float:
            return 0.8

    class _Bandit:
        priors = {("java_backend:senior:system_design", "plan_deep_probe"): _Params()}

    class _Tracer:
        def trace_node_event(self, *_args, **_kwargs) -> None:
            return None

    monkeypatch.setattr(extractor, "get_settings", lambda: _Settings())
    monkeypatch.setattr(extractor, "get_bandit", lambda: _Bandit())
    monkeypatch.setattr(extractor, "get_session", get_session)
    monkeypatch.setattr(extractor, "get_tracer", lambda: _Tracer())
    monkeypatch.setattr(extractor, "increment_session_count", lambda: None)

    state = {
        "session_id": "sess-bandit-failcat",
        "status": "completed",
        "job_spec": {"level": "senior", "interview_direction": "java_backend"},
        "qa_history": [
            {
                "dimension": "system_design",
                "selected_action": "plan_deep_probe",
                "evaluation": {
                    "score": 7.5,
                    "failure_categories": ["unclear_architecture"],
                },
            },
        ],
    }

    extractor.experience_extractor_node(state)  # type: ignore[arg-type]

    with Session() as sess:
        signals = list(sess.scalars(select(StrategySignal)))

    assert len(signals) == 1
    assert signals[0].dimension == "system_design"
    assert signals[0].failure_categories == ["unclear_architecture"]
