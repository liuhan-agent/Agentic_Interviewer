from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services import interview_waiting_tips as waiting_tips_service
from app.services.interview_waiting_tips import (
    WaitingTipsCatalogError,
    list_waiting_tips_payload,
    parse_waiting_tips_catalog,
)


def test_parse_waiting_tips_catalog_normalizes_valid_payload() -> None:
    payload = parse_waiting_tips_catalog(
        {
            "version": "2026-05-11",
            "rotation_interval_ms": 10_000,
            "tips": [
                {
                    "id": " problem_solving_001 ",
                    "scope": " problem_solving ",
                    "text": " 排查类回答可以按：现象、假设、验证、修复、防复发来组织。 ",
                },
                {
                    "id": "default_001",
                    "scope": "default",
                    "text": "先给结论，再讲过程，回答会更清晰。",
                },
            ],
        }
    )

    assert payload == {
        "version": "2026-05-11",
        "rotation_interval_ms": 10_000,
        "tips": [
            {
                "id": "problem_solving_001",
                "scope": "problem_solving",
                "text": "排查类回答可以按：现象、假设、验证、修复、防复发来组织。",
            },
            {
                "id": "default_001",
                "scope": "default",
                "text": "先给结论，再讲过程，回答会更清晰。",
            },
        ],
    }


def test_parse_waiting_tips_catalog_rejects_duplicate_tip_ids() -> None:
    with pytest.raises(WaitingTipsCatalogError, match="duplicate tip id"):
        parse_waiting_tips_catalog(
            {
                "version": "2026-05-11",
                "rotation_interval_ms": 10_000,
                "tips": [
                    {"id": "default_001", "scope": "default", "text": "先讲结论。"},
                    {"id": "default_001", "scope": "default", "text": "再讲过程。"},
                ],
            }
        )


def test_parse_waiting_tips_catalog_rejects_empty_scope_or_text() -> None:
    with pytest.raises(WaitingTipsCatalogError, match="scope"):
        parse_waiting_tips_catalog(
            {
                "version": "2026-05-11",
                "rotation_interval_ms": 10_000,
                "tips": [{"id": "bad_001", "scope": " ", "text": "先讲结论。"}],
            }
        )

    with pytest.raises(WaitingTipsCatalogError, match="text"):
        parse_waiting_tips_catalog(
            {
                "version": "2026-05-11",
                "rotation_interval_ms": 10_000,
                "tips": [{"id": "bad_002", "scope": "default", "text": " "}],
            }
        )


def test_waiting_tips_cover_all_configured_interview_dimensions() -> None:
    directions = json.loads(
        Path("knowledge/interview_directions.json").read_text(encoding="utf-8")
    )
    dimension_ids = {
        dimension["id"]
        for direction in directions
        for dimension in direction.get("dimension_catalog", [])
    }
    scopes = {tip["scope"] for tip in list_waiting_tips_payload()["tips"]}

    assert dimension_ids - scopes == set()


def test_configured_dimension_scopes_have_multiple_waiting_tips() -> None:
    directions = json.loads(
        Path("knowledge/interview_directions.json").read_text(encoding="utf-8")
    )
    dimension_ids = {
        dimension["id"]
        for direction in directions
        for dimension in direction.get("dimension_catalog", [])
    }
    counts: dict[str, int] = {}
    for tip in list_waiting_tips_payload()["tips"]:
        counts[tip["scope"]] = counts.get(tip["scope"], 0) + 1

    assert {
        scope: counts.get(scope, 0)
        for scope in sorted(dimension_ids)
        if counts.get(scope, 0) < 2
    } == {}


def test_waiting_tips_have_enough_default_content_for_long_generation() -> None:
    counts: dict[str, int] = {}
    for tip in list_waiting_tips_payload()["tips"]:
        counts[tip["scope"]] = counts.get(tip["scope"], 0) + 1

    assert counts.get("default", 0) >= 10
    assert counts.get("self_intro", 0) >= 6
    assert counts.get("final", 0) >= 6


def test_list_waiting_tips_payload_reflects_catalog_file_updates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    catalog_path = tmp_path / "interview_waiting_tips.json"
    monkeypatch.setattr(waiting_tips_service, "_CATALOG_PATH", catalog_path)
    if hasattr(waiting_tips_service.list_waiting_tips_payload, "cache_clear"):
        waiting_tips_service.list_waiting_tips_payload.cache_clear()

    catalog_path.write_text(
        json.dumps(
            {
                "version": "v1",
                "rotation_interval_ms": 10_000,
                "tips": [{"id": "default_001", "scope": "default", "text": "先讲结论。"}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    assert waiting_tips_service.list_waiting_tips_payload()["version"] == "v1"

    catalog_path.write_text(
        json.dumps(
            {
                "version": "v2",
                "rotation_interval_ms": 10_000,
                "tips": [{"id": "default_002", "scope": "default", "text": "再讲过程。"}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    assert waiting_tips_service.list_waiting_tips_payload()["version"] == "v2"
