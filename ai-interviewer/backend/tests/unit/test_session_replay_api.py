from __future__ import annotations

import threading
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

SESSION_CREATED_AT = datetime(2026, 5, 1, 10, 0, tzinfo=UTC)
SESSION_UPDATED_AT = datetime(2026, 5, 1, 10, 30, tzinfo=UTC)
FOLLOWUP_REASON = {
    "title": "为什么继续追问",
    "summary": "上一轮回答还需要补足「容量估算」，下一题会继续围绕这个点追问。",
    "chips": ["深挖追问", "量化指标", "容量估算"],
    "source": "evaluator",
}
QUESTION_BASIS = {
    "title": "为什么问这一题",
    "summary": "这题结合了简历中的支付迁移项目，并围绕技术深度确认 Redis。",
    "chips": ["来自简历", "来自岗位要求", "评分维度", "技术深度", "Redis"],
}


class _Manager:
    def get(self, session_id: str) -> None:
        return None


class _ResumeHandle:
    trace_id = "trace-replay"
    cancelled = False
    error = None
    error_kind = None
    current_question = {
        "question": "Follow-up: explain one performance optimization.",
        "dimension": "technical_depth",
        "formal_turn_idx": 1,
    }
    turn_idx = 1
    max_turns = 3
    final_state: dict | None = None
    session_token_hash = None
    session_token_expires_at = None
    last_turn_evaluation = {
        "turn_idx": 0,
        "dimension": "technical_depth",
        "score": 7.5,
        "passed": True,
        "strengths": ["Explains cache eviction"],
        "weaknesses": ["Capacity estimate is thin"],
    }

    def __init__(self) -> None:
        self.done_event = threading.Event()


class _ResumeManager:
    def __init__(self) -> None:
        self.handle = _ResumeHandle()

    def get(self, session_id: str) -> _ResumeHandle | None:
        return self.handle if session_id == "sess-replay" else None


class _ResumeManagerWithCheckpointIntro(_ResumeManager):
    def _checkpoint_waiting_question(self, session_id: str) -> dict | None:
        if session_id != "sess-replay":
            return None
        return {
            "current_question": self.handle.current_question,
            "turn_idx": self.handle.turn_idx,
            "self_intro_answer": "I am a backend engineer focused on Redis and workflow systems.",
        }


class _ResumeManagerWithCheckpointHistory(_ResumeManager):
    def _checkpoint_waiting_question(self, session_id: str) -> dict | None:
        if session_id != "sess-replay":
            return None
        return {
            "current_question": self.handle.current_question,
            "turn_idx": self.handle.turn_idx,
            "qa_history": [
                {
                    "turn_idx": 0,
                    "dimension": "communication",
                    "question": "Explain a technical decision to a teammate.",
                    "answer": "I used a concrete Redis Lua example and asked them to repeat it.",
                    "evaluation": {
                        "score": 7.0,
                        "passed": False,
                        "rationale": "Clear example with a light understanding check.",
                        "strengths": ["Concrete example"],
                        "weaknesses": ["Could verify more actively"],
                        "recommended_next": "advance",
                    },
                },
                {
                    "turn_idx": 1,
                    "dimension": "communication",
                    "question": "Handle pushback on delayed progress updates.",
                    "answer": "I separated Redis read freshness from delayed database writes.",
                    "evaluation": {
                        "score": 9.0,
                        "passed": True,
                        "strengths": ["Addressed the pushback directly"],
                        "weaknesses": [],
                    },
                },
                {
                    "turn_idx": 2,
                    "dimension": "technical_depth",
                    "question": "How do you repair cache state after a crash?",
                    "answer": "Use a compensation task with version checks.",
                    "evaluation": {
                        "score": 8.0,
                        "passed": False,
                        "strengths": ["Version checks"],
                        "weaknesses": ["CAP framing is thin"],
                    },
                },
                {
                    "turn_idx": 3,
                    "dimension": "system_design",
                    "question": "This is the current pending question and should not show.",
                    "answer": "A stale answer for the pending turn.",
                },
            ],
        }


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


def _client_with_manager(monkeypatch: pytest.MonkeyPatch, manager) -> TestClient:
    monkeypatch.setattr(interview_api, "get_session_manager", lambda: manager)
    app = FastAPI()
    app.include_router(interview_api.router)
    return TestClient(app)


def _seed_session(
    testing_session_local,
    *,
    status: str = "completed",
    token_hash: str | None = None,
) -> None:
    now = SESSION_CREATED_AT
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
                    "growth_signal": "near_target",
                    "overall_verdict": "hire",
                    "dimension_scores": {
                        "technical_depth": {
                            "score": 7.5,
                            "passed": True,
                        }
                    },
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
                updated_at=SESSION_UPDATED_AT,
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
    assert payload["created_at"] == SESSION_CREATED_AT.isoformat()
    assert payload["updated_at"] == SESSION_UPDATED_AT.isoformat()
    assert payload["summary"] == {
        "job_title": "Java 后端",
        "job_level": "junior",
        "overall_score": 8.1,
        "growth_signal": "near_target",
        "overall_verdict": "hire",
        "total_turns": 1,
        "priority_weaknesses": ["容量估算"],
        "priority_items": [
            {
                "category": "weakness",
                "label": "薄弱点",
                "dimension": "technical_depth",
                "focus": "容量估算",
                "display_text": "容量估算",
            }
        ],
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


def test_replay_summary_projects_grouped_priority_items(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _isolated_db(monkeypatch) as testing_session_local:
        _seed_session(testing_session_local)
        with testing_session_local() as sess:
            row = sess.get(InterviewSession, "sess-replay")
            assert row is not None
            row.final_report = {
                **(row.final_report or {}),
                "training_plan": {
                    "priority_weaknesses": [
                        {
                            "dimension": "技术深度",
                            "focus": "容量估算不够具体",
                            "why_it_matters": "评估器多次标记容量估算不足。",
                        },
                        {
                            "dimension": "系统设计",
                            "focus": "补充「系统设计」维度的回答证据与覆盖面",
                            "category": "coverage_limited",
                        },
                    ]
                },
            }
            sess.commit()
        client = _client(monkeypatch)

        resp = client.get("/api/v1/interview/sessions/sess-replay/replay")

    assert resp.status_code == 200
    summary = resp.json()["summary"]
    assert summary["priority_weaknesses"] == [
        "容量估算不够具体",
        "补充「系统设计」维度的回答证据与覆盖面",
    ]
    assert summary["priority_items"] == [
        {
            "category": "weakness",
            "label": "薄弱点",
            "dimension": "技术深度",
            "focus": "容量估算不够具体",
            "display_text": "容量估算不够具体",
        },
        {
            "category": "coverage_limited",
            "label": "补充证据",
            "dimension": "系统设计",
            "focus": "补充「系统设计」维度的回答证据与覆盖面",
            "display_text": "系统设计：补充具体例子、关键指标和取舍说明",
        },
    ]


def test_replay_summary_priority_items_handle_legacy_and_filtered_items(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _isolated_db(monkeypatch) as testing_session_local:
        _seed_session(testing_session_local)
        with testing_session_local() as sess:
            row = sess.get(InterviewSession, "sess-replay")
            assert row is not None
            row.final_report = {
                **(row.final_report or {}),
                "training_plan": {
                    "priority_weaknesses": [
                        "沟通表达缺少结构",
                        {"dimension": "技术深度", "focus": ""},
                        {
                            "dimension": "技术深度",
                            "focus": "Evaluator LLM failed before returning a score.",
                        },
                        {
                            "focus": "补充回答证据",
                            "category": "coverage_limited",
                        },
                    ]
                },
            }
            sess.commit()
        client = _client(monkeypatch)

        resp = client.get("/api/v1/interview/sessions/sess-replay/replay")

    assert resp.status_code == 200
    assert resp.json()["summary"]["priority_items"] == [
        {
            "category": "weakness",
            "label": "薄弱点",
            "dimension": None,
            "focus": "沟通表达缺少结构",
            "display_text": "沟通表达缺少结构",
        },
        {
            "category": "coverage_limited",
            "label": "补充证据",
            "dimension": None,
            "focus": "补充回答证据",
            "display_text": "补充回答证据",
        },
    ]


def test_replay_maps_refine_next_step_to_user_copy(
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
                **(trace.evaluation or {}),
                "recommended_next": "refine",
                "recommended_next_plan": "deep_probe",
            }
            sess.commit()
        client = _client(monkeypatch)

        resp = client.get("/api/v1/interview/sessions/sess-replay/replay")

    assert resp.status_code == 200
    turn = resp.json()["timeline"][0]
    assert turn["next_step"] == (
        "进一步深挖本题中的关键决策、指标、取舍或边界情况。"
    )
    assert "refine" not in str(turn)
    assert "deep_probe" not in str(turn)


@pytest.mark.parametrize("decision", ["advance", "skip"])
def test_replay_hides_internal_next_decisions(
    monkeypatch: pytest.MonkeyPatch,
    decision: str,
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
                **(trace.evaluation or {}),
                "recommended_next": decision,
                "recommended_next_plan": "adaptive",
            }
            sess.commit()
        client = _client(monkeypatch)

        resp = client.get("/api/v1/interview/sessions/sess-replay/replay")

    assert resp.status_code == 200
    turn = resp.json()["timeline"][0]
    assert turn["next_step"] == ""
    assert decision not in str(turn)
    assert "adaptive" not in str(turn)


def test_metadata_returns_persisted_session_times_and_summary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _isolated_db(monkeypatch) as testing_session_local:
        _seed_session(
            testing_session_local,
            token_hash=hash_session_token("session-secret"),
        )
        client = _client(monkeypatch)

        missing = client.get("/api/v1/interview/sessions/sess-replay/metadata")
        wrong = client.get(
            "/api/v1/interview/sessions/sess-replay/metadata",
            headers={"X-Session-Token": "wrong"},
        )
        ok = client.get(
            "/api/v1/interview/sessions/sess-replay/metadata",
            headers={"X-Session-Token": "session-secret"},
        )

    assert missing.status_code == 401
    assert wrong.status_code == 403
    assert ok.status_code == 200
    assert ok.json() == {
        "session_id": "sess-replay",
        "status": "completed",
        "created_at": SESSION_CREATED_AT.isoformat(),
        "updated_at": SESSION_UPDATED_AT.isoformat(),
        "job_title": "Java 后端",
        "candidate_name": "刘韩",
        "job_level": "junior",
        "overall_score": 8.1,
        "growth_signal": "near_target",
        "overall_verdict": "hire",
        "dimension_scores": {"technical_depth": 7.5},
    }


def test_resume_returns_prior_turn_history_for_running_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _isolated_db(monkeypatch) as testing_session_local:
        _seed_session(testing_session_local, status="interrupted")
        client = _client_with_manager(monkeypatch, _ResumeManager())

        resp = client.get("/api/v1/interview/sessions/sess-replay/resume")

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["status"] == "waiting_for_answer"
    assert payload["created_at"] == SESSION_CREATED_AT.isoformat()
    assert payload["updated_at"] == SESSION_UPDATED_AT.isoformat()
    assert payload["question"]["question"].startswith("Follow-up")
    assert payload["previous_turn_evaluation"] == _ResumeHandle.last_turn_evaluation
    assert len(payload["history"]) == 1
    turn = payload["history"][0]
    assert turn["turn_idx"] == 0
    assert turn["dimension"] == "technical_depth"
    assert "Redis" in turn["answer"]
    assert turn["score"] == 7.5
    assert turn["passed"] is True
    assert turn["strengths"]
    assert turn["weaknesses"]
    assert turn["next_step"]


def test_resume_history_includes_self_intro_without_counting_it_as_a_question(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _isolated_db(monkeypatch) as testing_session_local:
        _seed_session(testing_session_local, status="interrupted")
        client = _client_with_manager(
            monkeypatch,
            _ResumeManagerWithCheckpointIntro(),
        )

        resp = client.get("/api/v1/interview/sessions/sess-replay/resume")

    assert resp.status_code == 200
    history = resp.json()["history"]
    assert history[0]["question_type"] == "self_intro"
    assert history[0]["turn_idx"] is None
    assert history[0]["answer"].startswith("I am a backend engineer")
    assert history[1]["turn_idx"] == 0


def test_resume_history_uses_formal_turn_indexes_and_skips_current_question(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _isolated_db(monkeypatch) as testing_session_local:
        _seed_session(testing_session_local, status="interrupted")
        now = datetime.now(UTC)
        with testing_session_local() as sess:
            first_trace = (
                sess.query(GenerationTrace)
                .filter(GenerationTrace.session_id == "sess-replay")
                .filter(GenerationTrace.node == "evaluator")
                .one()
            )
            first_trace.turn_idx = 1
            first_trace.dimension = "communication"
            first_trace.question = "Introduce a project you owned."
            first_trace.answer = "I described the goal, tradeoffs, and outcome."
            first_trace.state_snapshot = {
                "qa_history": [
                    {
                        "turn_idx": 0,
                        "dimension": "communication",
                        "question": first_trace.question,
                        "answer": first_trace.answer,
                    }
                ]
            }
            sess.add(
                GenerationTrace(
                    trace_id="trace-replay",
                    session_id="sess-replay",
                    turn_idx=8,
                    node="evaluator",
                    dimension="problem_solving",
                    action_id="internal-action",
                    policy_id="policy",
                    context_key="junior:problem_solving",
                    policy_context_keys=["junior:problem_solving"],
                    score=7.0,
                    passed=True,
                    immediate_reward=0.3,
                    delayed_reward=None,
                    applied_to_bandit=False,
                    immediate_reward_applied=True,
                    state_snapshot={
                        "qa_history": [
                            {
                                "turn_idx": 7,
                                "dimension": "problem_solving",
                                "question": "This stale answered turn matches the pending question.",
                                "answer": "Already answered.",
                            }
                        ]
                    },
                    question="This stale answered turn matches the pending question.",
                    answer="Already answered.",
                    evaluation={
                        "score": 7.0,
                        "passed": True,
                        "strengths": ["Clear"],
                        "weaknesses": [],
                    },
                    langsmith_run_id="run-stale-current",
                    created_at=now,
                )
            )
            sess.commit()

        manager = _ResumeManager()
        manager.handle.current_question = {
            "question": "Pending eighth formal question.",
            "dimension": "problem_solving",
            "formal_turn_idx": 7,
        }
        manager.handle.turn_idx = 8
        manager.handle.max_turns = 8
        client = _client_with_manager(monkeypatch, manager)

        resp = client.get("/api/v1/interview/sessions/sess-replay/resume")

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["question"]["formal_turn_idx"] == 7
    assert [turn["turn_idx"] for turn in payload["history"]] == [0]
    assert payload["history"][0]["dimension"] == "communication"


def test_resume_history_backfills_missing_trace_turns_from_checkpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _isolated_db(monkeypatch) as testing_session_local:
        _seed_session(testing_session_local, status="interrupted")
        with testing_session_local() as sess:
            sess.query(GenerationTrace).delete()
            sess.add(
                GenerationTrace(
                    trace_id="trace-replay",
                    session_id="sess-replay",
                    turn_idx=2,
                    node="evaluator",
                    dimension="technical_depth",
                    action_id="internal-action",
                    policy_id="policy",
                    context_key="junior:technical_depth",
                    policy_context_keys=["junior:technical_depth"],
                    score=8.0,
                    passed=False,
                    immediate_reward=0.2,
                    delayed_reward=None,
                    applied_to_bandit=False,
                    immediate_reward_applied=True,
                    state_snapshot={},
                    question="How do you repair cache state after a crash?",
                    answer="Use a compensation task with version checks.",
                    evaluation={
                        "score": 8.0,
                        "passed": False,
                        "strengths": ["Trace copy"],
                        "weaknesses": ["Trace weakness"],
                    },
                    langsmith_run_id="run-existing",
                    created_at=SESSION_CREATED_AT,
                )
            )
            sess.commit()

        manager = _ResumeManagerWithCheckpointHistory()
        manager.handle.current_question = {
            "question": "Pending fourth formal question.",
            "dimension": "system_design",
            "formal_turn_idx": 3,
        }
        manager.handle.turn_idx = 4
        client = _client_with_manager(monkeypatch, manager)

        resp = client.get("/api/v1/interview/sessions/sess-replay/resume")

    assert resp.status_code == 200
    history = resp.json()["history"]
    assert [turn["turn_idx"] for turn in history] == [0, 1, 2]
    assert history[0]["question"].startswith("Explain a technical decision")
    assert history[1]["answer"].startswith("I separated Redis")
    assert history[2]["strengths"] == ["Trace copy"]
    assert all("current pending question" not in turn["question"] for turn in history)


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


def test_replay_report_fallback_maps_internal_next_step(
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
                                "question": "How would you debug a cache incident?",
                                "answer_excerpt": "I would inspect metrics and logs.",
                                "score": 6.5,
                                "passed": False,
                                "recommended_next": "refine",
                                "recommended_next_plan": "simple",
                            }
                        ]
                    }
                },
            }
            sess.commit()
        client = _client(monkeypatch)

        resp = client.get("/api/v1/interview/sessions/sess-replay/replay")

    assert resp.status_code == 200
    turn = resp.json()["timeline"][0]
    assert turn["next_step"] == "继续补充本题的基础信息和关键细节。"
    assert "refine" not in str(turn)
    assert "simple" not in str(turn)


def test_replay_report_fallback_prefers_full_answer_over_excerpt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    full_answer = (
        "我会先定义缓存命中率和延迟目标，再估算 key 数量、value 大小、TTL 分布，"
        "接着设计 Redis 集群容量、淘汰策略、缓存穿透保护和写入失效机制。"
    )
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
                                "answer": full_answer,
                                "answer_excerpt": "我会先定义缓存命中率和延迟目标...",
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
    assert resp.json()["timeline"][0]["answer"] == full_answer


def test_replay_trace_projects_display_followup_reason(
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
                **(trace.evaluation or {}),
                "followup_reason": FOLLOWUP_REASON,
            }
            sess.commit()
        client = _client(monkeypatch)

        resp = client.get("/api/v1/interview/sessions/sess-replay/replay")

    assert resp.status_code == 200
    assert resp.json()["timeline"][0]["followup_reason"] == FOLLOWUP_REASON


def test_replay_report_fallback_projects_display_followup_reason(
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
                                "question": "How do you size Redis capacity?",
                                "answer": "Estimate hot keys, value size, TTL, and peak QPS.",
                                "score": 6.0,
                                "passed": False,
                                "rationale": "Needs a more concrete capacity estimate.",
                                "weaknesses": ["Capacity estimate is thin"],
                                "followup_reason": FOLLOWUP_REASON,
                            }
                        ]
                    }
                },
            }
            sess.commit()
        client = _client(monkeypatch)

        resp = client.get("/api/v1/interview/sessions/sess-replay/replay")

    assert resp.status_code == 200
    assert resp.json()["timeline"][0]["followup_reason"] == FOLLOWUP_REASON


def test_replay_drops_malformed_followup_reason(
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
                **(trace.evaluation or {}),
                "followup_reason": {
                    "title": "为什么继续追问",
                    "summary": "说明存在，但 chips 不是数组。",
                    "chips": "补充证据",
                    "source": "evaluator",
                },
            }
            sess.commit()
        client = _client(monkeypatch)

        resp = client.get("/api/v1/interview/sessions/sess-replay/replay")

    assert resp.status_code == 200
    assert "followup_reason" not in resp.json()["timeline"][0]


def test_replay_context_basis_projects_opening_resume_and_job_spec(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _isolated_db(monkeypatch) as testing_session_local:
        _seed_session(testing_session_local)
        with testing_session_local() as sess:
            row = sess.get(InterviewSession, "sess-replay")
            assert row is not None
            row.setup_snapshot = {
                "candidate": {
                    "resume_parsed": {
                        "projects": [{"name": "支付迁移项目"}],
                        "focus_areas": [{"label": "缓存治理"}],
                        "skills": ["Redis", "Kafka"],
                    }
                },
                "job_spec": {
                    "title": "Java 后端",
                    "level": "senior",
                    "required_skills": ["Redis", "Kafka"],
                    "rubric_dimensions": ["technical_depth"],
                },
            }
            row.final_report = {
                **(row.final_report or {}),
                "self_intro": {
                    "profile": {
                        "summary": "候选人强调支付迁移项目，可全职实习6个月以上，面试通过后3天内到岗。",
                        "emphasized_projects": ["支付迁移项目"],
                        "emphasized_skills": ["Redis"],
                        "preferred_focus": ["容量估算"],
                    }
                },
            }
            sess.commit()
        client = _client(monkeypatch)

        resp = client.get("/api/v1/interview/sessions/sess-replay/replay")

    assert resp.status_code == 200
    basis = resp.json()["context_basis"]
    assert basis["title"] == "开场与简历线索"
    assert basis["summary"] == (
        "本场面试会结合开场自我介绍、简历项目和岗位要求选择问题；"
        "评分维度主要来自岗位要求。"
    )
    assert "全职实习" not in basis["summary"]
    assert "3天内到岗" not in basis["summary"]
    assert "来自自我介绍" not in basis["chips"]
    assert "来自简历" not in basis["chips"]
    assert "来自岗位要求" not in basis["chips"]
    assert "1 个项目线索" in basis["chips"]
    assert "2 个技能线索" in basis["chips"]
    assert "1 个评分维度" in basis["chips"]
    assert "支付迁移项目" not in basis["chips"]
    assert "Redis" not in basis["chips"]
    assert basis["self_intro"]["emphasized_projects"] == ["支付迁移项目"]
    assert basis["resume"]["skills"] == ["Redis", "Kafka"]
    assert basis["job_spec"]["dimension_source_label"] == "岗位要求"


def test_replay_trace_projects_display_question_basis(
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
            trace.state_snapshot = {
                "qa_history": [
                    {
                        "turn_idx": 0,
                        "question": trace.question,
                        "answer": trace.answer,
                        "question_basis": QUESTION_BASIS,
                    }
                ]
            }
            sess.commit()
        client = _client(monkeypatch)

        resp = client.get("/api/v1/interview/sessions/sess-replay/replay")

    assert resp.status_code == 200
    assert resp.json()["timeline"][0]["question_basis"] == QUESTION_BASIS


def test_replay_report_fallback_projects_display_question_basis(
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
                                "question": "How did you use Redis?",
                                "answer": "I used Redis for hot reads.",
                                "score": 8.0,
                                "passed": True,
                                "question_basis": QUESTION_BASIS,
                            }
                        ]
                    }
                },
            }
            sess.commit()
        client = _client(monkeypatch)

        resp = client.get("/api/v1/interview/sessions/sess-replay/replay")

    assert resp.status_code == 200
    assert resp.json()["timeline"][0]["question_basis"] == QUESTION_BASIS


def test_replay_drops_malformed_question_basis(
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
            trace.state_snapshot = {
                "qa_history": [
                    {
                        "turn_idx": 0,
                        "question": trace.question,
                        "answer": trace.answer,
                        "question_basis": {
                            "title": "为什么问这一题",
                            "summary": "说明",
                            "chips": "来自简历",
                        },
                    }
                ]
            }
            sess.commit()
        client = _client(monkeypatch)

        resp = client.get("/api/v1/interview/sessions/sess-replay/replay")

    assert resp.status_code == 200
    assert "question_basis" not in resp.json()["timeline"][0]


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
