"""Read-only coverage and drift report for reviewed acceptance checks."""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.engine.contracts.acceptance_compiler import compile_locked_acceptance_checks
from app.engine.contracts.seed_contract import build_locked_core_contract
from app.models.question_bank import QuestionSeed, QuestionVariant
from app.services.question_seed_import import parse_question_seed_dir

_CHECK_COMPARE_FIELDS = (
    "review_status",
    "source",
    "source_text",
    "acceptance_check",
    "version",
)


@dataclass(frozen=True)
class ReviewedAcceptanceReport:
    total_seeds: int = 0
    total_variants: int = 0
    variants_with_reviewed: int = 0
    variants_with_only_draft: int = 0
    variants_with_deprecated: int = 0
    variants_without_reviewed: int = 0
    reviewed_status_counts: dict[str, int] = field(default_factory=dict)
    stale_reviewed_checks: list[dict[str, Any]] = field(default_factory=list)
    variants_with_compiled_fallback_available: int = 0
    db_yaml_mismatches: list[dict[str, Any]] = field(default_factory=list)
    variant_reports: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "total_seeds": self.total_seeds,
            "total_variants": self.total_variants,
            "variants_with_reviewed": self.variants_with_reviewed,
            "variants_with_only_draft": self.variants_with_only_draft,
            "variants_with_deprecated": self.variants_with_deprecated,
            "variants_without_reviewed": self.variants_without_reviewed,
            "reviewed_status_counts": dict(self.reviewed_status_counts),
            "stale_reviewed_checks": [
                dict(check) for check in self.stale_reviewed_checks
            ],
            "variants_with_compiled_fallback_available": (
                self.variants_with_compiled_fallback_available
            ),
            "db_yaml_mismatches": [
                dict(mismatch) for mismatch in self.db_yaml_mismatches
            ],
            "variant_reports": [dict(report) for report in self.variant_reports],
        }


def build_reviewed_acceptance_report(
    *,
    yaml_path: Path | None = None,
    session: Session | None = None,
) -> ReviewedAcceptanceReport:
    """Build a read-only coverage report from YAML, DB, or both."""

    yaml_records = _records_from_yaml(yaml_path) if yaml_path is not None else []
    db_records = _records_from_db(session) if session is not None else []
    primary_records = db_records if db_records else yaml_records
    mismatches = (
        _db_yaml_mismatches(yaml_records=yaml_records, db_records=db_records)
        if yaml_records and db_records
        else []
    )
    return _report_from_records(primary_records, db_yaml_mismatches=mismatches)


def reviewed_acceptance_variant_summary(
    *,
    seed_version: int,
    variant: Any,
    db_sync_status: str | None = None,
) -> dict[str, Any]:
    """Return additive per-variant admin observability fields."""

    checks = _mapping_list(getattr(variant, "reviewed_acceptance_checks", []) or [])
    status_counts = _status_counts(checks)
    stale_count = sum(
        1
        for check in checks
        if _stale_check(
            seed_id=str(getattr(variant, "seed_id", "") or ""),
            seed_version=seed_version,
            variant_id=str(getattr(variant, "id", "") or ""),
            variant_version=_safe_int(getattr(variant, "version", 0)),
            check=check,
        )
        is not None
    )
    return {
        "reviewed_count": status_counts.get("reviewed", 0),
        "draft_count": status_counts.get("draft", 0),
        "deprecated_count": status_counts.get("deprecated", 0),
        "stale_count": stale_count,
        "db_sync_status": db_sync_status or "unknown",
    }


def aggregate_reviewed_acceptance_diagnostics(
    payloads: list[dict[str, Any]],
) -> dict[str, Any]:
    """Aggregate existing trace contract_diagnostics payloads."""

    source_counts: Counter[str] = Counter()
    present_count = 0
    applied_count = 0
    missing_count = 0
    for payload in payloads:
        diagnostics = payload.get("contract_diagnostics", payload)
        if not isinstance(diagnostics, dict):
            continue
        source = str(diagnostics.get("reviewed_acceptance_source") or "none")
        source_counts[source] += 1
        if bool(diagnostics.get("reviewed_acceptance_present")):
            present_count += 1
        if bool(diagnostics.get("reviewed_acceptance_applied")):
            applied_count += 1
        missing = diagnostics.get("reviewed_acceptance_missing_from_final") or []
        if isinstance(missing, list) and missing:
            missing_count += 1
    return {
        "total_traces": len(payloads),
        "reviewed_acceptance_source_counts": dict(source_counts),
        "reviewed_acceptance_present_count": present_count,
        "reviewed_acceptance_applied_count": applied_count,
        "reviewed_acceptance_compiled_fallback_count": source_counts.get(
            "compiled_fallback", 0
        ),
        "reviewed_acceptance_missing_from_final_count": missing_count,
    }


def _records_from_yaml(path: Path) -> list[dict[str, Any]]:
    seeds, variants = parse_question_seed_dir(_parse_root(path))
    seeds_by_id = {seed.values["id"]: seed.values for seed in seeds}
    records: list[dict[str, Any]] = []
    wanted_file_variants: set[str] | None = None
    if path.is_file():
        file_seeds, file_variants = parse_question_seed_dir(path.parent)
        wanted_file_variants = {
            variant.values["id"]
            for variant in file_variants
            if _variant_belongs_to_file(path, variant.values)
        }
    for variant in variants:
        values = variant.values
        if wanted_file_variants is not None and values["id"] not in wanted_file_variants:
            continue
        seed = seeds_by_id.get(values["seed_id"])
        if seed is None:
            continue
        records.append(_record_from_values(seed=seed, variant=values))
    return records


def _records_from_db(session: Session | None) -> list[dict[str, Any]]:
    if session is None:
        return []
    rows = session.execute(
        select(QuestionSeed, QuestionVariant)
        .join(QuestionVariant, QuestionVariant.seed_id == QuestionSeed.id)
        .order_by(QuestionSeed.id, QuestionVariant.id)
    ).all()
    return [
        _record_from_values(
            seed={
                "id": seed.id,
                "version": seed.version,
                "rubric": seed.rubric or {},
            },
            variant={
                "id": variant.id,
                "seed_id": variant.seed_id,
                "version": variant.version,
                "rubric_additions": variant.rubric_additions or [],
                "reviewed_acceptance_checks": (
                    variant.reviewed_acceptance_checks or []
                ),
            },
        )
        for seed, variant in rows
    ]


def _record_from_values(
    *,
    seed: dict[str, Any],
    variant: dict[str, Any],
) -> dict[str, Any]:
    checks = _mapping_list(variant.get("reviewed_acceptance_checks") or [])
    seed_id = str(seed.get("id") or "")
    variant_id = str(variant.get("id") or "")
    seed_version = _safe_int(seed.get("version"))
    variant_version = _safe_int(variant.get("version"))
    compiled_checks = compile_locked_acceptance_checks(
        build_locked_core_contract(
            contract_hints={
                "question_seed": {
                    "seed_id": seed_id,
                    "variant_id": variant_id,
                    "seed_version": seed_version,
                    "variant_version": variant_version,
                    "rubric": seed.get("rubric") or {},
                    "rubric_additions": list(
                        variant.get("rubric_additions") or []
                    ),
                }
            },
            target_difficulty="medium",
        )
    )
    return {
        "seed_id": seed_id,
        "variant_id": variant_id,
        "seed_version": seed_version,
        "variant_version": variant_version,
        "reviewed_acceptance_checks": checks,
        "status_counts": _status_counts(checks),
        "stale_checks": [
            stale
            for check in checks
            for stale in [
                _stale_check(
                    seed_id=seed_id,
                    seed_version=seed_version,
                    variant_id=variant_id,
                    variant_version=variant_version,
                    check=check,
                )
            ]
            if stale is not None
        ],
        "compiled_fallback_available": bool(compiled_checks),
    }


def _report_from_records(
    records: list[dict[str, Any]],
    *,
    db_yaml_mismatches: list[dict[str, Any]],
) -> ReviewedAcceptanceReport:
    seed_ids = {record["seed_id"] for record in records}
    status_counts: Counter[str] = Counter()
    variants_with_reviewed = 0
    variants_with_only_draft = 0
    variants_with_deprecated = 0
    variants_without_reviewed = 0
    stale_checks: list[dict[str, Any]] = []
    compiled_available = 0
    variant_reports: list[dict[str, Any]] = []

    for record in records:
        counts = dict(record["status_counts"])
        status_counts.update(counts)
        has_reviewed = counts.get("reviewed", 0) > 0
        has_deprecated = counts.get("deprecated", 0) > 0
        has_draft = counts.get("draft", 0) > 0
        if has_reviewed:
            variants_with_reviewed += 1
        else:
            variants_without_reviewed += 1
        if has_draft and not has_reviewed and not has_deprecated:
            variants_with_only_draft += 1
        if has_deprecated:
            variants_with_deprecated += 1
        if record["compiled_fallback_available"]:
            compiled_available += 1
        stale_checks.extend(record["stale_checks"])
        variant_reports.append(
            {
                "seed_id": record["seed_id"],
                "variant_id": record["variant_id"],
                "reviewed_count": counts.get("reviewed", 0),
                "draft_count": counts.get("draft", 0),
                "deprecated_count": counts.get("deprecated", 0),
                "stale_count": len(record["stale_checks"]),
                "compiled_fallback_available": bool(
                    record["compiled_fallback_available"]
                ),
            }
        )

    return ReviewedAcceptanceReport(
        total_seeds=len(seed_ids),
        total_variants=len(records),
        variants_with_reviewed=variants_with_reviewed,
        variants_with_only_draft=variants_with_only_draft,
        variants_with_deprecated=variants_with_deprecated,
        variants_without_reviewed=variants_without_reviewed,
        reviewed_status_counts=dict(status_counts),
        stale_reviewed_checks=stale_checks,
        variants_with_compiled_fallback_available=compiled_available,
        db_yaml_mismatches=db_yaml_mismatches,
        variant_reports=variant_reports,
    )


def _db_yaml_mismatches(
    *,
    yaml_records: list[dict[str, Any]],
    db_records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    yaml_by_variant = {record["variant_id"]: record for record in yaml_records}
    db_by_variant = {record["variant_id"]: record for record in db_records}
    mismatches: list[dict[str, Any]] = []
    for variant_id in sorted(set(yaml_by_variant) | set(db_by_variant)):
        yaml_record = yaml_by_variant.get(variant_id)
        db_record = db_by_variant.get(variant_id)
        if yaml_record is None:
            mismatches.append({"variant_id": variant_id, "reason": "missing_in_yaml"})
            continue
        if db_record is None:
            mismatches.append({"variant_id": variant_id, "reason": "missing_in_db"})
            continue
        mismatches.extend(
            _check_mismatches(
                variant_id=variant_id,
                yaml_checks=yaml_record["reviewed_acceptance_checks"],
                db_checks=db_record["reviewed_acceptance_checks"],
            )
        )
    return mismatches


def _check_mismatches(
    *,
    variant_id: str,
    yaml_checks: list[dict[str, Any]],
    db_checks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    yaml_by_id = _checks_by_id(yaml_checks)
    db_by_id = _checks_by_id(db_checks)
    mismatches: list[dict[str, Any]] = []
    for check_id in sorted(set(yaml_by_id) | set(db_by_id)):
        yaml_check = yaml_by_id.get(check_id)
        db_check = db_by_id.get(check_id)
        if yaml_check is None:
            mismatches.append(
                {
                    "variant_id": variant_id,
                    "check_id": check_id,
                    "reason": "missing_in_yaml",
                }
            )
            continue
        if db_check is None:
            mismatches.append(
                {
                    "variant_id": variant_id,
                    "check_id": check_id,
                    "reason": "missing_in_db",
                }
            )
            continue
        fields = [
            field
            for field in _CHECK_COMPARE_FIELDS
            if _normalised_check_field(yaml_check, field)
            != _normalised_check_field(db_check, field)
        ]
        if fields:
            mismatches.append(
                {
                    "variant_id": variant_id,
                    "check_id": check_id,
                    "reason": "field_mismatch",
                    "fields": fields,
                }
            )
    return mismatches


def _checks_by_id(checks: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        str(check.get("check_id") or "").strip(): check
        for check in checks
        if str(check.get("check_id") or "").strip()
    }


def _status_counts(checks: list[dict[str, Any]]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for check in checks:
        status = str(check.get("review_status") or "").strip()
        if status:
            counts[status] += 1
    return dict(counts)


def _stale_check(
    *,
    seed_id: str,
    seed_version: int,
    variant_id: str,
    variant_version: int,
    check: dict[str, Any],
) -> dict[str, Any] | None:
    reviewed_seed_version = _safe_int(check.get("reviewed_seed_version"))
    reviewed_variant_version = _safe_int(check.get("reviewed_variant_version"))
    if (
        reviewed_seed_version >= seed_version
        and reviewed_variant_version >= variant_version
    ):
        return None
    return {
        "seed_id": seed_id,
        "variant_id": variant_id,
        "check_id": str(check.get("check_id") or "").strip(),
        "reviewed_seed_version": reviewed_seed_version,
        "current_seed_version": seed_version,
        "reviewed_variant_version": reviewed_variant_version,
        "current_variant_version": variant_version,
    }


def _mapping_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _parse_root(path: Path) -> Path:
    return path.parent if path.is_file() else path


def _variant_belongs_to_file(path: Path, variant: dict[str, Any]) -> bool:
    return path.stem in str(variant.get("id") or "")


def _normalised_check_field(check: dict[str, Any], field: str) -> Any:
    value = check.get(field)
    if field == "version":
        return _safe_int(value)
    return _normalise(str(value or ""))


def _normalise(value: str) -> str:
    return re.sub(r"\s+", "", str(value or "").strip().lower())


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except Exception:
        return 0
