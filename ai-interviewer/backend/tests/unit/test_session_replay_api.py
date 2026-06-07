from __future__ import annotations

import threading
from contextlib import contextmanager
from datetime import UTC, datetime
from types import SimpleNamespace

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
from app.models.strategy_learning import InterviewTurn
from app.services import session_replay as replay_mod

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
    monkeypatch.setattr("app.models.get_session", get_session)
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
    owner_user_id: int | None = None,
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
                owner_user_id=owner_user_id,
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


def test_session_trace_returns_owner_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _isolated_db(monkeypatch) as testing_session_local:
        _seed_session(
            testing_session_local,
            token_hash=hash_session_token("session-secret"),
            owner_user_id=101,
        )
        with testing_session_local() as sess:
            sess.add(
                GenerationTrace(
                    trace_id="trace-replay",
                    session_id="sess-replay",
                    turn_idx=0,
                    node="resume_parse",
                    dimension=None,
                    action_id="internal-action",
                    policy_id="policy",
                    context_key="junior:setup",
                    policy_context_keys=["junior:setup"],
                    score=None,
                    passed=None,
                    immediate_reward=None,
                    delayed_reward=None,
                    applied_to_bandit=False,
                    immediate_reward_applied=False,
                    state_snapshot={
                        "payload": {
                            "workflow_node": "resume_parse",
                            "semantic_node": "resume_parse",
                            "display_name_zh": "简历准备",
                            "phase": "opening",
                            "dimensions": ["system_design", "communication"],
                            "rubric_dimensions": [
                                "system_design",
                                "communication",
                            ],
                            "required_skills": ["Redis", "Kafka"],
                            "candidate_skills": ["Redis", "Spring Boot"],
                            "resume_projects_count": 1,
                            "resume_focus_areas_count": 1,
                            "resume_projects": [
                                {
                                    "id": "p1",
                                    "name": "Coupon Guard",
                                    "role": "Tech Lead",
                                    "tech_stack": ["Redis", "Kafka"],
                                }
                            ],
                            "resume_focus_areas": [
                                {
                                    "id": "f1",
                                    "label": "缓存一致性治理",
                                    "project_id": "p1",
                                    "dimensions": ["system_design"],
                                    "skills": ["Redis"],
                                    "priority": 1,
                                }
                            ],
                            "resume_anchors": [
                                {
                                    "label": "缓存一致性治理",
                                    "project_name": "Coupon Guard",
                                    "tech_stack": ["Redis", "Kafka"],
                                    "question_anchors": ["热点 key 失效压测"],
                                    "skills": ["Redis"],
                                    "dimensions": ["system_design"],
                                    "anchor_key": "internal-anchor-key",
                                    "raw_debug_note": "owner should not see this",
                                }
                            ],
                            "rubric_dimension_keys": [
                                "system_design",
                                "communication",
                            ],
                            "dimensions_count": 2,
                            "rubric_count": 2,
                            "dimension_status_summary": {
                                "total": 2,
                                "pending": 2,
                                "active": 0,
                                "passed": 0,
                                "failed": 0,
                                "other": 0,
                            },
                            "scores_per_dim_summary": {
                                "total": 2,
                                "scored": 0,
                                "unscored": 2,
                            },
                            "resume_vector_status": {
                                "status": "ready",
                                "source_type": "parse_artifact",
                                "chunk_count": 6,
                                "has_resume_source_id": True,
                                "has_resume_revision_id": True,
                            },
                        }
                    },
                    question=None,
                    answer=None,
                    evaluation=None,
                    langsmith_run_id="run-internal",
                    created_at=SESSION_CREATED_AT,
                )
            )
            sess.add(
                GenerationTrace(
                    trace_id="trace-replay",
                    session_id="sess-replay",
                    turn_idx=0,
                    node="self_intro_parse",
                    dimension=None,
                    action_id="internal-action",
                    policy_id="policy",
                    context_key="junior:setup",
                    policy_context_keys=["junior:setup"],
                    score=None,
                    passed=None,
                    immediate_reward=None,
                    delayed_reward=None,
                    applied_to_bandit=False,
                    immediate_reward_applied=False,
                    state_snapshot={
                        "payload": {
                            "workflow_node": "self_intro_parse",
                            "semantic_node": "self_intro_parse",
                            "display_name_zh": "开场解析",
                            "phase": "opening",
                            "parse_status": "llm",
                            "emphasized_projects_count": 1,
                            "emphasized_skills_count": 2,
                            "profile_summary": {
                                "has_summary": True,
                                "preferred_focus_count": 1,
                                "clarification_targets_count": 0,
                                "communication_signal_present": True,
                                "communication_structure": "clear",
                                "communication_notes_count": 1,
                            },
                            "anchor_cards_summary": {
                                "total": 3,
                                "project": 1,
                                "responsibility": 0,
                                "tech": 2,
                                "difficulty": 0,
                                "result": 0,
                                "claim": 0,
                                "other": 0,
                            },
                            "profile_fields_present": [
                                "summary",
                                "emphasized_projects",
                                "emphasized_skills",
                                "preferred_focus",
                                "communication_signal",
                                "anchor_cards",
                            ],
                            "self_intro_profile_snapshot": {
                                "emphasized_projects": ["Coupon Guard"],
                                "emphasized_skills": ["Redis", "Kafka"],
                                "preferred_focus": ["缓存一致性治理"],
                                "clarification_targets": ["压测规模"],
                            },
                            "self_intro_anchor_cards": [
                                {
                                    "kind": "project",
                                    "title": "Coupon Guard",
                                    "tech_keywords": ["Redis"],
                                    "source": "llm",
                                    "text": "owner should not see full card text",
                                    "raw_debug_note": "owner should not see debug",
                                }
                            ],
                            "self_intro_communication": {
                                "structure": "clear",
                                "notes_count": 1,
                                "clarification_targets_count": 1,
                                "notes": ["owner should not see notes"],
                            },
                            "self_intro_downstream_usage": {
                                "anchor_scheduler_signals": [
                                    "emphasized_projects",
                                    "emphasized_skills",
                                    "preferred_focus",
                                ],
                                "skill_focus_signal": "emphasized_skills",
                                "rag_source": "anchor_cards",
                                "next_nodes": ["director_sample", "ask_question"],
                                "raw_debug_note": "owner should not see debug",
                            },
                            "self_intro_vector_status": {
                                "status": "ready",
                                "mode": "self_intro",
                                "chunk_count": 3,
                                "has_self_intro_revision_id": True,
                            },
                        }
                    },
                    question=None,
                    answer=None,
                    evaluation=None,
                    langsmith_run_id="run-internal",
                    created_at=SESSION_CREATED_AT,
                )
            )
            sess.add(
                GenerationTrace(
                    trace_id="trace-replay",
                    session_id="sess-replay",
                    turn_idx=0,
                    node="turn_finalize",
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
                    state_snapshot={
                        "payload": {
                            "phase": "turn_finalize",
                            "reason": "turn_finalize",
                            "next_step": "route_decision",
                            "raw_answer_cleared": True,
                        }
                    },
                    question=None,
                    answer=None,
                    evaluation=None,
                    langsmith_run_id="run-internal",
                    created_at=SESSION_CREATED_AT,
                )
            )
            sess.commit()
        monkeypatch.setattr(
            interview_api,
            "get_optional_user",
            lambda _request: SimpleNamespace(id=101),
        )
        client = _client(monkeypatch)

        resp = client.get(
            "/api/v1/interview/sessions/sess-replay/trace",
            headers={"X-Session-Token": "session-secret"},
        )

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["session_id"] == "sess-replay"
    assert payload["trace_health"] == "partial"
    assert payload["trace_count"] == 5
    assert "langsmith" not in payload
    assert payload["nodes"]

    evaluator = next(node for node in payload["nodes"] if node["node"] == "evaluator")
    assert isinstance(evaluator["question"], str)
    assert evaluator["question"].strip()
    assert evaluator["answer_excerpt"]
    assert evaluator["evaluation"]["score"] == 7.5
    assert evaluator["payload"] == {}

    for internal_key in (
        "action_id",
        "policy_id",
        "context_key",
        "policy_context_keys",
        "immediate_reward",
        "immediate_reward_applied",
        "langsmith_run_id",
    ):
        assert internal_key not in evaluator

    finalize = next(node for node in payload["nodes"] if node["node"] == "turn_finalize")
    assert finalize["payload"]["phase"] == "turn_finalize"
    assert finalize["payload"]["reason"] == "turn_finalize"
    assert finalize["payload"]["next_step"] == "route_decision"
    assert "raw_answer_cleared" not in finalize["payload"]

    opening = next(node for node in payload["nodes"] if node["node"] == "resume_parse")
    assert opening["payload"]["phase"] == "opening"
    assert opening["payload"]["dimensions"] == ["system_design", "communication"]
    assert opening["payload"]["rubric_dimensions"] == [
        "system_design",
        "communication",
    ]
    assert opening["payload"]["required_skills"] == ["Redis", "Kafka"]
    assert opening["payload"]["candidate_skills"] == ["Redis", "Spring Boot"]
    assert opening["payload"]["resume_projects_count"] == 1
    assert opening["payload"]["resume_focus_areas_count"] == 1
    assert opening["payload"]["resume_projects"][0]["name"] == "Coupon Guard"
    assert opening["payload"]["resume_focus_areas"][0]["label"] == "缓存一致性治理"
    assert opening["payload"]["resume_anchors"] == [
        {
            "label": "缓存一致性治理",
            "project_name": "Coupon Guard",
            "tech_stack": ["Redis", "Kafka"],
            "question_anchors": ["热点 key 失效压测"],
            "skills": ["Redis"],
            "dimensions": ["system_design"],
        }
    ]
    assert opening["payload"]["dimensions_count"] == 2
    assert opening["payload"]["rubric_count"] == 2
    assert opening["payload"]["dimension_status_summary"]["pending"] == 2
    assert opening["payload"]["scores_per_dim_summary"]["unscored"] == 2
    assert opening["payload"]["resume_vector_status"] == {"status": "ready"}
    assert "rubric_dimension_keys" not in opening["payload"]
    assert "anchor_key" not in str(opening["payload"]["resume_anchors"])
    assert "raw_debug_note" not in str(opening["payload"]["resume_anchors"])
    assert "chunk_count" not in opening["payload"]["resume_vector_status"]

    intro_parse = next(
        node for node in payload["nodes"] if node["node"] == "self_intro_parse"
    )
    assert intro_parse["payload"]["phase"] == "opening"
    assert intro_parse["payload"]["parse_status"] == "llm"
    assert intro_parse["payload"]["emphasized_projects_count"] == 1
    assert intro_parse["payload"]["emphasized_skills_count"] == 2
    assert intro_parse["payload"]["profile_summary"]["preferred_focus_count"] == 1
    assert intro_parse["payload"]["anchor_cards_summary"]["total"] == 3
    assert intro_parse["payload"]["self_intro_profile_snapshot"] == {
        "emphasized_projects": ["Coupon Guard"],
        "emphasized_skills": ["Redis", "Kafka"],
        "preferred_focus": ["缓存一致性治理"],
        "clarification_targets": ["压测规模"],
    }
    assert intro_parse["payload"]["self_intro_anchor_cards"] == [
        {
            "kind": "project",
            "title": "Coupon Guard",
            "tech_keywords": ["Redis"],
            "source": "llm",
        }
    ]
    assert intro_parse["payload"]["self_intro_communication"] == {
        "structure": "clear",
        "notes_count": 1,
        "clarification_targets_count": 1,
    }
    assert intro_parse["payload"]["self_intro_downstream_usage"] == {
        "anchor_scheduler_signals": [
            "emphasized_projects",
            "emphasized_skills",
            "preferred_focus",
        ],
        "skill_focus_signal": "emphasized_skills",
        "rag_source": "anchor_cards",
        "next_nodes": ["director_sample", "ask_question"],
    }
    assert intro_parse["payload"]["profile_fields_present"] == [
        "summary",
        "emphasized_projects",
        "emphasized_skills",
        "preferred_focus",
        "communication_signal",
        "anchor_cards",
    ]
    assert intro_parse["payload"]["self_intro_vector_status"] == {"status": "ready"}
    assert "full card text" not in str(intro_parse["payload"])
    assert "raw_debug_note" not in str(intro_parse["payload"])
    assert "owner should not see notes" not in str(intro_parse["payload"])
    assert "chunk_count" not in intro_parse["payload"]["self_intro_vector_status"]


def test_session_trace_requires_completed_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _isolated_db(monkeypatch) as testing_session_local:
        _seed_session(
            testing_session_local,
            status="running",
            token_hash=hash_session_token("session-secret"),
        )
        client = _client(monkeypatch)

        resp = client.get(
            "/api/v1/interview/sessions/sess-replay/trace",
            headers={"X-Session-Token": "session-secret"},
        )

    assert resp.status_code == 409
    assert resp.json()["detail"] == "trace is only available for completed sessions"


def test_session_trace_requires_session_token_when_persisted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _isolated_db(monkeypatch) as testing_session_local:
        _seed_session(
            testing_session_local,
            token_hash=hash_session_token("session-secret"),
        )
        client = _client(monkeypatch)

        missing = client.get("/api/v1/interview/sessions/sess-replay/trace")
        wrong = client.get(
            "/api/v1/interview/sessions/sess-replay/trace",
            headers={"X-Session-Token": "wrong"},
        )
        ok = client.get(
            "/api/v1/interview/sessions/sess-replay/trace",
            headers={"X-Session-Token": "session-secret"},
        )

    assert missing.status_code == 401
    assert wrong.status_code == 403
    assert ok.status_code == 200


def test_session_trace_rejects_wrong_logged_in_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _isolated_db(monkeypatch) as testing_session_local:
        _seed_session(
            testing_session_local,
            token_hash=hash_session_token("session-secret"),
            owner_user_id=101,
        )
        monkeypatch.setattr(
            interview_api,
            "get_optional_user",
            lambda _request: SimpleNamespace(id=202),
        )
        client = _client(monkeypatch)

        resp = client.get(
            "/api/v1/interview/sessions/sess-replay/trace",
            headers={"X-Session-Token": "session-secret"},
        )

    assert resp.status_code == 403
    assert resp.json()["detail"] == "session owner required"


def test_replay_prefers_durable_turns_when_trace_history_lags(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _isolated_db(monkeypatch) as testing_session_local:
        _seed_session(testing_session_local)
        with testing_session_local() as sess:
            row = sess.get(InterviewSession, "sess-replay")
            assert row is not None
            row.final_report = {**(row.final_report or {}), "total_turns": 2}
            sess.query(GenerationTrace).delete()
            sess.add_all(
                [
                    InterviewTurn(
                        session_id="sess-replay",
                        trace_id="trace-replay",
                        turn_idx=0,
                        dimension="technical_depth",
                        question="Turn 1 durable question",
                        answer="Turn 1 durable answer",
                        score=7.0,
                        passed=True,
                        evaluation={
                            "score": 7.0,
                            "passed": True,
                            "rationale": "First durable rationale.",
                            "strengths": ["Specific example"],
                            "weaknesses": ["Needs sharper metrics"],
                            "recommended_next": "advance",
                        },
                    ),
                    InterviewTurn(
                        session_id="sess-replay",
                        trace_id="trace-replay",
                        turn_idx=1,
                        dimension="system_design",
                        question="Turn 2 durable question",
                        answer="Turn 2 durable answer",
                        score=8.0,
                        passed=True,
                        evaluation={
                            "score": 8.0,
                            "passed": True,
                            "rationale": "Second durable rationale.",
                            "strengths": ["Clear tradeoff"],
                            "weaknesses": [],
                            "recommended_next": "advance",
                        },
                    ),
                ]
            )
            sess.add_all(
                [
                    GenerationTrace(
                        trace_id="trace-replay",
                        session_id="sess-replay",
                        turn_idx=0,
                        node="evaluator",
                        dimension="technical_depth",
                        score=7.0,
                        passed=True,
                        state_snapshot={"qa_history": []},
                        question="Turn 1 trace question",
                        answer="Turn 1 trace answer",
                        evaluation={"score": 7.0, "passed": True},
                        created_at=SESSION_CREATED_AT,
                    ),
                    GenerationTrace(
                        trace_id="trace-replay",
                        session_id="sess-replay",
                        turn_idx=1,
                        node="evaluator",
                        dimension="system_design",
                        score=8.0,
                        passed=True,
                        state_snapshot={
                            "qa_history": [
                                {
                                    "turn_idx": 0,
                                    "question": "Turn 1 trace question",
                                    "answer": "Turn 1 trace answer",
                                }
                            ]
                        },
                        question="Turn 2 trace question",
                        answer="Turn 2 trace answer",
                        evaluation={"score": 8.0, "passed": True},
                        created_at=SESSION_UPDATED_AT,
                    ),
                ]
            )
            sess.commit()
        client = _client(monkeypatch)

        resp = client.get("/api/v1/interview/sessions/sess-replay/replay")

    assert resp.status_code == 200
    timeline = resp.json()["timeline"]
    assert [turn["turn_idx"] for turn in timeline] == [0, 1]
    assert [turn["question"] for turn in timeline] == [
        "Turn 1 durable question",
        "Turn 2 durable question",
    ]


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


def test_resume_does_not_show_stale_question_while_answer_is_processing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _isolated_db(monkeypatch) as testing_session_local:
        _seed_session(testing_session_local, status="interrupted")
        manager = _ResumeManager()
        manager.handle.question_event = threading.Event()
        manager.handle.current_question = {
            "question": "Already-submitted question should not be shown again.",
            "dimension": "technical_depth",
            "formal_turn_idx": 0,
        }
        client = _client_with_manager(monkeypatch, manager)

        resp = client.get("/api/v1/interview/sessions/sess-replay/resume")

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["status"] == "running"
    assert payload["question"] is None
    assert len(payload["history"]) == 1
    assert "Redis" in payload["history"][0]["answer"]


def test_resume_includes_submitted_answer_while_evaluation_is_processing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _isolated_db(monkeypatch) as testing_session_local:
        _seed_session(testing_session_local, status="interrupted")
        manager = _ResumeManager()
        manager.handle.question_event = threading.Event()
        manager.handle.current_question = {
            "question": "Explain how you would repair Redis cache state.",
            "dimension": "system_design",
            "formal_turn_idx": 1,
        }
        manager.handle.turn_idx = 2
        manager.handle.pending_submitted_question = dict(manager.handle.current_question)
        manager.handle.pending_submitted_turn_idx = manager.handle.turn_idx
        manager.handle.pending_submitted_answer = (
            "I would compare Redis with the database source of truth and rebuild keys."
        )
        client = _client_with_manager(monkeypatch, manager)

        resp = client.get("/api/v1/interview/sessions/sess-replay/resume")

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["status"] == "running"
    assert payload["question"] is None
    assert [turn["turn_idx"] for turn in payload["history"]] == [0, 1]
    pending = payload["history"][-1]
    assert pending["dimension"] == "system_design"
    assert pending["question"] == "Explain how you would repair Redis cache state."
    assert pending["answer"].startswith("I would compare Redis")
    assert pending["score"] is None
    assert pending["passed"] is None
    assert pending["strengths"] == []
    assert pending["weaknesses"] == []


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


def test_replay_turn_fact_projects_question_decision_basis() -> None:
    row = SimpleNamespace(
        turn_idx=0,
        dimension="system_design",
        question="How would you design Redis consistency?",
        answer="I would use versioned writes.",
        score=8.0,
        passed=True,
        resume_anchor_key="focus-coupon-consistency",
        resume_anchor_label="Coupon consistency",
        resume_project_id="proj-coupon",
        evaluation={
            "score": 8.0,
            "passed": True,
            "recommended_next": "advance",
        },
        selection_artifacts={
            "question_decision_basis": {
                "version": "v1",
                "sources": ["resume", "job"],
                "dimension": "system_design",
                "resume_anchor": {
                    "label": "Coupon consistency",
                    "project_id": "proj-coupon",
                    "source": "resume",
                },
                "target_skills": [
                    {"value": "Redis", "source": "job_spec"},
                ],
                "reason_codes": ["covers_target_skills"],
                "prompt_slot": "must-not-survive",
            }
        },
    )

    payload = replay_mod._turn_payload_from_fact(row)

    assert payload["question_decision_basis"] == {
        "version": "v1",
        "sources": ["resume", "job"],
        "dimension": "system_design",
        "resume_anchor": {
            "label": "Coupon consistency",
            "project_id": "proj-coupon",
            "source": "resume",
        },
        "target_skills": [{"value": "Redis", "source": "job_spec"}],
        "reason_codes": ["covers_target_skills"],
    }
    assert "prompt_slot" not in str(payload)


def test_replay_trace_projects_depth_followup_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    depth_followup = {
        "source_turn_idx": 3,
        "parent_turn_idx": 10,
        "depth_reason": "depth_followup_recovery",
        "depth_slot_rank": 2,
        "depth_target_turns": 12,
    }
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
                        "phase": "depth_followup",
                        "depth_followup": depth_followup,
                    }
                ]
            }
            sess.commit()
        client = _client(monkeypatch)

        resp = client.get("/api/v1/interview/sessions/sess-replay/replay")

    turn = resp.json()["timeline"][0]
    assert resp.status_code == 200
    assert turn["phase"] == "depth_followup"
    assert turn["depth_followup"] == depth_followup


def test_replay_trace_projects_resume_anchor_display_fields(
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
                        "resume_anchor": {
                            "anchor_key": "focus-coupon-design",
                            "label": "Coupon consistency",
                            "project_id": "proj_coupon",
                            "skills": ["Redis"],
                        },
                    }
                ]
            }
            sess.commit()
        client = _client(monkeypatch)

        resp = client.get("/api/v1/interview/sessions/sess-replay/replay")

    turn = resp.json()["timeline"][0]
    assert resp.status_code == 200
    assert turn["resume_anchor_key"] == "focus-coupon-design"
    assert turn["resume_anchor_label"] == "Coupon consistency"
    assert turn["resume_project_id"] == "proj_coupon"
    assert "resume_anchor" not in turn


def test_replay_trace_projects_anchor_followup_display_fields(
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
                        "selection_artifacts": {
                            "anchor_scheduler": {
                                "available": True,
                                "anchor_attempt": 2,
                                "max_anchor_attempts": 2,
                                "expansion_reason": "high_value_second_pass",
                            }
                        },
                    }
                ]
            }
            sess.commit()
        client = _client(monkeypatch)

        resp = client.get("/api/v1/interview/sessions/sess-replay/replay")

    turn = resp.json()["timeline"][0]
    assert resp.status_code == 200
    assert turn["anchor_followup"] == {
        "attempt": 2,
        "max_attempts": 2,
    }
    assert "anchor_scheduler" not in turn


def test_replay_derives_anchor_followup_from_repeated_anchor_history(
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
                        "turn_idx": 1,
                        "question": trace.question,
                        "answer": trace.answer,
                        "resume_anchor": {
                            "anchor_key": "focus-coupon-design",
                            "label": "Coupon consistency",
                        },
                    }
                ]
            }
            sess.add(
                GenerationTrace(
                    trace_id="trace-replay",
                    session_id="sess-replay",
                    turn_idx=2,
                    node="evaluator",
                    dimension="system_design",
                    action_id="internal-action",
                    policy_id="policy",
                    context_key="junior:system_design",
                    score=8.5,
                    passed=True,
                    immediate_reward=0.5,
                    delayed_reward=None,
                    applied_to_bandit=False,
                    immediate_reward_applied=True,
                    state_snapshot={
                        "qa_history": [
                            {
                                "turn_idx": 2,
                                "question": "Second pass on the same anchor?",
                                "answer": "I would add a capacity drill.",
                                "resume_anchor": {
                                    "anchor_key": "focus-coupon-design",
                                    "label": "Coupon consistency",
                                },
                            }
                        ]
                    },
                    question="Second pass on the same anchor?",
                    answer="I would add a capacity drill.",
                    evaluation={
                        "score": 8.5,
                        "passed": True,
                        "strengths": [],
                        "weaknesses": [],
                    },
                    created_at=SESSION_UPDATED_AT,
                )
            )
            sess.commit()
        client = _client(monkeypatch)

        resp = client.get("/api/v1/interview/sessions/sess-replay/replay")

    timeline = resp.json()["timeline"]
    assert resp.status_code == 200
    assert "anchor_followup" not in timeline[0]
    assert timeline[1]["anchor_followup"] == {
        "attempt": 2,
        "max_attempts": 2,
    }


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
