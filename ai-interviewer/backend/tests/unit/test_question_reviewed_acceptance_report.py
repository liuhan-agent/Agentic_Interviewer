from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.base import Base
from app.models.question_bank import QuestionVariant
from app.scripts.report_reviewed_acceptance_coverage import main as report_script_main
from app.services.question_reviewed_acceptance_report import (
    aggregate_reviewed_acceptance_diagnostics,
    build_reviewed_acceptance_report,
)
from app.services.question_seed_import import import_question_seed_dir


def _session_factory():
    engine = create_engine(
        "sqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)


def _reviewed_check(
    check_id: str,
    *,
    status: str,
    source: str = "must_cover",
    source_text: str = "consistency target",
    acceptance_check: str = "Answer defines the target consistency level.",
    seed_version: int = 2,
    variant_version: int = 3,
) -> dict[str, Any]:
    return {
        "check_id": check_id,
        "source": source,
        "source_text": source_text,
        "acceptance_check": acceptance_check,
        "severity": "core" if source == "must_cover" else "supporting",
        "review_status": status,
        "version": 1,
        "reviewed_seed_version": seed_version,
        "reviewed_variant_version": variant_version,
        "reviewed_by": "qa-lead" if status != "draft" else "",
        "reviewed_at": "2026-06-01" if status != "draft" else "",
    }


def _variant_yaml(
    variant_id: str,
    *,
    version: int = 3,
    checks: list[dict[str, Any]] | None = None,
) -> str:
    extra = ""
    if checks is not None:
        rendered = yaml.safe_dump(
            {"reviewed_acceptance_checks": checks},
            allow_unicode=True,
            sort_keys=False,
        )
        extra = "\n".join(f"        {line}" for line in rendered.splitlines())
        extra = f"\n{extra}"
    return f"""
      - id: {variant_id}
        version: {version}
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
        good_answer_hints: [define consistency target first]{extra}
        priority: 10
        status: active
"""


def _seed_yaml(*, include_mismatch_check: bool = False) -> str:
    reviewed = _reviewed_check(
        "reviewed:v-reviewed:core:v1",
        status="reviewed",
        seed_version=1,
        variant_version=2,
    )
    draft = _reviewed_check(
        "reviewed:v-draft:core:v1",
        status="draft",
        source_text="failure window",
        acceptance_check="Answer names the failure window.",
    )
    deprecated = _reviewed_check(
        "reviewed:v-deprecated:core:v1",
        status="deprecated",
        source="manual",
        source_text="old manual check",
        acceptance_check="Answer names old manual evidence.",
    )
    if include_mismatch_check:
        reviewed["acceptance_check"] = "YAML-side acceptance text."
    return f"""
dimension: system_design
seeds:
  - id: system_design.cache_consistency
    version: 2
    title: Cache consistency
    dimension: system_design
    job_levels: [junior, mid, senior]
    skill_tags: [redis, cache]
    direction_tags: [internet_tech]
    role_tags: [java_backend]
    rubric:
      must_cover: [consistency target, failure window]
      minimum_bar: Explains consistency and failure windows.
    priority: 20
    status: active
    source: manual_yaml
    scope: global
    language: zh-CN
    variants:
{_variant_yaml("system_design.cache_consistency.v_reviewed", checks=[reviewed])}
{_variant_yaml("system_design.cache_consistency.v_draft", checks=[draft])}
{_variant_yaml("system_design.cache_consistency.v_deprecated", checks=[deprecated])}
{_variant_yaml("system_design.cache_consistency.v_none")}
""".lstrip()


def _write_seed_dir(tmp_path: Path, yaml_text: str | None = None) -> Path:
    seed_dir = tmp_path / "question_seeds"
    seed_dir.mkdir()
    (seed_dir / "system_design.yaml").write_text(
        yaml_text or _seed_yaml(),
        encoding="utf-8",
    )
    return seed_dir


def test_yaml_report_counts_status_coverage_stale_and_compiled_fallback(
    tmp_path: Path,
) -> None:
    seed_dir = _write_seed_dir(tmp_path)

    report = build_reviewed_acceptance_report(yaml_path=seed_dir)
    payload = report.as_dict()

    assert payload["total_seeds"] == 1
    assert payload["total_variants"] == 4
    assert payload["variants_with_reviewed"] == 1
    assert payload["variants_with_only_draft"] == 1
    assert payload["variants_with_deprecated"] == 1
    assert payload["variants_without_reviewed"] == 3
    assert payload["reviewed_status_counts"] == {
        "reviewed": 1,
        "draft": 1,
        "deprecated": 1,
    }
    assert payload["variants_with_compiled_fallback_available"] == 4
    assert payload["stale_reviewed_checks"] == [
        {
            "seed_id": "system_design.cache_consistency",
            "variant_id": "system_design.cache_consistency.v_reviewed",
            "check_id": "reviewed:v-reviewed:core:v1",
            "reviewed_seed_version": 1,
            "current_seed_version": 2,
            "reviewed_variant_version": 2,
            "current_variant_version": 3,
        }
    ]
    assert payload["db_yaml_mismatches"] == []


def test_db_report_reads_imported_checks_and_detects_yaml_db_mismatch(
    tmp_path: Path,
) -> None:
    seed_dir = _write_seed_dir(tmp_path, _seed_yaml(include_mismatch_check=True))
    session_local = _session_factory()
    with session_local() as sess:
        import_question_seed_dir(seed_dir, session=sess)
        variant = sess.get(
            QuestionVariant,
            "system_design.cache_consistency.v_reviewed",
        )
        assert variant is not None
        checks = list(variant.reviewed_acceptance_checks or [])
        checks[0] = {**checks[0], "acceptance_check": "DB-side acceptance text."}
        variant.reviewed_acceptance_checks = checks
        sess.commit()

        db_report = build_reviewed_acceptance_report(session=sess)
        mismatch_report = build_reviewed_acceptance_report(
            yaml_path=seed_dir,
            session=sess,
        )

    assert db_report.total_variants == 4
    assert db_report.variants_with_reviewed == 1
    mismatches = mismatch_report.as_dict()["db_yaml_mismatches"]
    assert mismatches == [
        {
            "variant_id": "system_design.cache_consistency.v_reviewed",
            "check_id": "reviewed:v-reviewed:core:v1",
            "reason": "field_mismatch",
            "fields": ["acceptance_check"],
        }
    ]


def test_report_script_prints_json_and_is_read_only(
    tmp_path: Path,
    capsys,
) -> None:
    seed_dir = _write_seed_dir(tmp_path)
    before = (seed_dir / "system_design.yaml").read_text(encoding="utf-8")

    report_script_main(str(seed_dir))

    output = yaml.safe_load(capsys.readouterr().out)
    assert output["total_variants"] == 4
    assert output["variants_with_reviewed"] == 1
    assert (seed_dir / "system_design.yaml").read_text(encoding="utf-8") == before


def test_runtime_diagnostics_aggregation_counts_reviewed_observability() -> None:
    summary = aggregate_reviewed_acceptance_diagnostics(
        [
            {
                "reviewed_acceptance_source": "reviewed",
                "reviewed_acceptance_present": True,
                "reviewed_acceptance_applied": True,
                "reviewed_acceptance_missing_from_final": [],
            },
            {
                "contract_diagnostics": {
                    "reviewed_acceptance_source": "compiled_fallback",
                    "reviewed_acceptance_present": False,
                    "reviewed_acceptance_applied": False,
                    "reviewed_acceptance_missing_from_final": [
                        "Answer explicitly covers consistency target."
                    ],
                }
            },
            {
                "reviewed_acceptance_source": "none",
                "reviewed_acceptance_present": False,
                "reviewed_acceptance_applied": False,
            },
        ]
    )

    assert summary == {
        "total_traces": 3,
        "reviewed_acceptance_source_counts": {
            "reviewed": 1,
            "compiled_fallback": 1,
            "none": 1,
        },
        "reviewed_acceptance_present_count": 1,
        "reviewed_acceptance_applied_count": 1,
        "reviewed_acceptance_compiled_fallback_count": 1,
        "reviewed_acceptance_missing_from_final_count": 1,
    }
