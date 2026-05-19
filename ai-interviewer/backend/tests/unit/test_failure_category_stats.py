"""Tests for ``failure_category_stats.compute_failure_category_overlap_stats``.

The service reads recent evaluator traces and buckets the LLM-output vs
keyword-inferred comparison into 4 mutually exclusive counters. We pin
the bucketing rule with synthetic ``GenerationTrace`` rows so it stays
stable when the keyword normalizer evolves.
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.base import Base
from app.models.generation_trace import GenerationTrace
from app.services.failure_category_stats import (
    compute_failure_category_overlap_stats,
)


def _session_factory():
    engine = create_engine(
        "sqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)


def _add_evaluator_trace(sess: Any, **evaluation: Any) -> None:
    sess.add(
        GenerationTrace(
            trace_id="trace-x",
            session_id="sess-x",
            turn_idx=0,
            node="evaluator",
            dimension="system_design",
            score=evaluation.get("score", 5.0),
            evaluation=evaluation,
        )
    )


def test_both_sources_present_falls_into_both_bucket() -> None:
    Session = _session_factory()
    with Session() as sess:
        _add_evaluator_trace(
            sess,
            failure_categories=["missing_metrics"],
            failure_reason="缺少量化指标",
            weaknesses=["缺少量化指标"],
            rubric_coverage={},
        )
        sess.commit()

        stats = compute_failure_category_overlap_stats(session=sess)

    assert stats.sample_size == 1
    assert stats.both == 1
    assert stats.llm_only == 0
    assert stats.normalize_only == 0
    assert stats.neither == 0


def test_llm_only_bucket() -> None:
    """LLM emitted a category that the keyword normalizer can't match."""
    Session = _session_factory()
    with Session() as sess:
        _add_evaluator_trace(
            sess,
            failure_categories=["weak_prioritization"],
            failure_reason=None,
            weaknesses=[],
            rubric_coverage={},
        )
        sess.commit()

        stats = compute_failure_category_overlap_stats(session=sess)

    assert stats.llm_only == 1
    assert stats.both == 0
    assert stats.normalize_only == 0
    assert stats.neither == 0


def test_normalize_only_bucket() -> None:
    """LLM emitted nothing but the keyword normalizer hits a category."""
    Session = _session_factory()
    with Session() as sess:
        _add_evaluator_trace(
            sess,
            failure_categories=[],
            failure_reason="缺少量化指标",
            weaknesses=["缺少量化指标"],
            rubric_coverage={},
        )
        sess.commit()

        stats = compute_failure_category_overlap_stats(session=sess)

    assert stats.normalize_only == 1
    assert stats.llm_only == 0
    assert stats.both == 0
    assert stats.neither == 0


def test_neither_bucket_when_both_sources_empty() -> None:
    Session = _session_factory()
    with Session() as sess:
        _add_evaluator_trace(
            sess,
            failure_categories=[],
            failure_reason=None,
            weaknesses=[],
            rubric_coverage={},
        )
        sess.commit()

        stats = compute_failure_category_overlap_stats(session=sess)

    assert stats.neither == 1
    assert stats.sample_size == 1
    assert stats.llm_only == 0
    assert stats.normalize_only == 0
    assert stats.both == 0


def test_mixed_sample_sums_to_sample_size_and_respects_limit() -> None:
    """Multiple rows across all 4 buckets are counted; ``limit`` caps
    the scan window."""
    Session = _session_factory()
    with Session() as sess:
        _add_evaluator_trace(
            sess,
            failure_categories=["missing_metrics"],
            failure_reason="量化",
            weaknesses=["量化指标"],
        )
        _add_evaluator_trace(
            sess,
            failure_categories=["weak_prioritization"],
            failure_reason=None,
            weaknesses=[],
        )
        _add_evaluator_trace(
            sess,
            failure_categories=[],
            failure_reason="架构边界不清",
            weaknesses=["架构边界"],
        )
        _add_evaluator_trace(
            sess,
            failure_categories=[],
            failure_reason=None,
            weaknesses=[],
        )
        # Non-evaluator trace must NOT be counted.
        sess.add(
            GenerationTrace(
                trace_id="other-trace",
                session_id="sess-x",
                turn_idx=1,
                node="ask_question",
                evaluation={
                    "failure_categories": ["missing_metrics"],
                    "failure_reason": "should be ignored",
                },
            )
        )
        sess.commit()

        stats = compute_failure_category_overlap_stats(session=sess)

    assert stats.sample_size == 4
    assert stats.both == 1
    assert stats.llm_only == 1
    assert stats.normalize_only == 1
    assert stats.neither == 1


def test_skips_rows_with_missing_evaluation_snapshot() -> None:
    Session = _session_factory()
    with Session() as sess:
        sess.add(
            GenerationTrace(
                trace_id="empty-trace",
                session_id="sess-x",
                turn_idx=0,
                node="evaluator",
                evaluation=None,
            )
        )
        _add_evaluator_trace(
            sess,
            failure_categories=["missing_metrics"],
            failure_reason="量化",
            weaknesses=["量化指标"],
        )
        sess.commit()

        stats = compute_failure_category_overlap_stats(session=sess)

    assert stats.sample_size == 1
    assert stats.both == 1
