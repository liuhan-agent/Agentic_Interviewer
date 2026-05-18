"""Strict Markdown import for structured interviewer playbook cards."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.skill_playbook import SkillPlaybookCard
from app.services.question_seed_import import VALID_DIRECTION_TAGS, VALID_ROLE_TAGS

_FM_PATTERN = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.DOTALL)
_FM_FIELD = re.compile(r"^(\w+):\s*(.*)$", re.MULTILINE)
_FM_LIST = re.compile(r"^\[([^\]]*)\]$")
_VALID_STATUSES = {"active", "draft", "archived"}
_REQUIRED_FIELDS = {"id", "name", "description", "status", "priority"}
_LIST_FIELDS = {
    "direction_tags",
    "role_tags",
    "dimensions",
    "job_levels",
    "probe_intents",
    "failure_categories",
}


@dataclass(frozen=True)
class SkillPlaybookImportResult:
    imported: int = 0
    updated: int = 0
    unchanged: int = 0
    archived: int = 0
    skipped: int = 0


class SkillPlaybookImportError(RuntimeError):
    """Raised when Markdown validation fails before any DB writes."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("skill playbook import failed:\n" + "\n".join(errors))


@dataclass(frozen=True)
class ParsedSkillPlaybookCard:
    values: dict[str, Any]


def import_skill_playbook_dir(
    skill_dir: Path,
    *,
    session: Session,
    archive_missing: bool = False,
) -> SkillPlaybookImportResult:
    """Validate and upsert all skill Markdown cards under ``skill_dir``."""

    parsed_cards, skipped = parse_skill_playbook_dir(skill_dir)
    incoming_ids = {card.values["id"] for card in parsed_cards}

    imported = updated = unchanged = 0
    for parsed in parsed_cards:
        row = session.get(SkillPlaybookCard, parsed.values["id"])
        if row is None:
            session.add(SkillPlaybookCard(**parsed.values))
            imported += 1
            continue
        if _row_matches(row, parsed.values, ignore={"version"}):
            unchanged += 1
            continue
        values = dict(parsed.values)
        values["version"] = int(row.version or 1) + 1
        _assign_values(row, values)
        updated += 1

    archived = 0
    if archive_missing:
        archived = _archive_missing_cards(session, incoming_ids)

    if imported or updated or archived:
        session.flush()

    return SkillPlaybookImportResult(
        imported=imported,
        updated=updated,
        unchanged=unchanged,
        archived=archived,
        skipped=skipped,
    )


def parse_skill_playbook_dir(
    skill_dir: Path,
) -> tuple[list[ParsedSkillPlaybookCard], int]:
    if not skill_dir.is_dir():
        return [], 0

    errors: list[str] = []
    cards: list[ParsedSkillPlaybookCard] = []
    seen_ids: set[str] = set()
    skipped = 0

    for path in sorted(skill_dir.glob("*.md")):
        if path.name == "SKILL.md":
            skipped += 1
            continue
        parsed = _parse_skill_file(path, errors)
        if parsed is None:
            continue
        card_id = parsed.values["id"]
        if card_id in seen_ids:
            errors.append(f"{path.name}: duplicate skill card id: {card_id}")
        seen_ids.add(card_id)
        cards.append(parsed)

    if errors:
        raise SkillPlaybookImportError(errors)

    return cards, skipped


def _parse_skill_file(
    path: Path,
    errors: list[str],
) -> ParsedSkillPlaybookCard | None:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        errors.append(f"{path.name}: failed to read file: {exc}")
        return None

    frontmatter = _parse_frontmatter(path.name, text, errors)
    if frontmatter is None:
        return None

    body = _strip_frontmatter(text)
    if not body:
        errors.append(f"{path.name}: body_markdown must not be empty")

    _validate_required(path.name, frontmatter, errors)
    card_id = _string(frontmatter.get("id"))
    if card_id:
        if card_id != _slugify(card_id):
            errors.append(f"{path.name}: id must be a stable slug: {card_id}")
        if len(card_id) > 160:
            errors.append(f"{path.name}: id exceeds 160 characters: {card_id}")

    status = _slugify(frontmatter.get("status")) or "active"
    if status and status not in _VALID_STATUSES:
        errors.append(
            f"{path.name}: invalid status: {status} "
            f"(expected one of {sorted(_VALID_STATUSES)})"
        )

    priority = _parse_priority(path.name, frontmatter.get("priority"), errors)

    for field in _LIST_FIELDS:
        if field in frontmatter and not isinstance(frontmatter[field], list):
            errors.append(f"{path.name}: {field} must be a list")

    values = {
        "id": card_id,
        "name": _string(frontmatter.get("name")),
        "description": _string(frontmatter.get("description")),
        "body_markdown": body,
        "status": status,
        "priority": priority,
        "direction_tags": _slug_list(
            path.name,
            "direction_tags",
            frontmatter.get("direction_tags"),
            errors,
            allowed=VALID_DIRECTION_TAGS,
        ),
        "role_tags": _slug_list(
            path.name,
            "role_tags",
            frontmatter.get("role_tags"),
            errors,
            allowed=VALID_ROLE_TAGS,
        ),
        "dimensions": _slug_list(
            path.name,
            "dimensions",
            frontmatter.get("dimensions"),
            errors,
        ),
        "job_levels": _slug_list(
            path.name,
            "job_levels",
            frontmatter.get("job_levels"),
            errors,
        ),
        "probe_intents": _slug_list(
            path.name,
            "probe_intents",
            frontmatter.get("probe_intents"),
            errors,
        ),
        "failure_categories": _slug_list(
            path.name,
            "failure_categories",
            frontmatter.get("failure_categories"),
            errors,
        ),
        "source": "manual_markdown",
        "version": 1,
        "content_hash": _content_hash(text),
    }
    return ParsedSkillPlaybookCard(values)


def _parse_frontmatter(
    file_name: str,
    text: str,
    errors: list[str],
) -> dict[str, Any] | None:
    match = _FM_PATTERN.match(text)
    if not match:
        errors.append(f"{file_name}: missing frontmatter")
        return None

    block = match.group(1)
    result: dict[str, Any] = {}
    for field in _FM_FIELD.finditer(block):
        key, raw = field.group(1), field.group(2).strip()
        list_match = _FM_LIST.match(raw)
        if list_match:
            result[key] = [
                item.strip().strip("'\"")
                for item in list_match.group(1).split(",")
                if item.strip()
            ]
        else:
            result[key] = raw.strip("'\"")
    return result


def _strip_frontmatter(text: str) -> str:
    return _FM_PATTERN.sub("", text).strip()


def _validate_required(
    file_name: str,
    frontmatter: dict[str, Any],
    errors: list[str],
) -> None:
    for field in sorted(_REQUIRED_FIELDS):
        value = frontmatter.get(field)
        if field not in frontmatter or value is None or _string(value) == "":
            errors.append(f"{file_name}: missing required field: {field}")


def _parse_priority(file_name: str, value: Any, errors: list[str]) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        errors.append(f"{file_name}: priority must be an integer: {_string(value)}")
        return 0


def _slug_list(
    file_name: str,
    field: str,
    value: Any,
    errors: list[str],
    *,
    allowed: set[str] | None = None,
) -> list[str]:
    if value is None:
        return []
    raw = value if isinstance(value, list) else [value]
    out: list[str] = []
    seen: set[str] = set()
    duplicates: set[str] = set()
    for item in raw:
        slug = _slugify(item)
        if not slug:
            continue
        if slug in seen:
            duplicates.add(slug)
            continue
        seen.add(slug)
        out.append(slug)
    if duplicates:
        errors.append(f"{file_name}: duplicate {field}: {sorted(duplicates)}")
    if allowed is not None:
        invalid = sorted(tag for tag in out if tag not in allowed)
        if invalid:
            errors.append(
                f"{file_name}: invalid {field}: {invalid} "
                f"(expected one of {sorted(allowed)})"
            )
    return out


def _slugify(value: Any) -> str:
    text = _string(value).lower()
    text = re.sub(r"[^\w]+", "_", text, flags=re.UNICODE)
    text = re.sub(r"_+", "_", text)
    return text.strip("_")


def _string(value: Any) -> str:
    return str(value or "").strip()


def _content_hash(text: str) -> str:
    digest = hashlib.sha1(text.encode("utf-8"), usedforsecurity=False).hexdigest()
    return f"sha1:{digest}"


def _row_matches(
    row: SkillPlaybookCard,
    values: dict[str, Any],
    *,
    ignore: set[str],
) -> bool:
    return all(
        getattr(row, key) == value
        for key, value in values.items()
        if key not in ignore
    )


def _assign_values(row: SkillPlaybookCard, values: dict[str, Any]) -> None:
    for key, value in values.items():
        setattr(row, key, value)


def _archive_missing_cards(session: Session, incoming_ids: set[str]) -> int:
    count = 0
    rows = session.scalars(
        select(SkillPlaybookCard).where(
            SkillPlaybookCard.source == "manual_markdown",
            SkillPlaybookCard.status != "archived",
        )
    ).all()
    for row in rows:
        if row.id in incoming_ids:
            continue
        row.status = "archived"
        count += 1
    return count
