from __future__ import annotations

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
from app.models.question_bank import QuestionRerankUsage
from app.services.question_fit_profile import build_question_fit_profile
from app.services.question_reranker import (
    record_question_rerank_usage,
    rerank_question_candidates,
)
from app.services.question_selector import QuestionCandidate


def _candidate(variant_id: str, *, rank: int) -> QuestionCandidate:
    return QuestionCandidate(
        seed_id=variant_id.rsplit(".", 1)[0],
        variant_id=variant_id,
        seed_version=1,
        variant_version=1,
        rank=rank,
        match_score=40.0 - rank,
        match_reasons=["priority:30"],
        injected=False,
        title=variant_id,
        dimension="system_design",
        seed_priority=20,
        variant_priority=10,
        skill_tags=["redis"],
        direction_tags=["internet_tech"],
        role_tags=["java_backend"],
        rubric={},
        intent="opening",
        difficulty="standard",
        scenario_brief=f"scenario {variant_id}",
        question_stem=f"stem {variant_id}",
        prompt_template=f"prompt {variant_id}",
        scenario_skill_tags=["redis"],
        resume_anchor_hints=["redis"],
        failure_categories=["missing_metrics"],
        rubric_additions=[],
        expected_signals=[],
        anti_patterns=[],
        good_answer_hints=[],
    )


def _profile():
    return build_question_fit_profile(
        candidate={"resume_parsed": {"projects": [{"name": "Inventory", "tech_stack": ["Redis"]}]}},
        self_intro_profile={},
        job_spec={"required_skills": ["Redis"]},
        target_skills=["Redis"],
        resume_anchor={"project_name": "Inventory", "tech_stack": ["Redis"]},
        pending_contract_hints=None,
        dimension="system_design",
        probe_intent="opening",
    )


def _session_factory():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)


def test_reranker_skips_vector_disabled_and_small_candidate_set(monkeypatch) -> None:
    calls: list[object] = []
    monkeypatch.setattr(
        "app.services.question_reranker.call_chat",
        lambda *_args, **_kwargs: calls.append(_kwargs) or "{}",
    )

    candidate = _candidate("system_design.cache.opening", rank=1)

    assert rerank_question_candidates(
        candidates=[candidate],
        fit_profile=_profile(),
        question_selector_mode="structured_shadow",
        enabled=True,
    ).status == "skipped"
    assert rerank_question_candidates(
        candidates=[candidate, _candidate("system_design.queue.opening", rank=2)],
        fit_profile=_profile(),
        question_selector_mode="vector",
        enabled=True,
    ).status == "skipped"
    assert rerank_question_candidates(
        candidates=[candidate, _candidate("system_design.queue.opening", rank=2)],
        fit_profile=_profile(),
        question_selector_mode="structured_shadow",
        enabled=False,
    ).status == "skipped"
    assert calls == []


def test_reranker_reranks_top3_only_and_keeps_valid_ids(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_call_chat(messages, **kwargs):
        captured["messages"] = messages
        captured.update(kwargs)
        return (
            '{"ranked_variant_ids":["system_design.queue.opening",'
            '"system_design.cache.opening"],'
            '"fit_scores":{"system_design.queue.opening":0.91},'
            '"anchor_choice":"Inventory",'
            '"reasons":["more project aligned"],'
            '"confidence":0.77}'
        )

    monkeypatch.setattr("app.services.question_reranker.call_chat", fake_call_chat)

    result = rerank_question_candidates(
        candidates=[
            _candidate("system_design.cache.opening", rank=1),
            _candidate("system_design.queue.opening", rank=2),
            _candidate("system_design.capacity.opening", rank=3),
            _candidate("system_design.ignored.opening", rank=4),
        ],
        fit_profile=_profile(),
        question_selector_mode="structured_shadow",
        enabled=True,
        timeout_ms=3500,
    )

    assert result.status == "ok"
    assert result.preferred_variant_id == "system_design.queue.opening"
    assert result.ranked_variant_ids == [
        "system_design.queue.opening",
        "system_design.cache.opening",
        "system_design.capacity.opening",
    ]
    assert "system_design.ignored.opening" not in str(captured["messages"])
    assert captured["request_timeout"] == 3.5
    assert captured["max_retries"] == 0


def test_reranker_failure_records_error_without_raising(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.question_reranker.call_chat",
        lambda *_args, **_kwargs: "not json",
    )

    result = rerank_question_candidates(
        candidates=[
            _candidate("system_design.cache.opening", rank=1),
            _candidate("system_design.queue.opening", rank=2),
        ],
        fit_profile=_profile(),
        question_selector_mode="structured_shadow",
        enabled=True,
    )

    assert result.status == "error"
    assert result.error
    assert result.preferred_variant_id is None


def test_record_question_rerank_usage_round_trip() -> None:
    session_local = _session_factory()
    candidates = [
        _candidate("system_design.cache.opening", rank=1),
        _candidate("system_design.queue.opening", rank=2),
    ]
    result = rerank_question_candidates(
        candidates=candidates,
        fit_profile=_profile(),
        question_selector_mode="structured_shadow",
        enabled=False,
    )
    result = result.with_result(
        status="ok",
        preferred_variant_id="system_design.queue.opening",
        ranked_variant_ids=["system_design.queue.opening", "system_design.cache.opening"],
        fit_scores={"system_design.queue.opening": 0.9},
        anchor_choice="Inventory",
        reasons=["more aligned"],
        confidence=0.8,
        model="shadow-model",
        latency_ms=123,
        error=None,
    )

    with session_local() as sess:
        record_question_rerank_usage(
            result=result,
            candidates=candidates,
            session_id="sess-1",
            turn_idx=2,
            trace_id="trace-1",
            dimension="system_design",
            probe_intent="opening",
            question_selector_mode="structured_shadow",
            session=sess,
        )
        sess.commit()
        row = sess.scalar(select(QuestionRerankUsage))

    assert row is not None
    assert row.rule_top_variant_id == "system_design.cache.opening"
    assert row.llm_top_variant_id == "system_design.queue.opening"
    assert row.ranked_variant_ids == [
        "system_design.queue.opening",
        "system_design.cache.opening",
    ]
    assert row.confidence == 0.8
