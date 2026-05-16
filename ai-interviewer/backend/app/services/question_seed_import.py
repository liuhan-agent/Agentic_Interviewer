"""Strict YAML import for the structured question bank."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.question_bank import QuestionSeed, QuestionVariant

SUPPORTED_DIMENSIONS = {
    "system_design",
    "backend_systems",
    "technical_depth",
    "coding_quality",
    "problem_solving",
    "project_experience",
    "product_thinking",
    "leadership",
    "communication",
    "user_insight",
    "requirement_analysis",
    "prioritization",
    "metrics_thinking",
    "stakeholder_management",
    "user_growth",
    "content_operations",
    "data_analysis",
    "campaign_execution",
    "process_optimization",
    "customer_discovery",
    "solution_matching",
    "objection_handling",
    "negotiation",
    "pipeline_management",
    "market_insight",
    "brand_strategy",
    "campaign_planning",
    "channel_growth",
    "content_creativity",
}
VALID_STATUSES = {"draft", "active", "disabled", "archived"}
VALID_SCOPES = {"global", "org", "job_template"}
P0_VALID_SCOPES = {"global"}
VALID_INTENTS = {"opening", "followup", "deep_probe", "recovery"}
VALID_DIFFICULTIES = {"warmup", "standard", "deep_probe", "stretch"}
VALID_LANGUAGES = {"zh-CN"}
VALID_DIRECTION_TAGS = {"internet_tech", "business"}
VALID_ROLE_TAGS = {
    "general",
    "java_backend",
    "frontend_web",
    "sre",
    "mobile",
    "ai_fullstack",
    "ai_agent",
    "ai_algorithm",
    "architect",
    "product_manager",
    "operations",
    "sales_business",
    "marketing_brand",
}

SEED_REQUIRED = {
    "id",
    "version",
    "title",
    "dimension",
    "job_levels",
    "skill_tags",
    "direction_tags",
    "role_tags",
    "rubric",
    "priority",
    "status",
    "source",
    "scope",
    "language",
    "variants",
}
VARIANT_REQUIRED = {
    "id",
    "version",
    "intent",
    "difficulty",
    "scenario_brief",
    "question_stem",
    "prompt_template",
    "scenario_skill_tags",
    "resume_anchor_hints",
    "failure_categories",
    "rubric_additions",
    "expected_signals",
    "anti_patterns",
    "good_answer_hints",
    "priority",
    "status",
}


@dataclass(frozen=True)
class QuestionSeedImportResult:
    imported_seeds: int = 0
    updated_seeds: int = 0
    unchanged_seeds: int = 0
    imported_variants: int = 0
    updated_variants: int = 0
    unchanged_variants: int = 0
    archived_seeds: int = 0
    archived_variants: int = 0


class QuestionSeedImportError(RuntimeError):
    """Raised when YAML validation fails before any DB writes."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("question seed import failed:\n" + "\n".join(errors))


@dataclass(frozen=True)
class ParsedQuestionSeed:
    values: dict[str, Any]


@dataclass(frozen=True)
class ParsedQuestionVariant:
    values: dict[str, Any]


def import_question_seed_dir(
    seed_dir: Path,
    *,
    session: Session,
    archive_missing: bool = False,
) -> QuestionSeedImportResult:
    """Validate and upsert all ``*.yaml`` files under ``seed_dir``.

    The import is deliberately two-phase: every file is parsed and validated
    before the first ORM row is added or mutated, so validation failures leave
    the DB untouched.
    """

    parsed_seeds, parsed_variants = parse_question_seed_dir(seed_dir)
    incoming_seed_ids = {seed.values["id"] for seed in parsed_seeds}
    incoming_variant_ids = {variant.values["id"] for variant in parsed_variants}

    imported_seeds = updated_seeds = unchanged_seeds = 0
    imported_variants = updated_variants = unchanged_variants = 0

    for parsed in parsed_seeds:
        row = session.get(QuestionSeed, parsed.values["id"])
        if row is None:
            session.add(QuestionSeed(**parsed.values))
            imported_seeds += 1
            continue
        if _row_matches(row, parsed.values):
            unchanged_seeds += 1
            continue
        _assign_values(row, parsed.values)
        updated_seeds += 1

    session.flush()

    for parsed in parsed_variants:
        row = session.get(QuestionVariant, parsed.values["id"])
        if row is None:
            session.add(QuestionVariant(**parsed.values))
            imported_variants += 1
            continue
        if _row_matches(row, parsed.values):
            unchanged_variants += 1
            continue
        _assign_values(row, parsed.values)
        updated_variants += 1

    archived_seeds = archived_variants = 0
    if archive_missing:
        archived_variants = _archive_missing_variants(session, incoming_variant_ids)
        archived_seeds = _archive_missing_seeds(session, incoming_seed_ids)

    if (
        imported_seeds
        or updated_seeds
        or imported_variants
        or updated_variants
        or archived_seeds
        or archived_variants
    ):
        session.flush()

    return QuestionSeedImportResult(
        imported_seeds=imported_seeds,
        updated_seeds=updated_seeds,
        unchanged_seeds=unchanged_seeds,
        imported_variants=imported_variants,
        updated_variants=updated_variants,
        unchanged_variants=unchanged_variants,
        archived_seeds=archived_seeds,
        archived_variants=archived_variants,
    )


def parse_question_seed_dir(
    seed_dir: Path,
) -> tuple[list[ParsedQuestionSeed], list[ParsedQuestionVariant]]:
    if not seed_dir.is_dir():
        return [], []

    errors: list[str] = []
    seeds: list[ParsedQuestionSeed] = []
    variants: list[ParsedQuestionVariant] = []
    seen_seed_ids: set[str] = set()
    seen_variant_ids: set[str] = set()

    for path in sorted(seed_dir.glob("*.yaml")):
        file_seeds, file_variants = _parse_question_seed_file(path, errors)
        for seed in file_seeds:
            seed_id = seed.values["id"]
            if seed_id in seen_seed_ids:
                errors.append(f"{path.name}: duplicate seed id: {seed_id}")
            seen_seed_ids.add(seed_id)
            seeds.append(seed)
        for variant in file_variants:
            variant_id = variant.values["id"]
            if variant_id in seen_variant_ids:
                errors.append(f"{path.name}: duplicate variant id: {variant_id}")
            seen_variant_ids.add(variant_id)
            variants.append(variant)

    seed_ids = {seed.values["id"] for seed in seeds}
    for variant in variants:
        if variant.values["seed_id"] not in seed_ids:
            errors.append(
                f"{variant.values['id']}: invalid parent seed reference: "
                f"{variant.values['seed_id']}"
            )

    if errors:
        raise QuestionSeedImportError(errors)

    return seeds, variants


def _parse_question_seed_file(
    path: Path,
    errors: list[str],
) -> tuple[list[ParsedQuestionSeed], list[ParsedQuestionVariant]]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as exc:
        errors.append(f"{path.name}: invalid yaml: {exc}")
        return [], []

    if not isinstance(raw, dict):
        errors.append(f"{path.name}: root must be a mapping")
        return [], []

    expected_from_file = path.stem
    if expected_from_file not in SUPPORTED_DIMENSIONS:
        errors.append(
            f"{path.name}: unsupported question seed file; expected one of "
            f"{sorted(f'{dimension}.yaml' for dimension in SUPPORTED_DIMENSIONS)}"
        )

    dimension = _string(raw.get("dimension"))
    if not dimension:
        errors.append(f"{path.name}: missing required field: dimension")
    elif dimension not in SUPPORTED_DIMENSIONS:
        errors.append(f"{path.name}: invalid dimension: {dimension}")

    if dimension and expected_from_file != dimension:
        errors.append(
            f"{path.name}: file/dimension mismatch: file={expected_from_file}, "
            f"dimension={dimension}"
        )

    raw_seeds = raw.get("seeds")
    if not isinstance(raw_seeds, list):
        errors.append(f"{path.name}: seeds must be a list")
        return [], []

    seeds: list[ParsedQuestionSeed] = []
    variants: list[ParsedQuestionVariant] = []
    for idx, raw_seed in enumerate(raw_seeds):
        seed, seed_variants = _parse_seed(path.name, idx, raw_seed, dimension, errors)
        if seed is not None:
            seeds.append(seed)
        variants.extend(seed_variants)
    return seeds, variants


def _parse_seed(
    file_name: str,
    idx: int,
    raw_seed: Any,
    file_dimension: str,
    errors: list[str],
) -> tuple[ParsedQuestionSeed | None, list[ParsedQuestionVariant]]:
    location = f"{file_name}: seeds[{idx}]"
    if not isinstance(raw_seed, dict):
        errors.append(f"{location}: seed must be a mapping")
        return None, []

    _required(location, raw_seed, SEED_REQUIRED, errors)
    seed_id = _string(raw_seed.get("id"))
    seed_dimension = _string(raw_seed.get("dimension"))
    if seed_dimension and seed_dimension != file_dimension:
        errors.append(
            f"{location}: seed dimension mismatch: seed={seed_dimension}, "
            f"file={file_dimension}"
        )
    _validate_enum(location, "dimension", seed_dimension, SUPPORTED_DIMENSIONS, errors)
    _validate_enum(location, "status", _string(raw_seed.get("status")), VALID_STATUSES, errors)
    _validate_enum(location, "scope", _string(raw_seed.get("scope")), VALID_SCOPES, errors)
    _validate_enum(
        location,
        "scope",
        _string(raw_seed.get("scope")),
        P0_VALID_SCOPES,
        errors,
        message="P0 only supports scope=global",
    )
    _validate_enum(location, "language", _string(raw_seed.get("language")), VALID_LANGUAGES, errors)
    _validate_list(location, "job_levels", raw_seed.get("job_levels"), errors)
    _validate_list(location, "skill_tags", raw_seed.get("skill_tags"), errors)
    _validate_list(location, "direction_tags", raw_seed.get("direction_tags"), errors)
    _validate_list(location, "role_tags", raw_seed.get("role_tags"), errors)
    direction_tags = _slug_list(
        raw_seed.get("direction_tags"),
        location=location,
        field="direction_tags",
        errors=errors,
        allowed=VALID_DIRECTION_TAGS,
        required=True,
    )
    role_tags = _slug_list(
        raw_seed.get("role_tags"),
        location=location,
        field="role_tags",
        errors=errors,
        allowed=VALID_ROLE_TAGS,
        required=True,
    )
    if not isinstance(raw_seed.get("rubric"), dict):
        errors.append(f"{location}: rubric must be a mapping")

    values = {
        "id": seed_id,
        "version": _int(raw_seed.get("version")),
        "title": _string(raw_seed.get("title")),
        "dimension": seed_dimension,
        "job_levels": _slug_list(raw_seed.get("job_levels")),
        "skill_tags": _slug_list(raw_seed.get("skill_tags")),
        "direction_tags": direction_tags,
        "role_tags": role_tags,
        "rubric": raw_seed.get("rubric") if isinstance(raw_seed.get("rubric"), dict) else {},
        "priority": _int(raw_seed.get("priority")),
        "status": _string(raw_seed.get("status")),
        "source": _string(raw_seed.get("source")),
        "scope": _string(raw_seed.get("scope")),
        "org_id": _optional_string(raw_seed.get("org_id")),
        "job_template_id": _optional_string(raw_seed.get("job_template_id")),
        "language": _string(raw_seed.get("language")),
    }

    raw_variants = raw_seed.get("variants")
    seed_variants: list[ParsedQuestionVariant] = []
    if isinstance(raw_variants, list):
        for variant_idx, raw_variant in enumerate(raw_variants):
            parsed = _parse_variant(
                file_name,
                idx,
                variant_idx,
                raw_variant,
                seed_id,
                role_tags,
                errors,
            )
            if parsed is not None:
                seed_variants.append(parsed)
    elif "variants" in raw_seed:
        errors.append(f"{location}: variants must be a list")

    return ParsedQuestionSeed(values), seed_variants


def _parse_variant(
    file_name: str,
    seed_idx: int,
    variant_idx: int,
    raw_variant: Any,
    seed_id: str,
    seed_role_tags: list[str],
    errors: list[str],
) -> ParsedQuestionVariant | None:
    location = f"{file_name}: seeds[{seed_idx}].variants[{variant_idx}]"
    if not isinstance(raw_variant, dict):
        errors.append(f"{location}: variant must be a mapping")
        return None

    _required(location, raw_variant, VARIANT_REQUIRED, errors)
    explicit_seed_id = _optional_string(raw_variant.get("seed_id"))
    if explicit_seed_id is not None and explicit_seed_id != seed_id:
        errors.append(
            f"{location}: invalid parent seed reference: {explicit_seed_id} "
            f"(expected {seed_id})"
        )
    _validate_enum(location, "intent", _string(raw_variant.get("intent")), VALID_INTENTS, errors)
    _validate_enum(
        location,
        "difficulty",
        _string(raw_variant.get("difficulty")),
        VALID_DIFFICULTIES,
        errors,
    )
    _validate_enum(location, "status", _string(raw_variant.get("status")), VALID_STATUSES, errors)
    for field in (
        "scenario_skill_tags",
        "resume_anchor_hints",
        "failure_categories",
        "rubric_additions",
        "expected_signals",
        "anti_patterns",
        "good_answer_hints",
    ):
        _validate_list(location, field, raw_variant.get(field), errors)
    if "role_tags" in raw_variant:
        _validate_list(location, "role_tags", raw_variant.get("role_tags"), errors)
        role_tags = _slug_list(
            raw_variant.get("role_tags"),
            location=location,
            field="role_tags",
            errors=errors,
            allowed=VALID_ROLE_TAGS,
            required=True,
        )
    else:
        role_tags = list(seed_role_tags)

    values = {
        "id": _string(raw_variant.get("id")),
        "seed_id": seed_id,
        "version": _int(raw_variant.get("version")),
        "intent": _string(raw_variant.get("intent")),
        "difficulty": _string(raw_variant.get("difficulty")),
        "scenario_brief": _string(raw_variant.get("scenario_brief")),
        "question_stem": _string(raw_variant.get("question_stem")),
        "prompt_template": _string(raw_variant.get("prompt_template")),
        "scenario_skill_tags": _slug_list(raw_variant.get("scenario_skill_tags")),
        "resume_anchor_hints": _slug_list(raw_variant.get("resume_anchor_hints")),
        "failure_categories": _slug_list(raw_variant.get("failure_categories")),
        "rubric_additions": _string_list(raw_variant.get("rubric_additions")),
        "expected_signals": _string_list(raw_variant.get("expected_signals")),
        "anti_patterns": _string_list(raw_variant.get("anti_patterns")),
        "good_answer_hints": _string_list(raw_variant.get("good_answer_hints")),
        "role_tags": role_tags,
        "priority": _int(raw_variant.get("priority")),
        "status": _string(raw_variant.get("status")),
    }
    return ParsedQuestionVariant(values)


def _required(
    location: str,
    raw: dict[str, Any],
    required: set[str],
    errors: list[str],
) -> None:
    for field in sorted(required):
        if field not in raw or raw.get(field) is None:
            errors.append(f"{location}: missing required field: {field}")


def _validate_enum(
    location: str,
    field: str,
    value: str,
    allowed: set[str],
    errors: list[str],
    *,
    message: str | None = None,
) -> None:
    if value and value not in allowed:
        prefix = message or f"invalid {field}"
        errors.append(f"{location}: {prefix}: {value} (expected one of {sorted(allowed)})")


def _validate_list(location: str, field: str, value: Any, errors: list[str]) -> None:
    if not isinstance(value, list):
        errors.append(f"{location}: {field} must be a list")


def _string(value: Any) -> str:
    return str(value or "").strip()


def _optional_string(value: Any) -> str | None:
    text = _string(value)
    return text or None


def _int(value: Any) -> int:
    try:
        return int(value)
    except Exception:
        return 0


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [text for item in value if (text := _string(item))]


def _slug_list(
    value: Any,
    *,
    location: str | None = None,
    field: str | None = None,
    errors: list[str] | None = None,
    allowed: set[str] | None = None,
    required: bool = False,
) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    duplicates: set[str] = set()
    for item in _string_list(value):
        slug = _slugify(item)
        if not slug:
            continue
        if slug in seen:
            duplicates.add(slug)
            continue
        seen.add(slug)
        out.append(slug)

    if errors is not None and location and field:
        if required and not out:
            errors.append(f"{location}: {field} must contain at least one tag")
        if duplicates:
            errors.append(f"{location}: duplicate {field}: {sorted(duplicates)}")
        if allowed is not None:
            invalid = sorted(tag for tag in out if tag not in allowed)
            if invalid:
                errors.append(
                    f"{location}: invalid {field}: {invalid} "
                    f"(expected one of {sorted(allowed)})"
                )
    return out


def _slugify(value: Any) -> str:
    text = _string(value).lower()
    text = re.sub(r"[^\w]+", "_", text, flags=re.UNICODE)
    text = re.sub(r"_+", "_", text)
    return text.strip("_")


def _row_matches(row: Any, values: dict[str, Any]) -> bool:
    return all(getattr(row, key) == value for key, value in values.items())


def _assign_values(row: Any, values: dict[str, Any]) -> None:
    for key, value in values.items():
        setattr(row, key, value)


def _archive_missing_seeds(session: Session, incoming_ids: set[str]) -> int:
    count = 0
    rows = session.scalars(
        select(QuestionSeed).where(QuestionSeed.status != "archived")
    ).all()
    for row in rows:
        if row.id in incoming_ids:
            continue
        row.status = "archived"
        count += 1
    return count


def _archive_missing_variants(session: Session, incoming_ids: set[str]) -> int:
    count = 0
    rows = session.scalars(
        select(QuestionVariant).where(QuestionVariant.status != "archived")
    ).all()
    for row in rows:
        if row.id in incoming_ids:
            continue
        row.status = "archived"
        count += 1
    return count
