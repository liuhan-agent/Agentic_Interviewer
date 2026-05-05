"""Interview direction catalog and direction-scoped dimension templates."""
from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any


class InterviewDirectionNotFound(ValueError):  # noqa: N818
    """Raised when a requested interview direction is not configured."""


@dataclass(frozen=True)
class DimensionCatalogItem:
    id: str
    label: str
    description: str
    triggers: list[str]

    def to_api_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "description": self.description,
        }


@dataclass(frozen=True)
class InterviewDirection:
    industry: str
    direction: str
    label: str
    default_title: str
    default_level: str
    skills: list[str]
    template: str
    dimension_catalog: list[DimensionCatalogItem]

    @property
    def rubric_dimensions(self) -> list[str]:
        return [d.id for d in self.dimension_catalog]

    def to_api_dict(self) -> dict[str, Any]:
        return {
            "industry": self.industry,
            "direction": self.direction,
            "label": self.label,
            "default_title": self.default_title,
            "default_level": self.default_level,
            "skills": list(self.skills),
            "dimension_catalog": [
                item.to_api_dict() for item in self.dimension_catalog
            ],
            "rubric_dimensions": self.rubric_dimensions,
        }


_CATALOG_PATH = (
    Path(__file__).resolve().parents[2]
    / "knowledge"
    / "interview_directions.json"
)


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _parse_dimension(raw: Any) -> DimensionCatalogItem:
    if not isinstance(raw, dict):
        raise ValueError("dimension catalog entries must be objects")
    dim_id = str(raw.get("id") or "").strip()
    label = str(raw.get("label") or "").strip()
    description = str(raw.get("description") or "").strip()
    triggers = _string_list(raw.get("triggers"))
    if not all([dim_id, label, description, triggers]):
        raise ValueError(f"incomplete dimension catalog entry: {dim_id or '<missing>'}")
    return DimensionCatalogItem(
        id=dim_id,
        label=label,
        description=description,
        triggers=triggers,
    )


def _parse_direction(raw: Any) -> InterviewDirection:
    if not isinstance(raw, dict):
        raise ValueError("interview direction entries must be objects")
    industry = str(raw.get("industry") or "").strip()
    direction = str(raw.get("direction") or "").strip()
    label = str(raw.get("label") or "").strip()
    default_title = str(raw.get("default_title") or raw.get("title") or "").strip()
    default_level = str(raw.get("default_level") or "mid").strip()
    template = str(raw.get("template") or "").strip()
    skills = _string_list(raw.get("skills"))
    dims = [_parse_dimension(d) for d in raw.get("dimension_catalog") or []]
    if not all([industry, direction, label, default_title, template, skills, dims]):
        raise ValueError(f"incomplete interview direction entry: {direction or '<missing>'}")
    return InterviewDirection(
        industry=industry,
        direction=direction,
        label=label,
        default_title=default_title,
        default_level=default_level,
        skills=skills,
        template=template,
        dimension_catalog=dims,
    )


@lru_cache(maxsize=1)
def _load_directions() -> dict[str, InterviewDirection]:
    raw = json.loads(_CATALOG_PATH.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("interview_directions.json must contain a list")
    out: dict[str, InterviewDirection] = {}
    for item in raw:
        direction = _parse_direction(item)
        out[direction.direction] = direction
    return out


def list_interview_directions() -> list[InterviewDirection]:
    return list(_load_directions().values())


def get_interview_direction(direction: str) -> InterviewDirection:
    key = (direction or "").strip()
    item = _load_directions().get(key)
    if item is None:
        raise InterviewDirectionNotFound(key)
    return item


def all_dimension_options() -> list[dict[str, str]]:
    seen: set[str] = set()
    options: list[dict[str, str]] = []
    for direction in list_interview_directions():
        for item in direction.dimension_catalog:
            if item.id in seen:
                continue
            seen.add(item.id)
            options.append({"id": item.id, "label": item.label})
    return options


def dimension_label(dim: str) -> str:
    for option in all_dimension_options():
        if option["id"] == dim:
            return option["label"]
    return dim.replace("_", " ").title()
