from __future__ import annotations

from pathlib import Path

from app.services.resume_chunker import (
    ResumeChunkerMode,
    chunk_resume,
    detect_resume_structure,
    extract_tech_keywords,
    infer_dimensions_hint,
    normalize_resume_text,
)

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "resumes"


def _read_fixture(name: str) -> str:
    return (FIXTURE_DIR / name).read_text(encoding="utf-8")


def test_chunker_classifies_high_structure_resume() -> None:
    text = _read_fixture("fixture_high_structure_tech.md")
    mode, chunks = chunk_resume(text, parsed=None)

    assert mode is ResumeChunkerMode.A
    tiers = [chunk.tier for chunk in chunks]
    assert tiers.count("highlight") >= 8
    assert tiers.count("skill") >= 5
    assert all(chunk.text.strip() for chunk in chunks)
    assert any(chunk.project_name == "Smart Learning Coupon Guard" for chunk in chunks)


def test_chunker_classifies_medium_structure_resume() -> None:
    text = _read_fixture("fixture_medium_structure_sales.md")
    mode, chunks = chunk_resume(text, parsed=None)

    assert mode is ResumeChunkerMode.B
    assert len(chunks) >= 2
    assert {chunk.tier for chunk in chunks} == {"section"}


def test_chunker_classifies_low_structure_resume() -> None:
    text = _read_fixture("fixture_low_structure_freeform.md")
    mode, chunks = chunk_resume(text, parsed=None)

    assert mode is ResumeChunkerMode.C
    assert chunks
    assert {chunk.tier for chunk in chunks} == {"window"}


def test_chunker_falls_back_to_full_on_minimal_resume() -> None:
    text = _read_fixture("fixture_minimal_intern.md")
    mode, chunks = chunk_resume(text, parsed=None)

    assert mode is ResumeChunkerMode.D
    assert len(chunks) == 1
    assert chunks[0].tier == "full"


def test_chunker_extracts_tech_keywords_from_highlight() -> None:
    text = "Redis Hash cache + Lua script protects RabbitMQ async writes"
    keywords = extract_tech_keywords(text)

    assert {"Redis", "Lua", "RabbitMQ"}.issubset(set(keywords))


def test_chunker_infers_dimensions_from_keywords() -> None:
    dimensions = infer_dimensions_hint(
        "Redis Lua queue consistency",
        ["Redis", "Lua", "RabbitMQ"],
    )

    assert "system_design" in dimensions
    assert "technical_depth" in dimensions


def test_chunker_normalizes_spacing_and_tech_punctuation() -> None:
    raw = "Java\u00a0\uff0c\u2009Spring Boot\u200b, Redis"

    assert normalize_resume_text(raw) == "Java, Spring Boot, Redis"


def test_chunker_never_raises_on_garbage_input() -> None:
    mode, chunks = chunk_resume("", parsed=None)

    assert mode is ResumeChunkerMode.D
    assert chunks == [] or chunks[0].text == ""


def test_detect_resume_structure_uses_parsed_projects_as_structure_signal() -> None:
    text = "Short project notes " * 40

    mode = detect_resume_structure(
        text,
        parsed={
            "projects": [
                {"name": "A", "highlights": ["Redis"]},
                {"name": "B", "highlights": ["Kafka"]},
            ],
            "focus_areas": [{"label": "cache"}],
        },
    )

    assert mode is ResumeChunkerMode.A
