from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.v1 import admin as admin_api
from app.models.base import Base
from app.models.question_bank import (
    QuestionRewardRollout,
    QuestionRerankUsage,
    QuestionSeed,
    QuestionUsage,
    QuestionUsageStats,
    QuestionVariant,
)


def _client(session_factory, *, knowledge_dir: Path | None = None) -> TestClient:
    app = FastAPI()
    app.include_router(admin_api.router)
    app.include_router(admin_api.api_v1_router)

    @contextmanager
    def get_session():
        with session_factory() as sess:
            yield sess
            sess.commit()

    admin_api.get_settings = lambda: SimpleNamespace(
        api_token=None,
        allow_open_admin=True,
        knowledge_dir=knowledge_dir or Path("knowledge"),
    )
    admin_api.get_session = get_session
    return TestClient(app)


def _session_factory():
    engine = create_engine(
        "sqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_local = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    with session_local() as sess:
        sess.add(
            QuestionSeed(
                id="system_design.cache_consistency",
                version=1,
                title="缓存一致性与失效策略",
                dimension="system_design",
                job_levels=["senior"],
                skill_tags=["redis"],
                direction_tags=["internet_tech"],
                role_tags=["java_backend"],
                rubric={"must_cover": ["一致性目标"]},
                priority=30,
                status="active",
                source="manual_yaml",
                scope="global",
                language="zh-CN",
            )
        )
        sess.add(
            QuestionVariant(
                id="system_design.cache_consistency.flash_sale_inventory",
                seed_id="system_design.cache_consistency",
                version=1,
                intent="opening",
                difficulty="standard",
                scenario_brief="秒杀库存读多写少。",
                question_stem="请设计库存缓存一致性方案。",
                prompt_template="围绕缓存经验生成一道系统设计题。",
                scenario_skill_tags=["redis"],
                resume_anchor_hints=["redis"],
                failure_categories=["missing_metrics"],
                rubric_additions=["说明缓存失效窗口"],
                expected_signals=["能区分强一致和最终一致"],
                anti_patterns=["只说加锁不讨论吞吐"],
                good_answer_hints=["先定义一致性目标"],
                role_tags=["java_backend"],
                priority=20,
                status="active",
            )
        )
        sess.add(
            QuestionUsage(
                id="usage-1",
                session_id="sess-1",
                turn_idx=1,
                trace_id="trace-1",
                seed_id="system_design.cache_consistency",
                variant_id="system_design.cache_consistency.flash_sale_inventory",
                seed_version=1,
                variant_version=1,
                rank=1,
                match_score=42.0,
                match_reasons=["priority:30"],
                injected=True,
                question_selector_mode="structured_primary",
                score=8.0,
                passed=True,
                immediate_reward=0.42,
            )
        )
        sess.add(
            QuestionRerankUsage(
                id="rerank-1",
                session_id="sess-1",
                turn_idx=1,
                trace_id="trace-1",
                dimension="system_design",
                probe_intent="opening",
                question_selector_mode="structured_shadow",
                rule_top_seed_id="system_design.cache_consistency",
                rule_top_variant_id="system_design.cache_consistency.flash_sale_inventory",
                llm_top_seed_id="system_design.cache_consistency",
                llm_top_variant_id="system_design.cache_consistency.failover",
                candidate_variant_ids=[
                    "system_design.cache_consistency.flash_sale_inventory",
                    "system_design.cache_consistency.failover",
                ],
                ranked_variant_ids=[
                    "system_design.cache_consistency.failover",
                    "system_design.cache_consistency.flash_sale_inventory",
                ],
                fit_scores={"system_design.cache_consistency.failover": 0.86},
                anchor_choice="Inventory",
                reasons=["more specific"],
                confidence=0.72,
                model="shadow-model",
                latency_ms=88,
                status="ok",
                error=None,
            )
        )
        sess.commit()
    return session_local


def test_admin_question_seed_list_detail_usage_and_status_actions() -> None:
    session_local = _session_factory()
    client = _client(session_local)

    listed = client.get("/admin/question-seeds")
    assert listed.status_code == 200
    assert listed.json()["count"] == 1
    seed = listed.json()["question_seeds"][0]
    assert seed["id"] == "system_design.cache_consistency"
    assert seed["dimension"] == "system_design"
    assert seed["direction_tags"] == ["internet_tech"]
    assert seed["role_tags"] == ["java_backend"]
    assert seed["variant_count"] == 1

    filtered = client.get("/admin/question-seeds?direction_tag=internet_tech&role_tag=java_backend")
    assert filtered.status_code == 200
    assert filtered.json()["count"] == 1

    filtered_out = client.get("/admin/question-seeds?role_tag=frontend_web")
    assert filtered_out.status_code == 200
    assert filtered_out.json()["count"] == 0

    detail = client.get("/admin/question-seeds/system_design.cache_consistency")
    assert detail.status_code == 200
    assert detail.json()["seed"]["title"] == "缓存一致性与失效策略"
    assert detail.json()["variants"][0]["id"] == (
        "system_design.cache_consistency.flash_sale_inventory"
    )
    assert detail.json()["variants"][0]["role_tags"] == ["java_backend"]
    assert detail.json()["variants"][0]["expected_signals"] == [
        "能区分强一致和最终一致"
    ]

    usages = client.get("/admin/question-usages?limit=10")
    assert usages.status_code == 200
    assert usages.json()["count"] == 1
    assert usages.json()["usages"][0]["variant_id"] == (
        "system_design.cache_consistency.flash_sale_inventory"
    )
    assert usages.json()["usages"][0]["immediate_reward"] == 0.42
    assert "question_context_key" in usages.json()["usages"][0]

    reranks = client.get("/admin/question-rerank-usages?limit=10")
    assert reranks.status_code == 200
    assert reranks.json()["count"] == 1
    assert reranks.json()["rerank_usages"][0]["llm_top_variant_id"] == (
        "system_design.cache_consistency.failover"
    )

    review = client.post(
        "/admin/question-reviews",
        json={
            "question_rerank_usage_id": "rerank-1",
            "session_id": "sess-1",
            "turn_idx": 1,
            "trace_id": "trace-1",
            "rule_variant_id": "system_design.cache_consistency.flash_sale_inventory",
            "llm_variant_id": "system_design.cache_consistency.failover",
            "winner": "llm",
            "reasons": ["more project aligned"],
            "notes": "LLM shadow picked a better angle.",
            "reviewer": "tester",
            "context_summary": {"dimension": "system_design"},
        },
    )
    assert review.status_code == 200
    assert review.json()["review"]["winner"] == "llm"

    reviews = client.get("/admin/question-reviews?limit=10")
    assert reviews.status_code == 200
    assert reviews.json()["count"] == 1
    assert reviews.json()["reviews"][0]["rule_variant_id"] == (
        "system_design.cache_consistency.flash_sale_inventory"
    )

    disabled_seed = client.post(
        "/admin/question-seeds/system_design.cache_consistency/disable"
    )
    assert disabled_seed.status_code == 200
    assert disabled_seed.json() == {
        "id": "system_design.cache_consistency",
        "status": "disabled",
    }

    disabled_variant = client.post(
        "/admin/question-variants/"
        "system_design.cache_consistency.flash_sale_inventory/disable"
    )
    assert disabled_variant.status_code == 200
    assert disabled_variant.json() == {
        "id": "system_design.cache_consistency.flash_sale_inventory",
        "status": "disabled",
    }

    archived_seed = client.post(
        "/admin/question-seeds/system_design.cache_consistency/archive"
    )
    assert archived_seed.status_code == 200
    assert archived_seed.json()["status"] == "archived"

    archived_variant = client.post(
        "/admin/question-variants/"
        "system_design.cache_consistency.flash_sale_inventory/archive"
    )
    assert archived_variant.status_code == 200
    assert archived_variant.json()["status"] == "archived"


def test_admin_question_seed_detail_returns_reviewed_acceptance_checks() -> None:
    session_local = _session_factory()
    reviewed_checks = [
        {
            "check_id": "reviewed:cache-consistency:core:v1",
            "source": "must_cover",
            "source_text": "consistency target",
            "acceptance_check": "Answer defines the target consistency level.",
            "severity": "core",
            "review_status": "reviewed",
            "version": 1,
            "reviewed_seed_version": 1,
            "reviewed_variant_version": 1,
            "reviewed_by": "qa-lead",
            "reviewed_at": "2026-06-01",
        }
    ]
    with session_local() as sess:
        variant = sess.get(
            QuestionVariant,
            "system_design.cache_consistency.flash_sale_inventory",
        )
        variant.reviewed_acceptance_checks = reviewed_checks
        sess.commit()

    client = _client(session_local)
    detail = client.get("/admin/question-seeds/system_design.cache_consistency")

    assert detail.status_code == 200
    assert detail.json()["variants"][0]["reviewed_acceptance_checks"] == (
        reviewed_checks
    )


def test_admin_question_usage_stats_refresh_and_reward_readiness() -> None:
    session_local = _session_factory()
    with session_local() as sess:
        sess.add(
            QuestionSeed(
                id="system_design.capacity_planning",
                version=1,
                title="容量规划",
                dimension="system_design",
                job_levels=["senior"],
                skill_tags=["capacity"],
                direction_tags=["internet_tech"],
                role_tags=["java_backend"],
                rubric={"must_cover": ["容量估算"]},
                priority=20,
                status="active",
                source="manual_yaml",
                scope="global",
                language="zh-CN",
            )
        )
        sess.add(
            QuestionVariant(
                id="system_design.capacity_planning.live_event_ticketing",
                seed_id="system_design.capacity_planning",
                version=1,
                intent="opening",
                difficulty="standard",
                scenario_brief="活动票务容量规划",
                question_stem="请设计活动票务容量方案。",
                prompt_template="围绕容量规划生成题目。",
                scenario_skill_tags=["capacity"],
                resume_anchor_hints=[],
                failure_categories=[],
                rubric_additions=[],
                expected_signals=[],
                anti_patterns=[],
                good_answer_hints=[],
                role_tags=["java_backend"],
                priority=20,
                status="active",
            )
        )
        for idx in range(20):
            sess.add(
                QuestionUsage(
                    id=f"usage-high-{idx}",
                    session_id=f"sess-high-{idx}",
                    turn_idx=idx,
                    trace_id=f"trace-high-{idx}",
                    seed_id="system_design.capacity_planning",
                    variant_id="system_design.capacity_planning.live_event_ticketing",
                    seed_version=1,
                    variant_version=1,
                    rank=2,
                    match_score=10.0,
                    match_reasons=["priority:10"],
                    injected=True,
                    question_selector_mode="structured_primary",
                    score=9.0,
                    passed=True,
                    immediate_reward=0.95,
                )
            )
        sess.commit()

    client = _client(session_local)

    refresh = client.post("/admin/question-usage-stats/refresh")
    assert refresh.status_code == 200
    assert refresh.json()["refreshed"] == 2

    stats = client.get("/admin/question-usage-stats?auto_refresh=true")
    assert stats.status_code == 200
    body = stats.json()
    assert body["count"] == 2
    rows = {row["variant_id"]: row for row in body["stats"]}
    assert rows[
        "system_design.cache_consistency.flash_sale_inventory"
    ]["rewarded_uses"] == 1
    assert rows[
        "system_design.capacity_planning.live_event_ticketing"
    ]["avg_immediate_reward"] == pytest.approx(0.95)

    paged = client.get("/admin/question-usage-stats?limit=1&offset=1")
    assert paged.status_code == 200
    paged_body = paged.json()
    assert paged_body["count"] == 2
    assert paged_body["limit"] == 1
    assert paged_body["offset"] == 1
    assert len(paged_body["stats"]) == 1
    assert paged_body["stats"][0]["variant_id"] == (
        "system_design.capacity_planning.live_event_ticketing"
    )

    readiness = client.get("/admin/question-reward-readiness?auto_refresh=true")
    assert readiness.status_code == 200
    payload = readiness.json()
    assert payload["selector_rollout_mode"] == "structured_primary"
    assert payload["reward_ranking_mode"] == "reward_shadow"
    assert payload["candidate_count"] == 2
    assert payload["usage_count"] == 21
    assert payload["rewarded_usage_count"] == 21
    assert payload["summary"]["shadow_changed_modes"] == 1
    assert payload["summary"]["low_sample_variants"] == 1
    assert payload["summary"]["ready_variants"] == 1
    assert payload["modes"] == []
    assert payload["metadata_top_variant_ids"][0] == (
        "system_design.cache_consistency.flash_sale_inventory"
    )
    assert payload["reward_top_variant_ids"][0] == (
        "system_design.capacity_planning.live_event_ticketing"
    )
    assert "reward_shadow_rank_changed" not in payload["reasons"]
    assert "candidate_pool_below_min" in payload["reasons"]
    variants = {row["variant_id"]: row for row in payload["variants"]}
    assert "reward_samples_below_min" in variants[
        "system_design.cache_consistency.flash_sale_inventory"
    ]["reasons"]
    assert "contexts" in payload
    assert "seeds" in payload

    with session_local() as sess:
        assert sess.query(QuestionUsageStats).count() == 2


def test_admin_question_reward_rollout_endpoint_updates_context_and_seed_override() -> None:
    session_local = _session_factory()
    client = _client(session_local)

    context_key = "internet_tech:java_backend:senior:system_design"
    context_rollout = client.post(
        f"/admin/question-reward-rollouts/context/{context_key}",
        json={"mode": "reward", "reason": "pilot context"},
    )
    assert context_rollout.status_code == 200
    assert context_rollout.json()["scope"] == "context"
    assert context_rollout.json()["scope_key"] == context_key
    assert context_rollout.json()["mode"] == "reward"

    seed_rollout = client.post(
        "/admin/question-reward-rollouts/seed/system_design.cache_consistency",
        json={"mode": "reward_shadow", "reason": "back to shadow"},
    )
    assert seed_rollout.status_code == 200
    assert seed_rollout.json()["scope"] == "seed"
    assert seed_rollout.json()["scope_key"] == "system_design.cache_consistency"
    assert seed_rollout.json()["mode"] == "reward_shadow"

    invalid_scope = client.post(
        "/admin/question-reward-rollouts/global/anything",
        json={"mode": "reward"},
    )
    assert invalid_scope.status_code == 400

    with session_local() as sess:
        rows = {
            (row.scope, row.scope_key): row
            for row in sess.query(QuestionRewardRollout).all()
        }
    assert rows[("context", context_key)].reason == "pilot context"
    assert rows[("seed", "system_design.cache_consistency")].reason == "back to shadow"


def test_admin_question_bank_filters_business_direction_and_role() -> None:
    session_local = _session_factory()
    with session_local() as sess:
        sess.add(
            QuestionSeed(
                id="user_insight.user_journey_pain_point",
                version=1,
                title="用户旅程与真实痛点识别",
                dimension="user_insight",
                job_levels=["mid", "senior"],
                skill_tags=["product_manager", "user_insight"],
                direction_tags=["business"],
                role_tags=["product_manager"],
                rubric={"must_cover": ["目标用户", "真实痛点"]},
                priority=30,
                status="active",
                source="manual_yaml",
                scope="global",
                language="zh-CN",
            )
        )
        sess.add(
            QuestionVariant(
                id="user_insight.user_journey_pain_point.cross_channel_onboarding",
                seed_id="user_insight.user_journey_pain_point",
                version=1,
                intent="opening",
                difficulty="standard",
                scenario_brief="多入口新用户激活率差异很大。",
                question_stem="你会如何还原不同入口用户的完整旅程？",
                prompt_template="生成一道用户洞察题。",
                scenario_skill_tags=["product_manager", "user_insight"],
                resume_anchor_hints=["product", "user_research"],
                failure_categories=["missing_evidence"],
                rubric_additions=["说明用户证据"],
                expected_signals=["能结合访谈和行为数据"],
                anti_patterns=["只描述功能流程"],
                good_answer_hints=["先拆用户与场景"],
                role_tags=["product_manager"],
                priority=18,
                status="active",
            )
        )
        sess.add(
            QuestionUsage(
                id="usage-business-1",
                session_id="sess-business",
                turn_idx=1,
                trace_id="trace-business",
                seed_id="user_insight.user_journey_pain_point",
                variant_id="user_insight.user_journey_pain_point.cross_channel_onboarding",
                seed_version=1,
                variant_version=1,
                rank=1,
                match_score=55.0,
                match_reasons=["direction_tag:business", "role_tag:product_manager"],
                injected=False,
                question_selector_mode="structured_shadow",
            )
        )
        sess.commit()

    client = _client(session_local)

    filtered = client.get(
        "/admin/question-seeds?direction_tag=business&role_tag=product_manager"
    )
    assert filtered.status_code == 200
    assert filtered.json()["count"] == 1
    assert filtered.json()["question_seeds"][0]["id"] == (
        "user_insight.user_journey_pain_point"
    )
    assert filtered.json()["question_seeds"][0]["direction_tags"] == ["business"]
    assert filtered.json()["question_seeds"][0]["role_tags"] == ["product_manager"]

    filtered_out = client.get("/admin/question-seeds?direction_tag=business&role_tag=sre")
    assert filtered_out.status_code == 200
    assert filtered_out.json()["count"] == 0

    usages = client.get(
        "/admin/question-usages?limit=10&direction_tag=business&role_tag=product_manager"
    )
    assert usages.status_code == 200
    assert usages.json()["count"] == 1
    assert usages.json()["usages"][0]["direction_tags"] == ["business"]
    assert usages.json()["usages"][0]["role_tags"] == ["product_manager"]
    assert usages.json()["usages"][0]["injected"] is False


def test_admin_question_seed_import_uses_yaml_source_of_truth(tmp_path: Path) -> None:
    knowledge_dir = tmp_path / "knowledge"
    seed_dir = knowledge_dir / "question_seeds"
    seed_dir.mkdir(parents=True)
    (seed_dir / "system_design.yaml").write_text(
        """
dimension: system_design
seeds:
  - id: system_design.capacity_planning
    version: 1
    title: 容量规划
    dimension: system_design
    job_levels: [senior]
    skill_tags: [capacity]
    direction_tags: [internet_tech]
    role_tags: [java_backend]
    rubric: {must_cover: [容量估算]}
    priority: 10
    status: active
    source: manual_yaml
    scope: global
    language: zh-CN
    variants:
      - id: system_design.capacity_planning.live_event
        version: 1
        intent: opening
        difficulty: standard
        scenario_brief: 开票流量峰值很高。
        question_stem: 请设计开票容量规划。
        prompt_template: 生成容量规划题。
        scenario_skill_tags: [capacity]
        resume_anchor_hints: []
        failure_categories: [missing_metrics]
        rubric_additions: [说明峰值估算]
        expected_signals: [能做数量级估算]
        anti_patterns: [直接堆机器]
        good_answer_hints: [先给假设]
        priority: 5
        status: active
""".lstrip(),
        encoding="utf-8",
    )
    session_local = _session_factory()
    client = _client(session_local, knowledge_dir=knowledge_dir)

    imported = client.post("/admin/question-seeds/import")

    assert imported.status_code == 200
    assert imported.json()["imported_seeds"] == 1
    assert imported.json()["imported_variants"] == 1

    detail = client.get("/admin/question-seeds/system_design.capacity_planning")
    assert detail.status_code == 200
    assert detail.json()["seed"]["title"] == "容量规划"


def test_admin_question_seed_lint_endpoint_reports_quality_issues(tmp_path: Path) -> None:
    knowledge_dir = tmp_path / "knowledge"
    seed_dir = knowledge_dir / "question_seeds"
    seed_dir.mkdir(parents=True)
    (seed_dir / "system_design.yaml").write_text(
        """
dimension: system_design
seeds:
  - id: system_design.generic
    version: 1
    title: Generic
    dimension: system_design
    job_levels: [senior]
    skill_tags: [architecture]
    direction_tags: [internet_tech]
    role_tags: [java_backend]
    rubric: {must_cover: [tradeoff]}
    priority: 10
    status: active
    source: manual_yaml
    scope: global
    language: zh-CN
    variants:
      - id: system_design.generic.opening
        version: 1
        intent: opening
        difficulty: standard
        scenario_brief: Generic architecture question.
        question_stem: Tell me about architecture.
        prompt_template: Generic prompt.
        scenario_skill_tags: []
        resume_anchor_hints: []
        failure_categories: []
        rubric_additions: []
        expected_signals: []
        anti_patterns: []
        good_answer_hints: []
        priority: 5
        status: active
""".lstrip(),
        encoding="utf-8",
    )
    session_local = _session_factory()
    client = _client(session_local, knowledge_dir=knowledge_dir)

    warning = client.post("/admin/question-seeds/lint")
    strict = client.post("/admin/question-seeds/lint?strict_quality=true")

    assert warning.status_code == 200
    assert warning.json()["passed"] is True
    assert warning.json()["warning_count"] >= 1
    assert strict.status_code == 200
    assert strict.json()["passed"] is False
    assert strict.json()["error_count"] == warning.json()["warning_count"]
