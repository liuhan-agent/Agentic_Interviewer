"""Build locked core contracts from structured question seed metadata."""
from __future__ import annotations

from typing import Any, TypedDict

from app.engine.workflow.difficulty_adapter import difficulty_to_bar_level


class LockedCoreContract(TypedDict):
    """Seed-owned contract fields that an LLM must not redefine."""

    must_cover: list[str]
    minimum_bar: str
    locked_rubric_additions: list[str]
    bar_level: str
    seed_ref: dict[str, Any]


def build_locked_core_contract(
    *,
    contract_hints: dict[str, Any] | None,
    target_difficulty: str | None,
) -> LockedCoreContract | None:
    """Return the seed-owned core contract, if hints contain enough metadata."""

    question_seed = (contract_hints or {}).get("question_seed")
    if not isinstance(question_seed, dict):
        return None

    rubric = question_seed.get("rubric")
    if not isinstance(rubric, dict):
        return None

    must_cover = _string_list(rubric.get("must_cover"))
    if not must_cover:
        return None

    return {
        "must_cover": must_cover,
        "minimum_bar": str(rubric.get("minimum_bar") or "").strip(),
        "locked_rubric_additions": _string_list(
            question_seed.get("rubric_additions")
        ),
        "bar_level": _bar_level(target_difficulty),
        "seed_ref": _seed_ref(question_seed),
    }


def _bar_level(target_difficulty: str | None) -> str:
    value = str(target_difficulty or "").strip().lower()
    if value not in {"easy", "medium", "hard"}:
        value = "medium"
    return difficulty_to_bar_level(value)  # type: ignore[arg-type]


def _seed_ref(question_seed: dict[str, Any]) -> dict[str, Any]:
    ref: dict[str, Any] = {}
    for key in ("seed_id", "variant_id", "seed_version", "variant_version"):
        value = question_seed.get(key)
        if value not in (None, ""):
            ref[key] = value
    return ref


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    return [str(item).strip() for item in value if str(item or "").strip()]
