"""Import file-backed strategy markdown seeds into the DB runtime store."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.models.strategy_memory import StrategyMemory

_FM_PATTERN = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_FM_FIELD = re.compile(r"^(\w+):\s*(.+)$", re.MULTILINE)
_FM_LIST = re.compile(r"\[([^\]]*)\]")


@dataclass(frozen=True)
class StrategySeedImportResult:
    imported: int = 0
    updated: int = 0
    unchanged: int = 0
    skipped: int = 0


@dataclass(frozen=True)
class ParsedStrategySeed:
    strategy_id: str
    slug: str
    name: str
    description: str
    memory_key: str | None
    dimensions: list[str]
    job_levels: list[str]
    body_markdown: str
    content_hash: str


def import_strategy_seed_dir(
    strategy_dir: Path,
    *,
    session: Session,
) -> StrategySeedImportResult:
    """Upsert all markdown strategy seeds under ``strategy_dir`` into DB."""

    result = StrategySeedImportResult()
    if not strategy_dir.is_dir():
        return result

    imported = updated = unchanged = skipped = 0
    for path in sorted(strategy_dir.glob("*.md")):
        if path.name == "MEMORY.md":
            skipped += 1
            continue
        seed = parse_strategy_seed(path)
        row = session.get(StrategyMemory, seed.strategy_id)
        if row is None:
            session.add(_new_strategy_memory(seed))
            imported += 1
            continue
        if row.content_hash == seed.content_hash:
            unchanged += 1
            continue
        _update_strategy_memory(row, seed)
        updated += 1

    if imported or updated:
        session.flush()

    return StrategySeedImportResult(
        imported=imported,
        updated=updated,
        unchanged=unchanged,
        skipped=skipped,
    )


def parse_strategy_seed(path: Path) -> ParsedStrategySeed:
    text = path.read_text(encoding="utf-8")
    frontmatter = _parse_frontmatter(text)
    body = _strip_frontmatter(text)
    slug = path.stem
    return ParsedStrategySeed(
        strategy_id=f"seed:{slug}",
        slug=slug,
        name=str(frontmatter.get("name") or slug),
        description=str(frontmatter.get("description") or ""),
        memory_key=_optional_str(frontmatter.get("memory_key")),
        dimensions=_string_list(frontmatter.get("dimensions")),
        job_levels=_string_list(frontmatter.get("job_levels")),
        body_markdown=body,
        content_hash=_content_hash(text),
    )


def _new_strategy_memory(seed: ParsedStrategySeed) -> StrategyMemory:
    return StrategyMemory(
        id=seed.strategy_id,
        slug=seed.slug,
        name=seed.name,
        description=seed.description,
        source="seed",
        memory_key=seed.memory_key,
        dimensions=seed.dimensions,
        job_levels=seed.job_levels,
        body_markdown=seed.body_markdown,
        status="active",
        promotion_stage="seed",
        version=1,
        content_hash=seed.content_hash,
    )


def _update_strategy_memory(row: StrategyMemory, seed: ParsedStrategySeed) -> None:
    row.slug = seed.slug
    row.name = seed.name
    row.description = seed.description
    row.source = "seed"
    row.memory_key = seed.memory_key
    row.dimensions = seed.dimensions
    row.job_levels = seed.job_levels
    row.body_markdown = seed.body_markdown
    row.status = "active"
    row.promotion_stage = "seed"
    row.version = int(row.version or 1) + 1
    row.content_hash = seed.content_hash


def _parse_frontmatter(text: str) -> dict[str, Any]:
    match = _FM_PATTERN.match(text)
    if not match:
        return {}
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


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _optional_str(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _content_hash(text: str) -> str:
    digest = hashlib.sha1(text.encode("utf-8"), usedforsecurity=False).hexdigest()
    return f"sha1:{digest}"
