from __future__ import annotations

from pathlib import Path

from app.services.resume_chunker import (
    ResumeChunkerMode,
    chunk_resume,
    detect_resume_structure,
    extract_tech_keywords,
    infer_dimensions_hint,
    normalize_resume_text,
)

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "resumes"


def _read_fixture(name: str) -> str:
    return (FIXTURE_DIR / name).read_text(encoding="utf-8")


def _java_backend_parsed_resume() -> dict:
    return {
        "skills": [
            "Java",
            "Spring Boot",
            "Redis",
            "RabbitMQ",
            "Flowable",
            "XXL-JOB",
        ],
        "projects": [
            {
                "name": "康乐智慧养老系统",
                "role": "后端开发",
                "tech_stack": [
                    "Spring Boot",
                    "Spring Security",
                    "MySQL",
                    "MyBatis-Plus",
                    "XXL-JOB",
                    "Flowable",
                    "IoT",
                    "WebSocket",
                    "LangChainj",
                ],
                "responsibilities": [
                    "AI健康评估系统：异步任务 + Redis 进度缓存，MD5 报告缓存命中率 80%+，Prompt 工程与结构化输出后校验，准确率从 60% 提升到 90%+。",
                    "工作流引擎集成：业务状态机 + Flowable，5 个审批节点、4 个部门流转，RBAC 数据权限和 formKey/taskId 四级权限。",
                ],
                "achievements": [
                    "数据查询优化：单 SQL + 双 LEFT JOIN + nested ResultMap 消除 N+1，Redis Hash HMGET 回填实时数据。",
                    "IoT 告警系统：XXL-JOB 分钟级扫描，Redis Hash 设备快照，规则引擎阈值/窗口/静默去抖，WebSocket 定向推送。",
                ],
                "question_anchors": [
                    "AI 工程落地与 RAG/Prompt 可靠性",
                    "Flowable 流程变量与权限隔离",
                    "XXL-JOB 告警扫描和 Redis Hash 新鲜度窗口",
                ],
            },
            {
                "name": "智学在线教育平台",
                "role": "后端开发",
                "tech_stack": [
                    "Spring Boot",
                    "Spring Cloud",
                    "Redis",
                    "RabbitMQ",
                    "ElasticSearch",
                    "XXL-JOB",
                    "SpringAI",
                ],
                "responsibilities": [
                    "AI agent 路由：router agent 分发到业务 agents，Redis memory isolation，RAG 与 Tool Calling 双通道输出。",
                    "推荐搜索：多路召回 + 融合排序，FunctionScoreQuery 热度衰减。",
                ],
                "achievements": [
                    "优惠券防超卖：Redis Lua 原子扣减库存与限领，RabbitMQ 异步落库保证最终一致性。",
                    "排行榜分表：Redis ZSet 月榜实时排行，XXL-JOB 分片任务归档，rank 作为主键节省 25% 存储。",
                ],
                "question_anchors": [
                    "Redis Lua 高并发扣减一致性",
                    "RabbitMQ 异步落库幂等",
                    "RAG 与 Tool Calling 的工具上下文隔离",
                ],
            },
        ],
        "focus_areas": [
            {
                "label": "AI 应用工程化",
                "skills": ["LangChainj", "SpringAI", "RAG"],
                "highlights": ["Prompt 输出校验、重试降级、工具上下文隔离"],
            },
            {
                "label": "缓存一致性与高并发",
                "skills": ["Redis", "Lua", "RabbitMQ"],
                "highlights": ["优惠券扣减、异步落库、最终一致性"],
            },
        ],
    }


def _java_backend_raw_text() -> str:
    return """
刘韩
Java 后端开发

项目经历
康乐智慧养老系统 | 后端开发 | 2025年8月-2025年11月
- AI健康评估系统：异步任务 + Redis 进度缓存，MD5 报告缓存命中率 80%+，Prompt 工程与结构化输出后校验，准确率从 60% 提升到 90%+。
- 工作流引擎集成：业务状态机 + Flowable，5 个审批节点、4 个部门流转，RBAC 数据权限和 formKey/taskId 四级权限。
- IoT 告警系统：XXL-JOB 分钟级扫描，Redis Hash 设备快照，规则引擎阈值/窗口/静默去抖，WebSocket 定向推送。

智学在线教育平台 | 后端开发 | 2025年3月-2025年6月
- AI agent 路由：router agent 分发到业务 agents，Redis memory isolation，RAG 与 Tool Calling 双通道输出。
- 优惠券防超卖：Redis Lua 原子扣减库存与限领，RabbitMQ 异步落库保证最终一致性。
- 排行榜分表：Redis ZSet 月榜实时排行，XXL-JOB 分片任务归档，rank 作为主键节省 25% 存储。

专业技能
- Java, Spring Boot, Spring Security, MyBatis-Plus
- Redis, Lua, RabbitMQ, Flowable, XXL-JOB, WebSocket
- LangChainj, SpringAI, RAG, Tool Calling
"""


def test_chunker_classifies_high_structure_resume() -> None:
    text = _read_fixture("fixture_high_structure_tech.md")
    mode, chunks = chunk_resume(text, parsed=None)

    assert mode is ResumeChunkerMode.A
    tiers = [chunk.tier for chunk in chunks]
    assert tiers.count("highlight") >= 8
    assert tiers.count("skill") >= 5
    assert all(chunk.text.strip() for chunk in chunks)
    assert any(chunk.project_name == "Smart Learning Coupon Guard" for chunk in chunks)


def test_mode_a_merges_parsed_and_raw_resume_anchors() -> None:
    mode, chunks = chunk_resume(
        _java_backend_raw_text(),
        parsed=_java_backend_parsed_resume(),
    )

    assert mode is ResumeChunkerMode.A
    assert 8 <= len(chunks) <= 24
    assert [chunk.chunk_index for chunk in chunks] == list(range(len(chunks)))
    tiers = [chunk.tier for chunk in chunks]
    assert tiers.count("project") == 2
    assert "highlight" in tiers
    assert "focus" in tiers
    combined_text = "\n".join(chunk.text for chunk in chunks)
    for term in ("Flowable", "Redis Hash", "XXL-JOB", "Lua", "RabbitMQ", "RAG"):
        assert term in combined_text
    keywords = {keyword for chunk in chunks for keyword in chunk.tech_keywords}
    assert {"Flowable", "XXL-JOB", "RabbitMQ", "Lua"}.issubset(keywords)


def test_mode_a_chunks_chinese_raw_project_sections_without_parsed() -> None:
    mode, chunks = chunk_resume(_java_backend_raw_text(), parsed=None)

    assert mode is ResumeChunkerMode.A
    tiers = {chunk.tier for chunk in chunks}
    assert {"project", "highlight", "skill"}.issubset(tiers)
    assert any(chunk.project_name == "康乐智慧养老系统" for chunk in chunks)
    assert any("Flowable" in chunk.text for chunk in chunks)
    assert any("XXL-JOB" in chunk.text for chunk in chunks)


def test_mode_a_deduplicates_parsed_and_raw_anchor_overlap() -> None:
    mode, chunks = chunk_resume(
        _java_backend_raw_text(),
        parsed=_java_backend_parsed_resume(),
    )

    assert mode is ResumeChunkerMode.A
    keys = [
        (
            chunk.tier,
            chunk.project_name or "",
            chunk.heading or chunk.text[:96],
        )
        for chunk in chunks
    ]
    assert len(keys) == len(set(keys))
    assert len(chunks) <= 24


def test_chunker_classifies_medium_structure_resume() -> None:
    text = _read_fixture("fixture_medium_structure_sales.md")
    mode, chunks = chunk_resume(text, parsed=None)

    assert mode is ResumeChunkerMode.B
    assert len(chunks) >= 2
    assert {chunk.tier for chunk in chunks} == {"section"}


def test_chunker_classifies_low_structure_resume() -> None:
    text = _read_fixture("fixture_low_structure_freeform.md")
    mode, chunks = chunk_resume(text, parsed=None)

    assert mode is ResumeChunkerMode.C
    assert chunks
    assert {chunk.tier for chunk in chunks} == {"window"}


def test_chunker_falls_back_to_full_on_minimal_resume() -> None:
    text = _read_fixture("fixture_minimal_intern.md")
    mode, chunks = chunk_resume(text, parsed=None)

    assert mode is ResumeChunkerMode.D
    assert len(chunks) == 1
    assert chunks[0].tier == "full"


def test_chunker_extracts_tech_keywords_from_highlight() -> None:
    text = "Redis Hash cache + Lua script protects RabbitMQ async writes"
    keywords = extract_tech_keywords(text)

    assert {"Redis", "Lua", "RabbitMQ"}.issubset(set(keywords))


def test_chunker_infers_dimensions_from_keywords() -> None:
    dimensions = infer_dimensions_hint(
        "Redis Lua queue consistency",
        ["Redis", "Lua", "RabbitMQ"],
    )

    assert "system_design" in dimensions
    assert "technical_depth" in dimensions


def test_chunker_normalizes_spacing_and_tech_punctuation() -> None:
    raw = "Java\u00a0\uff0c\u2009Spring Boot\u200b, Redis"

    assert normalize_resume_text(raw) == "Java, Spring Boot, Redis"


def test_chunker_never_raises_on_garbage_input() -> None:
    mode, chunks = chunk_resume("", parsed=None)

    assert mode is ResumeChunkerMode.D
    assert chunks == [] or chunks[0].text == ""


def test_detect_resume_structure_uses_parsed_projects_as_structure_signal() -> None:
    text = "Short project notes " * 40

    mode = detect_resume_structure(
        text,
        parsed={
            "projects": [
                {"name": "A", "highlights": ["Redis"]},
                {"name": "B", "highlights": ["Kafka"]},
            ],
            "focus_areas": [{"label": "cache"}],
        },
    )

    assert mode is ResumeChunkerMode.A
