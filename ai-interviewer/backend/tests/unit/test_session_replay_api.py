from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.v1 import interview as interview_api
from app.core.session_auth import hash_session_token
from app.models.base import Base
from app.models.generation_trace import GenerationTrace
from app.models.interview_session import InterviewSession


class _Manager:
    def get(self, session_id: str) -> None:
        return None


@contextmanager
def _isolated_db(monkeypatch: pytest.MonkeyPatch):
    engine = create_engine(
        "sqlite://",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session_local = sessionmaker(
        bind=engine,
        expire_on_commit=False,
        autoflush=False,
    )
    Base.metadata.create_all(engine)

    @contextmanager
    def get_session():
        sess = testing_session_local()
        try:
            yield sess
            sess.commit()
        except Exception:
            sess.rollback()
            raise
        finally:
            sess.close()

    monkeypatch.setattr(interview_api, "get_db_session", get_session, raising=False)
    yield testing_session_local


def _client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(interview_api, "get_session_manager", lambda: _Manager())
    app = FastAPI()
    app.include_router(interview_api.router)
    return TestClient(app)


def _seed_session(
    testing_session_local,
    *,
    status: str = "completed",
    token_hash: str | None = None,
) -> None:
    now = datetime.now(UTC)
    with testing_session_local() as sess:
        sess.add(
            InterviewSession(
                session_id="sess-replay",
                trace_id="trace-replay",
                session_token_hash=token_hash,
                candidate_name="刘韩",
                job_title="Java 后端",
                job_level="junior",
                mode="mixed",
                status=status,
                final_report={
                    "overall_score": 8.1,
                    "overall_verdict": "hire",
                    "total_turns": 1,
                    "training_plan": {
                        "priority_weaknesses": [
                            {
                                "dimension": "technical_depth",
                                "focus": "容量估算",
                            }
                        ],
                        "practice_plan": [
                            {"task": "补一次缓存容量估算练习"},
                        ],
                    },
                },
                created_at=now,
                updated_at=now,
            )
        )
        sess.add(
            GenerationTrace(
                trace_id="trace-replay",
                session_id="sess-replay",
                turn_idx=0,
                node="evaluator",
                dimension="technical_depth",
                action_id="internal-action",
                policy_id="policy",
                context_key="junior:technical_depth",
                policy_context_keys=["junior:technical_depth"],
                score=7.5,
                passed=True,
                immediate_reward=0.4,
                delayed_reward=None,
                applied_to_bandit=False,
                immediate_reward_applied=True,
                state_snapshot={
                    "timing": {"llm_total_ms": 900},
                    "selected_action": {"id": "internal-action"},
                },
                question="如何设计一个缓存系统？",
                answer="我会使用 Redis，并说明淘汰策略。",
                evaluation={
                    "score": 7.5,
                    "passed": True,
                    "rationale": "覆盖了核心设计，但容量估算不足。",
                    "strengths": ["能说明缓存淘汰策略"],
                    "weaknesses": ["容量估算不够具体"],
                    "recommended_next": "练习容量估算",
                },
                langsmith_run_id="run-internal",
                created_at=now,
            )
        )
        sess.add(
            GenerationTrace(
                trace_id="trace-replay",
                session_id="sess-replay",
                turn_idx=0,
                node="director_sample",
                dimension="technical_depth",
                action_id="internal-action",
                policy_id="policy",
                context_key="junior:technical_depth",
                policy_context_keys=["junior:technical_depth"],
                score=None,
                passed=None,
                immediate_reward=None,
                delayed_reward=None,
                applied_to_bandit=False,
                immediate_reward_applied=False,
                state_snapshot={"selected_action": {"id": "internal-action"}},
                question=None,
                answer=None,
                evaluation=None,
                langsmith_run_id="run-internal",
                created_at=now,
            )
        )
        sess.commit()


def test_replay_returns_user_facing_timeline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _isolated_db(monkeypatch) as testing_session_local:
        _seed_session(testing_session_local)
        client = _client(monkeypatch)

        resp = client.get("/api/v1/interview/sessions/sess-replay/replay")

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["summary"] == {
        "job_title": "Java 后端",
        "job_level": "junior",
        "overall_score": 8.1,
        "overall_verdict": "hire",
        "total_turns": 1,
        "priority_weaknesses": ["容量估算"],
    }
    assert payload["timeline"] == [
        {
            "turn_idx": 0,
            "dimension": "technical_depth",
            "question": "如何设计一个缓存系统？",
            "answer": "我会使用 Redis，并说明淘汰策略。",
            "score": 7.5,
            "passed": True,
            "rationale": "覆盖了核心设计，但容量估算不足。",
            "strengths": ["能说明缓存淘汰策略"],
            "weaknesses": ["容量估算不够具体"],
            "next_step": "练习容量估算",
        }
    ]
    assert payload["training_plan"]["practice_plan"] == [
        {"task": "补一次缓存容量估算练习"},
    ]
    assert "trace_id" not in payload
    assert "state_snapshot" not in str(payload)
    assert "langsmith_run_id" not in str(payload)
    assert "policy_context_keys" not in str(payload)


def test_replay_falls_back_to_final_report_evidence_when_traces_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _isolated_db(monkeypatch) as testing_session_local:
        _seed_session(testing_session_local)
        with testing_session_local() as sess:
            sess.query(GenerationTrace).delete()
            row = sess.get(InterviewSession, "sess-replay")
            assert row is not None
            row.final_report = {
                **(row.final_report or {}),
                "total_turns": 1,
                "dimension_summaries": {
                    "technical_depth": {
                        "evidence": [
                            {
                                "turn_idx": 0,
                                "question": "如何设计一个缓存系统？",
                                "answer_excerpt": "我会使用 Redis，并说明淘汰策略。",
                                "score": 7.5,
                                "passed": True,
                                "rationale": "覆盖了核心设计，但容量估算不足。",
                                "strengths": ["能说明缓存淘汰策略"],
                                "weaknesses": ["容量估算不够具体"],
                                "recommended_next": "练习容量估算",
                            }
                        ]
                    }
                },
            }
            sess.commit()
        client = _client(monkeypatch)

        resp = client.get("/api/v1/interview/sessions/sess-replay/replay")

    assert resp.status_code == 200
    assert resp.json()["timeline"] == [
        {
            "turn_idx": 0,
            "dimension": "technical_depth",
            "question": "如何设计一个缓存系统？",
            "answer": "我会使用 Redis，并说明淘汰策略。",
            "score": 7.5,
            "passed": True,
            "rationale": "覆盖了核心设计，但容量估算不足。",
            "strengths": ["能说明缓存淘汰策略"],
            "weaknesses": ["容量估算不够具体"],
            "next_step": "练习容量估算",
        }
    ]


def test_replay_rejects_running_session(monkeypatch: pytest.MonkeyPatch) -> None:
    with _isolated_db(monkeypatch) as testing_session_local:
        _seed_session(testing_session_local, status="running")
        client = _client(monkeypatch)

        resp = client.get("/api/v1/interview/sessions/sess-replay/replay")

    assert resp.status_code == 409
    assert "completed" in resp.text


def test_replay_requires_session_token_when_persisted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _isolated_db(monkeypatch) as testing_session_local:
        _seed_session(
            testing_session_local,
            token_hash=hash_session_token("session-secret"),
        )
        client = _client(monkeypatch)

        missing = client.get("/api/v1/interview/sessions/sess-replay/replay")
        wrong = client.get(
            "/api/v1/interview/sessions/sess-replay/replay",
            headers={"X-Session-Token": "wrong"},
        )
        ok = client.get(
            "/api/v1/interview/sessions/sess-replay/replay",
            headers={"X-Session-Token": "session-secret"},
        )

    assert missing.status_code == 401
    assert wrong.status_code == 403
    assert ok.status_code == 200


def test_replay_hides_system_fallback_feedback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _isolated_db(monkeypatch) as testing_session_local:
        _seed_session(testing_session_local)
        with testing_session_local() as sess:
            trace = (
                sess.query(GenerationTrace)
                .filter(GenerationTrace.session_id == "sess-replay")
                .filter(GenerationTrace.node == "evaluator")
                .one()
            )
            trace.evaluation = {
                "score": 0.0,
                "passed": False,
                "rationale": "Evaluator LLM unavailable; using conservative fallback.",
                "strengths": ["Evaluator LLM unavailable."],
                "weaknesses": ["conservative fallback"],
                "recommended_next": "Evaluator LLM failed before returning a score.",
            }
            sess.commit()
        client = _client(monkeypatch)

        resp = client.get("/api/v1/interview/sessions/sess-replay/replay")

    assert resp.status_code == 200
    turn = resp.json()["timeline"][0]
    assert turn["rationale"] == ""
    assert turn["strengths"] == []
    assert turn["weaknesses"] == []
    assert turn["next_step"] == ""
