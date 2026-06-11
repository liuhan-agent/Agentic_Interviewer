"""Structured question-bank persistence models."""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class QuestionSeed(Base):
    """Reusable technical-question seed owned by YAML imports."""

    __tablename__ = "question_seeds"

    id: Mapped[str] = mapped_column(String(160), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    title: Mapped[str] = mapped_column(String(240))
    dimension: Mapped[str] = mapped_column(String(64), index=True)
    job_levels: Mapped[list] = mapped_column(JSON, default=list)
    skill_tags: Mapped[list] = mapped_column(JSON, default=list)
    direction_tags: Mapped[list] = mapped_column(JSON, default=list)
    role_tags: Mapped[list] = mapped_column(JSON, default=list)
    rubric: Mapped[dict] = mapped_column(JSON, default=dict)
    priority: Mapped[int] = mapped_column(Integer, default=0, index=True)
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    source: Mapped[str] = mapped_column(String(64), default="manual_yaml", index=True)
    scope: Mapped[str] = mapped_column(String(32), default="global", index=True)
    org_id: Mapped[str | None] = mapped_column(String(96), index=True)
    job_template_id: Mapped[str | None] = mapped_column(String(96), index=True)
    language: Mapped[str] = mapped_column(String(16), default="zh-CN", index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )


class QuestionVariant(Base):
    """Concrete angle/stem for a question seed."""

    __tablename__ = "question_variants"

    id: Mapped[str] = mapped_column(String(200), primary_key=True)
    seed_id: Mapped[str] = mapped_column(
        String(160),
        ForeignKey("question_seeds.id"),
        index=True,
    )
    version: Mapped[int] = mapped_column(Integer, default=1)
    intent: Mapped[str] = mapped_column(String(32), index=True)
    difficulty: Mapped[str] = mapped_column(String(32), index=True)
    scenario_brief: Mapped[str] = mapped_column(Text, default="")
    question_stem: Mapped[str] = mapped_column(Text, default="")
    prompt_template: Mapped[str] = mapped_column(Text, default="")
    scenario_skill_tags: Mapped[list] = mapped_column(JSON, default=list)
    resume_anchor_hints: Mapped[list] = mapped_column(JSON, default=list)
    failure_categories: Mapped[list] = mapped_column(JSON, default=list)
    rubric_additions: Mapped[list] = mapped_column(JSON, default=list)
    expected_signals: Mapped[list] = mapped_column(JSON, default=list)
    anti_patterns: Mapped[list] = mapped_column(JSON, default=list)
    good_answer_hints: Mapped[list] = mapped_column(JSON, default=list)
    reviewed_acceptance_checks: Mapped[list] = mapped_column(JSON, default=list)
    role_tags: Mapped[list] = mapped_column(JSON, default=list)
    priority: Mapped[int] = mapped_column(Integer, default=0, index=True)
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )


class QuestionUsage(Base):
    """Per-turn question-bank candidate attribution."""

    __tablename__ = "question_usages"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(64), index=True)
    turn_idx: Mapped[int] = mapped_column(Integer, index=True)
    trace_id: Mapped[str | None] = mapped_column(String(64), index=True)
    seed_id: Mapped[str] = mapped_column(String(160), index=True)
    variant_id: Mapped[str] = mapped_column(String(200), index=True)
    seed_version: Mapped[int] = mapped_column(Integer)
    variant_version: Mapped[int] = mapped_column(Integer)
    rank: Mapped[int] = mapped_column(Integer, index=True)
    match_score: Mapped[float] = mapped_column(Float, default=0.0)
    match_reasons: Mapped[list] = mapped_column(JSON, default=list)
    injected: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    question_selector_mode: Mapped[str] = mapped_column(String(32), index=True)
    question_context_key: Mapped[str | None] = mapped_column(String(160), index=True)
    direction_tag: Mapped[str | None] = mapped_column(String(64), index=True)
    role_tag: Mapped[str | None] = mapped_column(String(64), index=True)
    job_level: Mapped[str | None] = mapped_column(String(64), index=True)
    dimension: Mapped[str | None] = mapped_column(String(64), index=True)
    score: Mapped[float | None] = mapped_column(Float)
    passed: Mapped[bool | None] = mapped_column(Boolean)
    immediate_reward: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        index=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )


class QuestionRewardRollout(Base):
    """Context/seed rollout override for live question reward ranking."""

    __tablename__ = "question_reward_rollouts"

    id: Mapped[str] = mapped_column(String(240), primary_key=True)
    scope: Mapped[str] = mapped_column(String(32), index=True)
    scope_key: Mapped[str] = mapped_column(String(200), index=True)
    mode: Mapped[str] = mapped_column(String(32), default="reward_shadow", index=True)
    reason: Mapped[str] = mapped_column(String(512), default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )


class QuestionUsageStats(Base):
    """Aggregated reward-shadow health for question-bank variants."""

    __tablename__ = "question_usage_stats"

    id: Mapped[str] = mapped_column(String(160), primary_key=True)
    variant_id: Mapped[str] = mapped_column(String(200), index=True)
    question_selector_mode: Mapped[str] = mapped_column(String(32), index=True)
    question_context_key: Mapped[str] = mapped_column(
        String(160),
        default="__global__",
        index=True,
    )

    uses: Mapped[int] = mapped_column(Integer, default=0)
    injected_uses: Mapped[int] = mapped_column(Integer, default=0)
    rewarded_uses: Mapped[int] = mapped_column(Integer, default=0)
    avg_score: Mapped[float | None] = mapped_column(Float)
    pass_rate: Mapped[float | None] = mapped_column(Float)
    avg_immediate_reward: Mapped[float | None] = mapped_column(Float)

    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )


class QuestionRerankUsage(Base):
    """Shadow LLM reranker attribution for rule-vs-LLM comparison."""

    __tablename__ = "question_rerank_usages"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(64), index=True)
    turn_idx: Mapped[int] = mapped_column(Integer, index=True)
    trace_id: Mapped[str | None] = mapped_column(String(64), index=True)
    dimension: Mapped[str] = mapped_column(String(64), index=True)
    probe_intent: Mapped[str | None] = mapped_column(String(32), index=True)
    question_selector_mode: Mapped[str] = mapped_column(String(32), index=True)
    rule_top_seed_id: Mapped[str | None] = mapped_column(String(160), index=True)
    rule_top_variant_id: Mapped[str | None] = mapped_column(String(200), index=True)
    llm_top_seed_id: Mapped[str | None] = mapped_column(String(160), index=True)
    llm_top_variant_id: Mapped[str | None] = mapped_column(String(200), index=True)
    candidate_variant_ids: Mapped[list] = mapped_column(JSON, default=list)
    ranked_variant_ids: Mapped[list] = mapped_column(JSON, default=list)
    fit_scores: Mapped[dict] = mapped_column(JSON, default=dict)
    anchor_choice: Mapped[str | None] = mapped_column(Text)
    reasons: Mapped[list] = mapped_column(JSON, default=list)
    confidence: Mapped[float | None] = mapped_column(Float)
    model: Mapped[str | None] = mapped_column(String(96), index=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32), default="ok", index=True)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        index=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )


class QuestionReview(Base):
    """Human pairwise review of rule top1 vs shadow LLM top1."""

    __tablename__ = "question_reviews"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(64), index=True)
    turn_idx: Mapped[int] = mapped_column(Integer, index=True)
    trace_id: Mapped[str | None] = mapped_column(String(64), index=True)
    question_rerank_usage_id: Mapped[str | None] = mapped_column(
        String(128),
        index=True,
    )
    rule_variant_id: Mapped[str | None] = mapped_column(String(200), index=True)
    llm_variant_id: Mapped[str | None] = mapped_column(String(200), index=True)
    winner: Mapped[str] = mapped_column(String(16), index=True)
    reasons: Mapped[list] = mapped_column(JSON, default=list)
    notes: Mapped[str] = mapped_column(Text, default="")
    reviewer: Mapped[str] = mapped_column(String(96), default="admin", index=True)
    context_summary: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        index=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )
