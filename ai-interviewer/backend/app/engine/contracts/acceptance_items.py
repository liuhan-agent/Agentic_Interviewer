"""Structured acceptance-check items and legacy string projections."""
from __future__ import annotations

import copy
import hashlib
import re
from typing import Any, Literal, TypedDict


AcceptanceCheckSource = Literal[
    "adaptive_context",
    "reviewed",
    "compiled_fallback",
    "rewrite_fallback",
    "evaluator_extra",
]
AcceptanceCheckSeverity = Literal["core", "supporting"]


class AcceptanceCheckItem(TypedDict, total=False):
    check_id: str
    text: str
    source: str
    severity: str
    source_text: str
    seed_ref: dict[str, Any]
    origin: str
    metadata: dict[str, Any]


class AcceptanceCheckResultItem(AcceptanceCheckItem, total=False):
    verdict: str
    evidence: list[Any]
    evidence_spans: list[Any]
    result_present: bool


_SOURCE_PRIORITY = {
    "evaluator_extra": 0,
    "adaptive_context": 10,
    "rewrite_fallback": 20,
    "compiled_fallback": 30,
    "reviewed": 40,
}


def acceptance_check_items_from_legacy(
    acceptance_checks: Any,
    *,
    source: str = "adaptive_context",
    severity: str = "supporting",
    origin: str = "negotiated_contract",
) -> list[AcceptanceCheckItem]:
    """Convert legacy string checks into structured items."""

    items: list[AcceptanceCheckItem] = []
    for text in _string_list(acceptance_checks):
        items.append(
            {
                "check_id": _stable_check_id(
                    source=source,
                    text=text,
                    source_text="",
                    origin=origin,
                ),
                "text": text,
                "source": source,
                "severity": _severity_or_default(severity),
                "source_text": "",
                "seed_ref": {},
                "origin": origin,
                "metadata": {},
            }
        )
    return items


def acceptance_check_items_from_structured(
    checks: Any,
    *,
    source: str,
    origin: str,
    seed_ref: dict[str, Any] | None = None,
) -> list[AcceptanceCheckItem]:
    """Convert reviewed/compiled check dictionaries into structured items."""

    if not isinstance(checks, list):
        return []
    items: list[AcceptanceCheckItem] = []
    for raw in checks:
        if not isinstance(raw, dict):
            continue
        text = str(raw.get("acceptance_check") or raw.get("text") or "").strip()
        if not text:
            continue
        raw_source_text = str(raw.get("source_text") or "").strip()
        raw_seed_ref = raw.get("seed_ref") if isinstance(raw.get("seed_ref"), dict) else None
        effective_seed_ref = dict(seed_ref or raw_seed_ref or {})
        check_id = str(raw.get("check_id") or "").strip() or _stable_check_id(
            source=source,
            text=text,
            source_text=raw_source_text,
            origin=origin,
            seed_ref=effective_seed_ref,
        )
        criterion_source = str(raw.get("source") or "").strip()
        metadata = {
            key: copy.deepcopy(value)
            for key, value in raw.items()
            if key
            not in {
                "acceptance_check",
                "text",
                "check_id",
                "source_text",
                "severity",
                "seed_ref",
            }
        }
        if criterion_source:
            metadata.setdefault("criterion_source", criterion_source)
        items.append(
            {
                "check_id": check_id,
                "text": text,
                "source": source,
                "severity": _severity_or_default(raw.get("severity")),
                "source_text": raw_source_text,
                "seed_ref": effective_seed_ref,
                "origin": origin,
                "metadata": metadata,
            }
        )
    return items


def ensure_contract_acceptance_items(
    contract: dict[str, Any] | None,
    *,
    source: str = "adaptive_context",
    severity: str = "supporting",
    origin: str = "negotiated_contract",
) -> dict[str, Any]:
    """Return a contract carrying both items and string projection."""

    updated = dict(contract or {})
    raw_items = updated.get("acceptance_check_items")
    if isinstance(raw_items, list) and raw_items:
        items = _normalise_items(raw_items)
    else:
        items = acceptance_check_items_from_legacy(
            updated.get("acceptance_checks") or [],
            source=source,
            severity=severity,
            origin=origin,
        )
    items = merge_acceptance_check_items([], items)
    updated["acceptance_check_items"] = items
    updated["acceptance_checks"] = acceptance_check_texts(items)
    return updated


def append_acceptance_check_items(
    contract: dict[str, Any] | None,
    incoming_items: list[dict[str, Any]] | None,
) -> tuple[dict[str, Any], list[str]]:
    """Append structured items and refresh the legacy string projection."""

    updated = ensure_contract_acceptance_items(contract or {})
    before_texts = acceptance_check_texts(updated.get("acceptance_check_items"))
    merged = merge_acceptance_check_items(
        list(updated.get("acceptance_check_items") or []),
        list(incoming_items or []),
    )
    after_texts = acceptance_check_texts(merged)
    appended = [text for text in after_texts if text not in before_texts]
    updated["acceptance_check_items"] = merged
    updated["acceptance_checks"] = after_texts
    return updated, appended


def merge_acceptance_check_items(
    existing_items: list[dict[str, Any]] | None,
    incoming_items: list[dict[str, Any]] | None,
) -> list[AcceptanceCheckItem]:
    """Merge items by stable identity without fuzzy semantic matching."""

    merged: list[AcceptanceCheckItem] = []
    check_id_index: dict[str, int] = {}
    source_text_index: dict[tuple[str, str], int] = {}
    text_index: dict[str, int] = {}

    def remember(item: AcceptanceCheckItem, idx: int) -> None:
        check_id = str(item.get("check_id") or "").strip()
        if check_id:
            check_id_index[check_id] = idx
        source_text = _normalise_text(item.get("source_text") or "")
        source = str(item.get("source") or "").strip()
        if source and source_text:
            source_text_index[(source, source_text)] = idx
        text_norm = _normalise_text(item.get("text") or "")
        if text_norm:
            text_index[text_norm] = idx

    def duplicate_index(item: AcceptanceCheckItem) -> int | None:
        check_id = str(item.get("check_id") or "").strip()
        if check_id and check_id in check_id_index:
            return check_id_index[check_id]
        source_text = _normalise_text(item.get("source_text") or "")
        source = str(item.get("source") or "").strip()
        if source and source_text and (source, source_text) in source_text_index:
            return source_text_index[(source, source_text)]
        text_norm = _normalise_text(item.get("text") or "")
        if text_norm and text_norm in text_index:
            return text_index[text_norm]
        return None

    for raw in list(existing_items or []) + list(incoming_items or []):
        item = _normalise_item(raw)
        if item is None:
            continue
        idx = duplicate_index(item)
        if idx is None:
            merged.append(item)
            remember(item, len(merged) - 1)
            continue
        if _source_priority(item) > _source_priority(merged[idx]):
            merged[idx] = item
            remember(item, idx)
    return merged


def acceptance_check_texts(items: Any) -> list[str]:
    if not isinstance(items, list):
        return []
    texts: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        if text:
            texts.append(text)
    return texts


def acceptance_check_item_projection_diagnostics(
    contract: dict[str, Any] | None,
) -> dict[str, Any]:
    """Summarise item/projection consistency for trace diagnostics."""

    payload = contract or {}
    items = _normalise_items(payload.get("acceptance_check_items"))
    projection = acceptance_check_texts(items)
    checks = _string_list(payload.get("acceptance_checks"))
    source_counts: dict[str, int] = {}
    severity_counts: dict[str, int] = {}
    for item in items:
        source = str(item.get("source") or "unknown")
        severity = str(item.get("severity") or "supporting")
        source_counts[source] = source_counts.get(source, 0) + 1
        severity_counts[severity] = severity_counts.get(severity, 0) + 1
    warnings: list[str] = []
    if items and projection != checks:
        warnings.append("acceptance_check_projection_mismatch")
    if checks and not items:
        warnings.append("acceptance_check_items_missing")
    return {
        "acceptance_check_items_present": bool(items),
        "acceptance_check_item_count": len(items),
        "acceptance_check_item_source_counts": source_counts,
        "acceptance_check_item_severity_counts": severity_counts,
        "acceptance_check_projection_match": projection == checks,
        "acceptance_check_projection_warnings": warnings,
    }


def contract_for_legacy_scoring(contract: dict[str, Any] | None) -> dict[str, Any]:
    """Project a structured runtime contract back to the legacy scoring shape."""

    projected = ensure_contract_acceptance_items(contract or {})
    projected.pop("acceptance_check_items", None)
    return projected


def contract_for_source_aware_scoring(
    contract: dict[str, Any] | None,
) -> dict[str, Any]:
    """Project runtime contract into a lightweight LLM-facing shape.

    The scoring prompt still receives ``acceptance_checks: list[str]`` so
    legacy output keys remain text-based. When runtime items already
    exist, add a small ``acceptance_check_items_for_prompt`` sidecar with
    only stable source metadata the LLM should consider.
    """

    payload = contract or {}
    raw_items = payload.get("acceptance_check_items")
    if not isinstance(raw_items, list) or not raw_items:
        return contract_for_legacy_scoring(payload)

    projected = ensure_contract_acceptance_items(payload)
    items = _prompt_items(projected.get("acceptance_check_items"))
    projected.pop("acceptance_check_items", None)
    if items:
        projected["acceptance_check_items_for_prompt"] = items
    else:
        projected.pop("acceptance_check_items_for_prompt", None)
    return projected


def join_acceptance_check_results(
    contract_or_items: dict[str, Any] | list[dict[str, Any]] | None,
    acceptance_check_results: Any,
) -> list[AcceptanceCheckResultItem]:
    """Attach evaluator results to structured check items."""

    if isinstance(contract_or_items, list):
        items = merge_acceptance_check_items([], contract_or_items)
    else:
        contract = ensure_contract_acceptance_items(contract_or_items or {})
        items = list(contract.get("acceptance_check_items") or [])

    results = acceptance_check_results if isinstance(acceptance_check_results, dict) else {}
    result_by_norm: dict[str, tuple[str, Any]] = {}
    for key, value in results.items():
        if not isinstance(key, str):
            continue
        result_by_norm.setdefault(_normalise_text(key), (key, value))

    matched_keys: set[str] = set()
    joined: list[AcceptanceCheckResultItem] = []
    for item in items:
        text = str(item.get("text") or "").strip()
        raw_result = None
        result_present = False
        if text in results:
            raw_result = results[text]
            matched_keys.add(text)
            result_present = True
        else:
            match = result_by_norm.get(_normalise_text(text))
            if match is not None:
                key, raw_result = match
                matched_keys.add(key)
                result_present = True
        joined.append(
            _result_item_from_value(
                item,
                raw_result,
                result_present=result_present,
            )
        )

    for key, raw_result in results.items():
        if not isinstance(key, str) or key in matched_keys:
            continue
        extra = acceptance_check_items_from_legacy(
            [key],
            source="evaluator_extra",
            severity="supporting",
            origin="evaluator_output",
        )[0]
        joined.append(
            _result_item_from_value(
                extra,
                raw_result,
                result_present=True,
            )
        )
    return joined


def _result_item_from_value(
    item: dict[str, Any],
    raw_result: Any,
    *,
    result_present: bool,
) -> AcceptanceCheckResultItem:
    result: AcceptanceCheckResultItem = copy.deepcopy(item)  # type: ignore[assignment]
    verdict = ""
    evidence: list[Any] = []
    evidence_spans: list[Any] = []
    if isinstance(raw_result, dict):
        verdict = str(raw_result.get("verdict") or "").strip().lower()
        raw_evidence = raw_result.get("evidence")
        if isinstance(raw_evidence, list):
            evidence = copy.deepcopy(raw_evidence)
        raw_spans = raw_result.get("evidence_spans")
        if isinstance(raw_spans, list):
            evidence_spans = copy.deepcopy(raw_spans)
    elif raw_result is not None:
        verdict = str(raw_result).strip().lower()
    result["verdict"] = verdict if verdict in {"yes", "partial", "no"} else ""
    result["evidence"] = evidence
    result["evidence_spans"] = evidence_spans
    result["result_present"] = bool(result_present)
    return result


def _normalise_items(value: Any) -> list[AcceptanceCheckItem]:
    if not isinstance(value, list):
        return []
    return [
        item
        for item in (_normalise_item(raw) for raw in value)
        if item is not None
    ]


def _prompt_items(value: Any) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for item in _normalise_items(value):
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        items.append(
            {
                "check_id": str(item.get("check_id") or "").strip(),
                "text": text,
                "source": str(item.get("source") or "adaptive_context").strip()
                or "adaptive_context",
                "severity": _severity_or_default(item.get("severity")),
            }
        )
    return items


def _normalise_item(raw: Any) -> AcceptanceCheckItem | None:
    if not isinstance(raw, dict):
        return None
    text = str(raw.get("text") or raw.get("acceptance_check") or "").strip()
    if not text:
        return None
    source = str(raw.get("source") or "adaptive_context").strip() or "adaptive_context"
    severity = _severity_or_default(raw.get("severity"))
    source_text = str(raw.get("source_text") or "").strip()
    origin = str(raw.get("origin") or source).strip() or source
    seed_ref = raw.get("seed_ref") if isinstance(raw.get("seed_ref"), dict) else {}
    metadata = raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {}
    check_id = str(raw.get("check_id") or "").strip() or _stable_check_id(
        source=source,
        text=text,
        source_text=source_text,
        origin=origin,
        seed_ref=seed_ref,
    )
    return {
        "check_id": check_id,
        "text": text,
        "source": source,
        "severity": severity,
        "source_text": source_text,
        "seed_ref": copy.deepcopy(seed_ref),
        "origin": origin,
        "metadata": copy.deepcopy(metadata),
    }


def _stable_check_id(
    *,
    source: str,
    text: str,
    source_text: str,
    origin: str,
    seed_ref: dict[str, Any] | None = None,
) -> str:
    seed = seed_ref or {}
    digest = hashlib.sha1(
        "|".join(
            [
                str(source or ""),
                str(origin or ""),
                str(seed.get("seed_id") or ""),
                str(seed.get("variant_id") or ""),
                _normalise_text(source_text),
                _normalise_text(text),
            ]
        ).encode("utf-8")
    ).hexdigest()[:12]
    return f"{source}:{digest}"


def _severity_or_default(value: Any) -> str:
    text = str(value or "").strip().lower()
    return text if text in {"core", "supporting"} else "supporting"


def _source_priority(item: dict[str, Any]) -> int:
    return _SOURCE_PRIORITY.get(str(item.get("source") or ""), 10)


def _string_list(value: Any) -> list[str]:
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item or "").strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _normalise_text(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "").strip().lower())
