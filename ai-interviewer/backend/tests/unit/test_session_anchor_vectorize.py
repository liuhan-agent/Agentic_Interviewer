from __future__ import annotations

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.session_anchor import SessionAnchorChunk
from app.services.resume_embedding import ResumeEmbeddingError
from app.services.session_anchor_vectorize import (
    build_self_intro_fallback_cards,
    vectorize_resume,
    vectorize_self_intro_anchor_cards,
)

HIGH_STRUCTURE_TEXT = """
Projects

Smart Learning Coupon Guard | Backend Owner | 2024.05-2024.08
- Designed Redis Hash inventory buckets with Lua atomic deduction.
- Added RabbitMQ delayed compensation and idempotent retry records.
- Tuned Spring Boot APIs with MyBatis-Plus batch queries.
- Built Prometheus alerts for oversell risk and Redis hot keys.

Realtime Order Risk Platform | Core Developer | 2023.06-2024.04
- Built Kafka ingestion and Flink stream rules.
- Used Elasticsearch indexes for investigation queries.
- Designed PostgreSQL partitioning and archive jobs.
- Added Kubernetes rollout checks with canary metrics.

Skills
- Java, Spring Boot, Spring Cloud
- Redis, Lua, RabbitMQ
- Kafka, Flink, Elasticsearch
- PostgreSQL, MySQL, MyBatis-Plus
- Docker, Kubernetes, Prometheus
"""

JAVA_BACKEND_TEXT = """
项目经历
康乐智慧养老系统 | 后端开发 | 2025年8月-2025年11月
- 工作流引擎集成：业务状态机 + Flowable，5 个审批节点、4 个部门流转，RBAC 数据权限和 formKey/taskId 四级权限。
- IoT 告警系统：XXL-JOB 分钟级扫描，Redis Hash 设备快照，规则引擎阈值/窗口/静默去抖，WebSocket 定向推送。
- 数据查询优化：单 SQL + 双 LEFT JOIN + nested ResultMap 消除 N+1，Redis Hash HMGET 回填实时数据。
- AI健康评估系统：异步任务 + Redis 进度缓存，Prompt 工程与结构化输出后校验，准确率从 60% 提升到 90%+。

智学在线教育平台 | 后端开发 | 2025年3月-2025年6月
- AI agent 路由：Redis memory isolation，RAG 与 Tool Calling 双通道输出。
- 优惠券防超卖：Redis Lua 原子扣减库存与限领，RabbitMQ 异步落库保证最终一致性。
- 推荐搜索：多路召回 + 融合排序，FunctionScoreQuery 热度衰减，ElasticSearch 支持课程检索。
- 排行榜分表：Redis ZSet 月榜实时排行，XXL-JOB 分片任务归档，rank 作为主键节省 25% 存储。

专业技能
- Java, Spring Boot, Redis, RabbitMQ, Flowable, XXL-JOB, RAG
"""

JAVA_BACKEND_PARSED = {
    "skills": ["Java", "Spring Boot", "Redis", "RabbitMQ", "Flowable", "XXL-JOB"],
    "projects": [
        {
            "name": "康乐智慧养老系统",
            "role": "后端开发",
            "tech_stack": ["Spring Boot", "Redis", "Flowable", "XXL-JOB", "WebSocket"],
            "responsibilities": [
                "工作流引擎集成：业务状态机 + Flowable，5 个审批节点、4 个部门流转。",
                "IoT 告警系统：XXL-JOB 分钟级扫描，Redis Hash 设备快照。",
            ],
            "achievements": ["Redis Hash HMGET 回填实时数据，减少 N+1 查询。"],
            "question_anchors": ["Flowable 流程变量与权限隔离"],
        },
        {
            "name": "智学在线教育平台",
            "role": "后端开发",
            "tech_stack": ["Redis", "Lua", "RabbitMQ", "SpringAI", "RAG"],
            "responsibilities": [
                "AI agent 路由：Redis memory isolation，RAG 与 Tool Calling 双通道输出。"
            ],
            "achievements": [
                "优惠券防超卖：Redis Lua 原子扣减库存与限领，RabbitMQ 异步落库保证最终一致性。"
            ],
            "question_anchors": ["Redis Lua 高并发扣减一致性", "RabbitMQ 异步落库幂等"],
        },
    ],
    "focus_areas": [
        {"label": "缓存一致性与高并发", "skills": ["Redis", "Lua", "RabbitMQ"]},
    ],
}

LONG_SELF_INTRO_TEXT = (
    "I led the Smart Learning coupon guard project where Redis Lua scripts "
    "protected coupon deduction during high traffic. I also handled RabbitMQ "
    "compensation, Spring Boot API tuning, Prometheus alerts, and incident "
    "review with product and operations teams. The most important detail is "
    "how we balanced atomic consistency, user experience, and rollback safety."
)


def _db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    SessionAnchorChunk.__table__.create(engine)
    session_local = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    return session_local


def test_vectorize_resume_writes_chunks_and_returns_ready(monkeypatch) -> None:
    session_local = _db()
    with session_local() as db_session:
        monkeypatch.setattr(
            "app.services.session_anchor_vectorize.embed_chunks",
            lambda texts, **_kw: [[0.1] * 1536 for _ in texts],
        )

        status = vectorize_resume(
            session_id="sess_a",
            resume_revision_id="rev_1",
            source_artifact_id="artifact_1",
            raw_text=HIGH_STRUCTURE_TEXT,
            parsed=None,
            db_session=db_session,
        )
        rows = db_session.scalars(
            select(SessionAnchorChunk).where(SessionAnchorChunk.session_id == "sess_a")
        ).all()

        assert status["status"] == "ready"
        assert status["mode"] == "A"
        assert status["chunk_count"] >= 10
        assert len(rows) == status["chunk_count"]
        assert {row.source_type for row in rows} == {"resume"}
        assert {row.source_revision_id for row in rows} == {"rev_1"}
        assert rows[0].source_artifact_id == "artifact_1"


def test_vectorize_resume_writes_dual_track_mode_a_chunks(monkeypatch) -> None:
    session_local = _db()
    with session_local() as db_session:
        monkeypatch.setattr(
            "app.services.session_anchor_vectorize.embed_chunks",
            lambda texts, **_kw: [[0.1] * 1536 for _ in texts],
        )

        status = vectorize_resume(
            session_id="sess_dual",
            resume_revision_id="rev_dual",
            source_artifact_id="artifact_dual",
            raw_text=JAVA_BACKEND_TEXT,
            parsed=JAVA_BACKEND_PARSED,
            db_session=db_session,
        )
        rows = db_session.scalars(
            select(SessionAnchorChunk)
            .where(SessionAnchorChunk.session_id == "sess_dual")
            .order_by(SessionAnchorChunk.chunk_index)
        ).all()

        assert status["status"] == "ready"
        assert status["mode"] == "A"
        assert status["chunk_count"] > 2
        assert len(rows) == status["chunk_count"]
        assert {row.source_type for row in rows} == {"resume"}
        assert {row.chunker_mode for row in rows} == {"A"}
        assert [row.chunk_index for row in rows] == list(range(len(rows)))
        assert {"project", "highlight", "focus"}.issubset({row.tier for row in rows})


def test_vectorize_resume_writes_revision_id(monkeypatch) -> None:
    session_local = _db()
    with session_local() as db_session:
        monkeypatch.setattr(
            "app.services.session_anchor_vectorize.embed_chunks",
            lambda texts, **_kw: [[0.1] * 1536 for _ in texts],
        )

        vectorize_resume(
            session_id="sess_a",
            resume_revision_id="rev_1",
            source_artifact_id="artifact_1",
            raw_text=HIGH_STRUCTURE_TEXT,
            parsed=None,
            db_session=db_session,
        )
        vectorize_resume(
            session_id="sess_a",
            resume_revision_id="rev_2",
            source_artifact_id="artifact_2",
            raw_text=HIGH_STRUCTURE_TEXT.replace("Coupon", "Inventory"),
            parsed=None,
            db_session=db_session,
        )
        rows = db_session.scalars(
            select(SessionAnchorChunk).where(SessionAnchorChunk.session_id == "sess_a")
        ).all()

        assert {row.source_revision_id for row in rows} == {"rev_1", "rev_2"}


def test_vectorize_resume_uses_embedding_override_version(monkeypatch) -> None:
    session_local = _db()
    embedding_override = {
        "provider": "qwen",
        "api_key": "sk-qwen-embedding",
        "model": "text-embedding-v4",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "dimensions": 1536,
    }
    captured = {}
    with session_local() as db_session:
        def fake_embed_chunks(texts, **kw):
            captured["kw"] = kw
            return [[0.1] * 1536 for _ in texts]

        monkeypatch.setattr(
            "app.services.session_anchor_vectorize.embed_chunks",
            fake_embed_chunks,
        )

        status = vectorize_resume(
            session_id="sess_a",
            resume_revision_id="rev_1",
            source_artifact_id="artifact_1",
            raw_text=HIGH_STRUCTURE_TEXT,
            parsed=None,
            db_session=db_session,
            embedding_override=embedding_override,
        )
        rows = db_session.scalars(
            select(SessionAnchorChunk).where(SessionAnchorChunk.session_id == "sess_a")
        ).all()

        assert status["embedding_model_version"] == "qwen:text-embedding-v4:1536@v1"
        assert {row.embedding_model_version for row in rows} == {
            "qwen:text-embedding-v4:1536@v1"
        }
        assert captured["kw"]["embedding_override"] == embedding_override


def test_vectorize_resume_writes_source_cache_key(monkeypatch) -> None:
    session_local = _db()
    with session_local() as db_session:
        monkeypatch.setattr(
            "app.services.session_anchor_vectorize.embed_chunks",
            lambda texts, **_kw: [[0.1] * 1536 for _ in texts],
        )

        status = vectorize_resume(
            session_id="sess_cache",
            resume_revision_id="rev_cache",
            source_artifact_id="artifact_cache",
            raw_text=HIGH_STRUCTURE_TEXT,
            parsed=None,
            db_session=db_session,
            source_cache_key="cache_a",
        )
        rows = db_session.scalars(
            select(SessionAnchorChunk).where(
                SessionAnchorChunk.session_id == "sess_cache"
            )
        ).all()

        assert status["status"] == "ready"
        assert status["source_cache_key"] == "cache_a"
        assert {row.source_cache_key for row in rows} == {"cache_a"}


def test_vectorize_resume_returns_failed_on_embedding_error(monkeypatch) -> None:
    session_local = _db()
    with session_local() as db_session:
        monkeypatch.setattr(
            "app.services.session_anchor_vectorize.embed_chunks",
            lambda _texts, **_kw: (_ for _ in ()).throw(
                ResumeEmbeddingError("upstream 500")
            ),
        )

        status = vectorize_resume(
            session_id="sess_a",
            resume_revision_id="rev_failed",
            source_artifact_id="artifact_failed",
            raw_text=HIGH_STRUCTURE_TEXT,
            parsed=None,
            db_session=db_session,
        )
        rows = db_session.scalars(
            select(SessionAnchorChunk).where(SessionAnchorChunk.session_id == "sess_a")
        ).all()

        assert status["status"] == "failed"
        assert "upstream 500" in status["error"]
        assert rows == []


def test_vectorize_resume_skips_mode_d() -> None:
    status = vectorize_resume(
        session_id="sess_b",
        resume_revision_id="rev_short",
        source_artifact_id="artifact_short",
        raw_text="too short.",
        parsed=None,
    )

    assert status["status"] == "skipped"
    assert status["mode"] == "D"
    assert status["skipped_reason"] == "mode_d_minimal_resume"


def test_vectorize_self_intro_skips_short_answer() -> None:
    session_local = _db()
    with session_local() as db_session:
        status = vectorize_self_intro_anchor_cards(
            session_id="sess_a",
            self_intro_revision_id="intro_rev_1",
            turn_idx=0,
            sanitized_answer="too short",
            anchor_cards=[],
            db_session=db_session,
        )

        assert status["status"] == "skipped"
        assert status["skipped_reason"] == "skipped_short"
        assert status["strategy"] == "short"


def test_vectorize_self_intro_writes_anchor_cards(monkeypatch) -> None:
    session_local = _db()
    with session_local() as db_session:
        monkeypatch.setattr(
            "app.services.session_anchor_vectorize.embed_chunks",
            lambda texts, **_kw: [[0.2] * 1536 for _ in texts],
        )

        status = vectorize_self_intro_anchor_cards(
            session_id="sess_a",
            self_intro_revision_id="intro_rev_1",
            turn_idx=0,
            sanitized_answer=LONG_SELF_INTRO_TEXT,
            anchor_cards=[
                {
                    "kind": "project",
                    "title": "Redis coupon guard",
                    "text": "I led the Redis Lua atomic deduction work under peak traffic.",
                    "tech_keywords": ["Redis", "Lua"],
                    "source": "llm",
                }
            ],
            db_session=db_session,
        )
        rows = db_session.scalars(
            select(SessionAnchorChunk).where(SessionAnchorChunk.session_id == "sess_a")
        ).all()

        assert status["status"] == "ready"
        assert rows[0].source_type == "self_intro"
        assert rows[0].source_revision_id == "intro_rev_1"
        assert rows[0].source_turn_id == 0
        assert rows[0].tier == "anchor_card"
        assert rows[0].chunker_mode == "SI"
        assert status["strategy"] == "medium"
        assert status["card_sources"] == {"llm": 1}
        assert status["card_count_by_kind"] == {"project": 1}


def test_vectorize_self_intro_reports_long_strategy_and_source_counts(monkeypatch) -> None:
    session_local = _db()
    long_answer = LONG_SELF_INTRO_TEXT * 5
    with session_local() as db_session:
        monkeypatch.setattr(
            "app.services.session_anchor_vectorize.embed_chunks",
            lambda texts, **_kw: [[0.2] * 1536 for _ in texts],
        )

        status = vectorize_self_intro_anchor_cards(
            session_id="sess_long",
            self_intro_revision_id="intro_rev_long",
            turn_idx=0,
            sanitized_answer=long_answer,
            anchor_cards=[
                {
                    "kind": "project",
                    "title": "Redis coupon guard",
                    "text": "I led the Redis Lua atomic deduction work.",
                    "tech_keywords": ["Redis", "Lua"],
                    "source": "llm",
                },
                {
                    "kind": "result",
                    "title": "Consistency outcome",
                    "text": "The work improved consistency under peak traffic.",
                    "tech_keywords": ["Redis"],
                    "source": "supplement",
                },
            ],
            db_session=db_session,
        )
        rows = db_session.scalars(
            select(SessionAnchorChunk)
            .where(SessionAnchorChunk.session_id == "sess_long")
            .order_by(SessionAnchorChunk.chunk_index)
        ).all()

        assert status["status"] == "ready"
        assert status["strategy"] == "long"
        assert status["card_sources"] == {"llm": 1, "supplement": 1}
        assert status["card_count_by_kind"] == {"project": 1, "result": 1}
        assert [row.chunk_index for row in rows] == [0, 1]


def test_self_intro_fallback_cards_use_profile_summary() -> None:
    cards = build_self_intro_fallback_cards(
        {"summary": "Led Redis coupon consistency.", "emphasized_projects": ["Coupon"]},
        "fallback answer",
    )

    assert cards[0]["kind"] == "claim"
    assert cards[0]["text"] == "Led Redis coupon consistency."
    assert any(card["kind"] == "project" for card in cards)
