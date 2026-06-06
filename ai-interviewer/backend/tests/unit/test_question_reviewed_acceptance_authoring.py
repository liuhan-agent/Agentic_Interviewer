from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.v1 import admin as admin_api
from app.engine.workflow.nodes import ask_question as ask_mod
from app.models.base import Base
from app.models.question_bank import QuestionVariant
from app.scripts.author_reviewed_acceptance_checks import main as authoring_script_main
from app.services.question_reviewed_acceptance_authoring import (
    author_reviewed_acceptance_checks,
)
from app.services.question_seed_import import import_question_seed_dir
from app.services.question_seed_lint import lint_question_seed_dir
from app.services.question_selector import select_question_candidates


def _seed_yaml(
    *,
    seed_version: int = 2,
    variant_version: int = 3,
    reviewed_acceptance_checks: list[dict[str, Any]] | None = None,
) -> str:
    variant_extra = ""
    if reviewed_acceptance_checks is not None:
        rendered = yaml.safe_dump(
            {"reviewed_acceptance_checks": reviewed_acceptance_checks},
            allow_unicode=True,
            sort_keys=False,
        )
        variant_extra = "\n".join(f"        {line}" for line in rendered.splitlines())
        variant_extra = f"\n{variant_extra}"
    return f"""
dimension: system_design
seeds:
  - id: system_design.cache_consistency
    version: {seed_version}
    title: Cache consistency
    dimension: system_design
    job_levels: [junior, mid, senior]
    skill_tags: [redis, cache]
    direction_tags: [internet_tech]
    role_tags: [java_backend]
    rubric:
      must_cover: [consistency target, failure window]
      minimum_bar: Explains the consistency target and failure window.
    priority: 20
    status: active
    source: manual_yaml
    scope: global
    language: zh-CN
    variants:
      - id: system_design.cache_consistency.flash_sale_inventory
        version: {variant_version}
        intent: opening
        difficulty: standard
        scenario_brief: Flash sale inventory reads are cache-heavy.
        question_stem: Design a cache consistency approach.
        prompt_template: Ask one system design question.
        scenario_skill_tags: [redis]
        resume_anchor_hints: [cache]
        failure_categories: [missing_metrics]
        rubric_additions: [invalidation window]
        expected_signals: [distinguishes strong and eventual consistency]
        anti_patterns: [only says add lock]
        good_answer_hints: [define consistency target first]{variant_extra}
        priority: 10
        status: active
""".lstrip()


def _write_seed_dir(tmp_path: Path, yaml_text: str) -> Path:
    seed_dir = tmp_path / "question_seeds"
    seed_dir.mkdir()
    (seed_dir / "system_design.yaml").write_text(yaml_text, encoding="utf-8")
    return seed_dir


def _load_variant_checks(seed_dir: Path) -> list[dict[str, Any]]:
    raw = yaml.safe_load((seed_dir / "system_design.yaml").read_text(encoding="utf-8"))
    return raw["seeds"][0]["variants"][0].get("reviewed_acceptance_checks") or []


def _session_factory():
    engine = create_engine(
        "sqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)


def test_authoring_dry_run_generates_drafts_without_mutating_yaml(tmp_path: Path) -> None:
    seed_dir = _write_seed_dir(tmp_path, _seed_yaml())
    original = (seed_dir / "system_design.yaml").read_text(encoding="utf-8")

    result = author_reviewed_acceptance_checks(seed_dir)

    assert result.scanned_seeds == 1
    assert result.scanned_variants == 1
    assert result.draft_checks_generated == 3
    assert result.variants_changed == 1
    assert result.would_write is False
    assert (seed_dir / "system_design.yaml").read_text(encoding="utf-8") == original
    generated = result.variant_reports[0].generated_checks
    assert [check["source"] for check in generated] == [
        "must_cover",
        "must_cover",
        "rubric_addition",
    ]
    assert generated[0]["check_id"].startswith(
        "reviewed:system_design.cache_consistency.flash_sale_inventory:must_cover:"
    )
    assert generated[0]["review_status"] == "draft"
    assert generated[0]["reviewed_seed_version"] == 2
    assert generated[0]["reviewed_variant_version"] == 3
    assert generated[0]["reviewed_by"] == ""
    assert generated[0]["reviewed_at"] == ""


def test_authoring_script_defaults_to_dry_run_and_prints_summary(
    tmp_path: Path,
    capsys,
) -> None:
    seed_dir = _write_seed_dir(tmp_path, _seed_yaml())
    original = (seed_dir / "system_design.yaml").read_text(encoding="utf-8")

    authoring_script_main(str(seed_dir))

    output = yaml.safe_load(capsys.readouterr().out)
    assert output["draft_checks_generated"] == 3
    assert output["would_write"] is False
    assert (seed_dir / "system_design.yaml").read_text(encoding="utf-8") == original


def test_authoring_write_preserves_existing_skips_duplicates_and_reports_stale(
    tmp_path: Path,
) -> None:
    existing = [
        {
            "check_id": "reviewed:existing:core:v1",
            "source": "must_cover",
            "source_text": "consistency target",
            "acceptance_check": "Answer defines the target consistency level.",
            "severity": "core",
            "review_status": "reviewed",
            "version": 1,
            "reviewed_seed_version": 1,
            "reviewed_variant_version": 2,
            "reviewed_by": "qa-lead",
            "reviewed_at": "2026-06-01",
        },
        {
            "check_id": "reviewed:existing:draft:v1",
            "source": "rubric_addition",
            "source_text": "invalidation window",
            "acceptance_check": "Draft check that should remain untouched.",
            "severity": "supporting",
            "review_status": "draft",
            "version": 1,
            "reviewed_seed_version": 2,
            "reviewed_variant_version": 3,
            "reviewed_by": "",
            "reviewed_at": "",
        },
        {
            "check_id": "reviewed:existing:deprecated:v1",
            "source": "manual",
            "source_text": "old manual check",
            "acceptance_check": "Deprecated manual check should remain untouched.",
            "severity": "supporting",
            "review_status": "deprecated",
            "version": 1,
            "reviewed_seed_version": 2,
            "reviewed_variant_version": 3,
            "reviewed_by": "qa-lead",
            "reviewed_at": "2026-06-01",
        },
    ]
    seed_dir = _write_seed_dir(
        tmp_path,
        _seed_yaml(reviewed_acceptance_checks=existing),
    )

    result = author_reviewed_acceptance_checks(seed_dir, write=True)
    checks = _load_variant_checks(seed_dir)

    assert result.would_write is True
    assert result.variants_with_existing_reviewed_checks == 1
    assert result.draft_checks_generated == 1
    assert result.stale_checks == [
        {
            "seed_id": "system_design.cache_consistency",
            "variant_id": "system_design.cache_consistency.flash_sale_inventory",
            "check_id": "reviewed:existing:core:v1",
            "reviewed_seed_version": 1,
            "current_seed_version": 2,
            "reviewed_variant_version": 2,
            "current_variant_version": 3,
        }
    ]
    assert checks[:3] == existing
    assert len(checks) == 4
    assert checks[-1]["source_text"] == "failure window"
    assert checks[-1]["review_status"] == "draft"


def test_authoring_write_generates_yaml_that_lints_and_imports_to_runtime_copy(
    tmp_path: Path,
    monkeypatch,
) -> None:
    seed_dir = _write_seed_dir(tmp_path, _seed_yaml())
    author_reviewed_acceptance_checks(seed_dir, write=True)

    lint_result = lint_question_seed_dir(
        seed_dir,
        strict=True,
        min_active_variants=1,
        check_role_coverage=False,
    )
    assert lint_result.passed is True

    raw = yaml.safe_load((seed_dir / "system_design.yaml").read_text(encoding="utf-8"))
    checks = raw["seeds"][0]["variants"][0]["reviewed_acceptance_checks"]
    checks[0]["review_status"] = "reviewed"
    checks[0]["reviewed_by"] = "qa-lead"
    checks[0]["reviewed_at"] = "2026-06-01"
    (seed_dir / "system_design.yaml").write_text(
        yaml.safe_dump(raw, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    session_local = _session_factory()
    with session_local() as sess:
        import_question_seed_dir(seed_dir, session=sess)
        sess.commit()
        variant = sess.get(
            QuestionVariant,
            "system_design.cache_consistency.flash_sale_inventory",
        )
        selection = select_question_candidates(
            sess,
            dimension="system_design",
            job_level="senior",
            target_skills=["redis"],
            direction_tags=["internet_tech"],
            role_tags=["java_backend"],
            probe_intent="opening",
        )

    assert variant is not None
    assert variant.reviewed_acceptance_checks[0]["review_status"] == "reviewed"
    assert selection.candidates[0].reviewed_acceptance_checks[0]["review_status"] == (
        "reviewed"
    )

    app = FastAPI()
    app.include_router(admin_api.router)
    app.include_router(admin_api.api_v1_router)

    @contextmanager
    def get_session():
        with session_local() as sess:
            yield sess
            sess.commit()

    admin_api.get_session = get_session
    admin_api.get_settings = lambda: SimpleNamespace(
        api_token=None,
        allow_open_admin=True,
        knowledge_dir=seed_dir.parent,
    )
    client = TestClient(app)

    response = client.get("/admin/question-seeds/system_design.cache_consistency")
    assert response.status_code == 200
    admin_checks = response.json()["variants"][0]["reviewed_acceptance_checks"]
    assert admin_checks[0]["review_status"] == "reviewed"

    captured_trace: dict[str, Any] = {}

    class _Tracer:
        def trace_node_event(self, _state, *, node, payload, **_kwargs):
            if node == "ask_question":
                captured_trace.update(payload)

    class _Retrieval:
        as_prompt_block = "(stub retrieval)"

    monkeypatch.setattr(ask_mod, "get_session", get_session)
    monkeypatch.setattr(ask_mod, "get_tracer", lambda: _Tracer())
    monkeypatch.setattr(ask_mod, "retrieve_for_question", lambda **_kwargs: _Retrieval())
    monkeypatch.setattr(ask_mod, "retrieve_strategies", lambda **_kwargs: [])
    monkeypatch.setattr(
        ask_mod,
        "format_strategies_for_prompt",
        lambda _entries: "(no relevant strategy memories)",
    )
    monkeypatch.setattr(ask_mod, "record_question_usages", lambda **_kwargs: None)
    monkeypatch.setattr(
        ask_mod,
        "get_settings",
        lambda: SimpleNamespace(
            question_selector_mode="structured_primary",
            contract_core_mode="shadow",
            contract_acceptance_mode="shadow",
            enable_question_fit_profile=False,
            enable_question_reranker_shadow=False,
        ),
    )
    monkeypatch.setattr(
        ask_mod,
        "generate_question",
        lambda **kwargs: {
            "question": "How would you design cache consistency?",
            "dimension": kwargs["dimension"],
            "proposed_contract": {
                "must_cover": ["negotiated"],
                "acceptance_checks": ["Answer names one negotiated item."],
                "minimum_bar": "Names one item.",
                "bar_level": "standard",
            },
        },
    )
    monkeypatch.setattr(
        ask_mod,
        "negotiate_contract_via_evaluator",
        lambda **kwargs: {
            **kwargs["proposed_contract"],
            "signed_by": ["generator", "evaluator"],
        },
    )

    out = ask_mod.ask_question_node(
        {
            "session_id": "sess-authoring",
            "trace_id": "trace-authoring",
            "job_spec": {
                "title": "Backend Engineer",
                "level": "senior",
                "required_skills": ["redis"],
                "interview_direction": "java_backend",
            },
            "candidate": {"resume_parsed": {"projects": [], "focus_areas": []}},
            "dimensions": ["system_design"],
            "dimension_status": {"system_design": "active"},
            "current_dimension": "system_design",
            "turn_idx": 1,
            "formal_turn_idx": 0,
            "qa_history": [],
            "runtime_config": {
                "question_selector_mode": "structured_primary",
                "contract_acceptance_mode": "reviewed_shadow",
            },
            "refine_mode": False,
            "current_ask_plan": None,
            "current_contract": None,
            "pending_plan_template": None,
            "pending_contract_hints": None,
            "target_difficulty": "medium",
            "selected_action": {"id": "plan_adaptive", "plan_template": "adaptive"},
        }
    )

    diagnostics = captured_trace["contract_diagnostics"]
    assert diagnostics["reviewed_acceptance_present"] is True
    assert diagnostics["reviewed_acceptance_source"] == "reviewed"
    assert diagnostics["reviewed_acceptance_checks"][0]["review_status"] == "reviewed"
    current_checks = "\n".join(out["current_contract"]["acceptance_checks"])
    assert "Answer explicitly covers consistency target." not in current_checks
