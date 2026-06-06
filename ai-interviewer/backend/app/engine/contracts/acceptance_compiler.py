"""Compile seed-owned contract items into deterministic acceptance checks."""
from __future__ import annotations

import hashlib
import re
from typing import Any, Literal, TypedDict


class CompiledAcceptanceCheck(TypedDict):
    """Structured metadata for a deterministic acceptance check."""

    check_id: str
    source: Literal["must_cover", "rubric_addition"]
    source_text: str
    acceptance_check: str
    severity: Literal["core", "supporting"]
    seed_ref: dict[str, Any]


def compile_locked_acceptance_checks(
    locked_core_contract: dict[str, Any] | None,
) -> list[CompiledAcceptanceCheck]:
    """Compile locked core items into evaluator-ready string checks."""

    if not locked_core_contract:
        return []

    seed_ref = dict(locked_core_contract.get("seed_ref") or {})
    compiled: list[CompiledAcceptanceCheck] = []
    seen: set[tuple[str, str]] = set()

    for source, severity, items in (
        ("must_cover", "core", locked_core_contract.get("must_cover")),
        (
            "rubric_addition",
            "supporting",
            locked_core_contract.get("locked_rubric_additions"),
        ),
    ):
        for source_text in _string_list(items):
            dedupe_key = (source, _normalise_source_text(source_text))
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            compiled.append(
                {
                    "check_id": _check_id(
                        source=source,
                        source_text=source_text,
                        seed_ref=seed_ref,
                    ),
                    "source": source,  # type: ignore[typeddict-item]
                    "source_text": source_text,
                    "acceptance_check": _render_acceptance_check(
                        source=source,
                        source_text=source_text,
                    ),
                    "severity": severity,  # type: ignore[typeddict-item]
                    "seed_ref": dict(seed_ref),
                }
            )
    return compiled


def _render_acceptance_check(*, source: str, source_text: str) -> str:
    if _contains_cjk(source_text):
        return f"回答需要{source_text}。"
    if source == "must_cover":
        return f"Answer explicitly covers {source_text}."
    return f"Answer provides evidence for {source_text}."


def _check_id(
    *,
    source: str,
    source_text: str,
    seed_ref: dict[str, Any],
) -> str:
    seed_id = str(seed_ref.get("seed_id") or "")
    variant_id = str(seed_ref.get("variant_id") or "")
    digest = hashlib.sha1(
        "|".join(
            [
                seed_id,
                variant_id,
                source,
                _normalise_source_text(source_text),
            ]
        ).encode("utf-8")
    ).hexdigest()[:12]
    return f"seed_check:{digest}"


def _contains_cjk(value: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", value))


def _normalise_source_text(value: str) -> str:
    return re.sub(r"\s+", "", str(value or "").strip().lower())


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    return [str(item).strip() for item in value if str(item or "").strip()]
