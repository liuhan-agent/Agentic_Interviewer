"""Author draft reviewed acceptance checks from deterministic seed contracts."""
from __future__ import annotations

import hashlib
import re
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from app.engine.contracts.acceptance_compiler import compile_locked_acceptance_checks
from app.engine.contracts.seed_contract import build_locked_core_contract
from app.services.question_seed_import import parse_question_seed_dir


@dataclass(frozen=True)
class VariantAuthoringReport:
    seed_id: str
    variant_id: str
    existing_reviewed_acceptance_checks: int = 0
    generated_checks: list[dict[str, Any]] = field(default_factory=list)
    stale_checks: list[dict[str, Any]] = field(default_factory=list)
    skipped_reasons: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "seed_id": self.seed_id,
            "variant_id": self.variant_id,
            "existing_reviewed_acceptance_checks": (
                self.existing_reviewed_acceptance_checks
            ),
            "generated_checks": [dict(check) for check in self.generated_checks],
            "stale_checks": [dict(check) for check in self.stale_checks],
            "skipped_reasons": [dict(reason) for reason in self.skipped_reasons],
        }


@dataclass(frozen=True)
class ReviewedAcceptanceAuthoringResult:
    path: str
    would_write: bool
    scanned_seeds: int = 0
    scanned_variants: int = 0
    variants_with_existing_reviewed_checks: int = 0
    draft_checks_generated: int = 0
    variants_changed: int = 0
    stale_checks: list[dict[str, Any]] = field(default_factory=list)
    skipped_reasons: list[dict[str, Any]] = field(default_factory=list)
    variant_reports: list[VariantAuthoringReport] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "would_write": self.would_write,
            "scanned_seeds": self.scanned_seeds,
            "scanned_variants": self.scanned_variants,
            "variants_with_existing_reviewed_checks": (
                self.variants_with_existing_reviewed_checks
            ),
            "draft_checks_generated": self.draft_checks_generated,
            "variants_changed": self.variants_changed,
            "stale_checks": [dict(check) for check in self.stale_checks],
            "skipped_reasons": [dict(reason) for reason in self.skipped_reasons],
            "variant_reports": [report.as_dict() for report in self.variant_reports],
        }


def author_reviewed_acceptance_checks(
    path: Path,
    *,
    write: bool = False,
) -> ReviewedAcceptanceAuthoringResult:
    """Generate draft reviewed acceptance checks for a seed file or directory.

    Dry-run is the default. When ``write`` is true, the service still only
    appends missing draft checks and preserves every existing check verbatim.
    """

    root = Path(path)
    _validate_with_import_parser(root)
    yaml_paths = _seed_yaml_paths(root)
    total_seeds = 0
    total_variants = 0
    variants_with_existing = 0
    draft_checks_generated = 0
    variants_changed = 0
    all_stale: list[dict[str, Any]] = []
    all_skipped: list[dict[str, Any]] = []
    reports: list[VariantAuthoringReport] = []

    for yaml_path in yaml_paths:
        raw = _load_yaml_mapping(yaml_path)
        seeds = raw.get("seeds")
        if not isinstance(seeds, list):
            all_skipped.append(
                {
                    "path": str(yaml_path),
                    "reason": "missing_seeds",
                }
            )
            continue

        file_changed = False
        for seed in seeds:
            if not isinstance(seed, dict):
                continue
            total_seeds += 1
            seed_id = str(seed.get("id") or "").strip()
            seed_version = _safe_int(seed.get("version"))
            variants = seed.get("variants")
            if not isinstance(variants, list):
                continue
            for variant in variants:
                if not isinstance(variant, dict):
                    continue
                total_variants += 1
                report, generated = _author_variant(
                    seed=seed,
                    seed_id=seed_id,
                    seed_version=seed_version,
                    variant=variant,
                )
                reports.append(report)
                if report.existing_reviewed_acceptance_checks:
                    variants_with_existing += 1
                if report.stale_checks:
                    all_stale.extend(report.stale_checks)
                if report.skipped_reasons:
                    all_skipped.extend(report.skipped_reasons)
                if generated:
                    draft_checks_generated += len(generated)
                    variants_changed += 1
                    file_changed = True
                    if write:
                        checks = variant.setdefault("reviewed_acceptance_checks", [])
                        if isinstance(checks, list):
                            checks.extend(generated)

        if write and file_changed:
            yaml_path.write_text(
                yaml.safe_dump(raw, allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )

    return ReviewedAcceptanceAuthoringResult(
        path=str(root),
        would_write=bool(write),
        scanned_seeds=total_seeds,
        scanned_variants=total_variants,
        variants_with_existing_reviewed_checks=variants_with_existing,
        draft_checks_generated=draft_checks_generated,
        variants_changed=variants_changed,
        stale_checks=all_stale,
        skipped_reasons=all_skipped,
        variant_reports=reports,
    )


def _author_variant(
    *,
    seed: dict[str, Any],
    seed_id: str,
    seed_version: int,
    variant: dict[str, Any],
) -> tuple[VariantAuthoringReport, list[dict[str, Any]]]:
    variant_id = str(variant.get("id") or "").strip()
    variant_version = _safe_int(variant.get("version"))
    existing = variant.get("reviewed_acceptance_checks")
    existing_checks = existing if isinstance(existing, list) else []
    existing_ids = {
        str(check.get("check_id") or "").strip()
        for check in existing_checks
        if isinstance(check, dict) and str(check.get("check_id") or "").strip()
    }
    existing_source_keys = {
        _source_key(check)
        for check in existing_checks
        if isinstance(check, dict) and _source_key(check) is not None
    }
    stale_checks = [
        stale
        for check in existing_checks
        if isinstance(check, dict)
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
    ]

    locked_core = build_locked_core_contract(
        contract_hints={
            "question_seed": {
                "seed_id": seed_id,
                "variant_id": variant_id,
                "seed_version": seed_version,
                "variant_version": variant_version,
                "rubric": seed.get("rubric") or {},
                "rubric_additions": list(variant.get("rubric_additions") or []),
            }
        },
        target_difficulty="medium",
    )
    compiled_checks = compile_locked_acceptance_checks(locked_core)
    generated: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    if not locked_core:
        skipped.append(
            {
                "seed_id": seed_id,
                "variant_id": variant_id,
                "reason": "no_locked_core",
            }
        )

    for compiled in compiled_checks:
        draft = _draft_from_compiled(
            compiled,
            variant_id=variant_id,
            seed_version=seed_version,
            variant_version=variant_version,
        )
        source_key = _source_key(draft)
        if draft["check_id"] in existing_ids:
            skipped.append(
                {
                    "seed_id": seed_id,
                    "variant_id": variant_id,
                    "reason": "duplicate_check_id",
                    "check_id": draft["check_id"],
                }
            )
            continue
        if source_key in existing_source_keys:
            skipped.append(
                {
                    "seed_id": seed_id,
                    "variant_id": variant_id,
                    "reason": "duplicate_source_text",
                    "source": draft["source"],
                    "source_text": draft["source_text"],
                }
            )
            continue
        generated.append(draft)
        existing_ids.add(draft["check_id"])
        if source_key is not None:
            existing_source_keys.add(source_key)

    report = VariantAuthoringReport(
        seed_id=seed_id,
        variant_id=variant_id,
        existing_reviewed_acceptance_checks=len(existing_checks),
        generated_checks=[dict(check) for check in generated],
        stale_checks=stale_checks,
        skipped_reasons=skipped,
    )
    return report, generated


def _draft_from_compiled(
    compiled: dict[str, Any],
    *,
    variant_id: str,
    seed_version: int,
    variant_version: int,
) -> dict[str, Any]:
    source = str(compiled.get("source") or "").strip()
    source_text = str(compiled.get("source_text") or "").strip()
    return {
        "check_id": _reviewed_check_id(
            variant_id=variant_id,
            source=source,
            source_text=source_text,
        ),
        "source": source,
        "source_text": source_text,
        "acceptance_check": str(compiled.get("acceptance_check") or "").strip(),
        "severity": str(compiled.get("severity") or "").strip(),
        "review_status": "draft",
        "version": 1,
        "reviewed_seed_version": seed_version,
        "reviewed_variant_version": variant_version,
        "reviewed_by": "",
        "reviewed_at": "",
    }


def _reviewed_check_id(*, variant_id: str, source: str, source_text: str) -> str:
    digest = hashlib.sha1(
        f"{_normalise(source)}|{_normalise_source_text(source_text)}".encode("utf-8")
    ).hexdigest()[:12]
    return f"reviewed:{variant_id}:{source}:{digest}:v1"


def _source_key(check: dict[str, Any]) -> tuple[str, str] | None:
    source = str(check.get("source") or "").strip()
    source_text = str(check.get("source_text") or "").strip()
    if not source or not source_text:
        return None
    return (_normalise(source), _normalise_source_text(source_text))


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


def _validate_with_import_parser(path: Path) -> None:
    if path.is_dir():
        parse_question_seed_dir(path)
        return
    if path.is_file():
        with tempfile.TemporaryDirectory() as tmp:
            temp_dir = Path(tmp)
            shutil.copy2(path, temp_dir / path.name)
            parse_question_seed_dir(temp_dir)
        return
    raise FileNotFoundError(path)


def _seed_yaml_paths(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    if path.is_dir():
        return sorted(path.glob("*.yaml"))
    return []


def _load_yaml_mapping(path: Path) -> dict[str, Any]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return {}
    return raw


def _normalise(value: str) -> str:
    return re.sub(r"\s+", "", str(value or "").strip().lower())


def _normalise_source_text(value: str) -> str:
    return _normalise(value)


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except Exception:
        return 0
