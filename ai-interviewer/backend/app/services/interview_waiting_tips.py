from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any


class WaitingTipsCatalogError(ValueError):
    """Raised when the waiting tips catalog is malformed."""


_CATALOG_PATH = (
    Path(__file__).resolve().parents[2]
    / "knowledge"
    / "interview_waiting_tips.json"
)


def parse_waiting_tips_catalog(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise WaitingTipsCatalogError("waiting tips catalog must be an object")

    version = str(raw.get("version") or "").strip()
    if not version:
        raise WaitingTipsCatalogError("waiting tips catalog version is required")

    rotation_interval_ms = raw.get("rotation_interval_ms")
    if not isinstance(rotation_interval_ms, int) or rotation_interval_ms <= 0:
        raise WaitingTipsCatalogError("rotation_interval_ms must be a positive integer")

    raw_tips = raw.get("tips")
    if not isinstance(raw_tips, list) or not raw_tips:
        raise WaitingTipsCatalogError("waiting tips catalog must contain tips")

    seen_ids: set[str] = set()
    tips: list[dict[str, str]] = []
    for index, item in enumerate(raw_tips):
        if not isinstance(item, dict):
            raise WaitingTipsCatalogError(f"tip at index {index} must be an object")
        tip_id = str(item.get("id") or "").strip()
        scope = str(item.get("scope") or "").strip()
        text = str(item.get("text") or "").strip()
        if not tip_id:
            raise WaitingTipsCatalogError(f"tip at index {index} id is required")
        if tip_id in seen_ids:
            raise WaitingTipsCatalogError(f"duplicate tip id: {tip_id}")
        if not scope:
            raise WaitingTipsCatalogError(f"tip {tip_id} scope is required")
        if not text:
            raise WaitingTipsCatalogError(f"tip {tip_id} text is required")
        seen_ids.add(tip_id)
        tips.append({"id": tip_id, "scope": scope, "text": text})

    return {
        "version": version,
        "rotation_interval_ms": rotation_interval_ms,
        "tips": tips,
    }


@lru_cache(maxsize=1)
def list_waiting_tips_payload() -> dict[str, Any]:
    with _CATALOG_PATH.open("r", encoding="utf-8") as f:
        raw = json.load(f)
    return parse_waiting_tips_catalog(raw)
