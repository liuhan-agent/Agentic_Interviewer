from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.memory import strategy_store as ss
from app.models.base import Base
from app.models.strategy_memory import StrategyMemory


def _db_session_context():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)

    with Session() as sess:
        sess.add_all(
            [
                StrategyMemory(
                    id="seed:senior_system_design",
                    slug="senior_system_design",
                    name="Senior System Design",
                    description="Deep probes for senior system design.",
                    source="seed",
                    memory_key="seed:system_design:senior",
                    dimensions=["system_design"],
                    job_levels=["senior"],
                    body_markdown="Push for concrete trade-offs and failure modes.",
                    status="active",
                    promotion_stage="seed",
                    confidence=0.8,
                    support_count=20,
                ),
                StrategyMemory(
                    id="seed:disabled_strategy",
                    slug="disabled_strategy",
                    name="Disabled Strategy",
                    description="Should not be returned.",
                    source="seed",
                    dimensions=["system_design"],
                    job_levels=["senior"],
                    body_markdown="Disabled body.",
                    status="disabled",
                ),
                StrategyMemory(
                    id="seed:communication_hint",
                    slug="communication_hint",
                    name="Communication Hint",
                    description="Hints for communication answers.",
                    source="seed",
                    dimensions=["communication"],
                    job_levels=["senior"],
                    body_markdown="Ask for stakeholder context.",
                    status="active",
                ),
            ]
        )
        sess.commit()

    @contextmanager
    def get_session():
        with Session() as sess:
            yield sess

    return get_session


def test_list_strategies_reads_active_db_rows(monkeypatch) -> None:
    monkeypatch.setattr(
        ss,
        "get_settings",
        lambda: SimpleNamespace(strategy_memory_backend="db"),
    )
    monkeypatch.setattr(ss, "get_session", _db_session_context())

    entries = ss.list_strategies()

    assert [entry.name for entry in entries] == [
        "Communication Hint",
        "Senior System Design",
    ]
    assert {entry.id for entry in entries} == {
        "seed:communication_hint",
        "seed:senior_system_design",
    }
    assert all(entry.status == "active" for entry in entries)


def test_retrieve_strategies_uses_db_metadata_and_formats_prompt(monkeypatch) -> None:
    monkeypatch.setattr(
        ss,
        "get_settings",
        lambda: SimpleNamespace(strategy_memory_backend="db"),
    )
    monkeypatch.setattr(ss, "get_session", _db_session_context())

    entries = ss.retrieve_strategies(dimension="system_design", job_level="senior")
    block = ss.format_strategies_for_prompt(entries)

    assert [entry.id for entry in entries] == ["seed:senior_system_design"]
    assert entries[0].memory_key == "seed:system_design:senior"
    assert entries[0].source == "seed"
    assert entries[0].promotion_stage == "seed"
    assert "Senior System Design" in block
    assert "concrete trade-offs" in block


def test_file_backend_still_reads_markdown_strategies(
    tmp_path: Path,
    monkeypatch,
) -> None:
    strategy_dir = tmp_path / "strategy"
    strategy_dir.mkdir()
    (strategy_dir / "seed.md").write_text(
        "---\n"
        "name: seed\n"
        "description: seed strategy\n"
        "dimensions: [system_design]\n"
        "job_levels: [senior]\n"
        "---\n\n"
        "File-backed body.\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        ss,
        "get_settings",
        lambda: SimpleNamespace(strategy_memory_backend="file", knowledge_dir=tmp_path),
    )
    ss.clear_strategy_cache_for_tests()

    entries = ss.retrieve_strategies(dimension="system_design", job_level="senior")

    assert len(entries) == 1
    assert entries[0].name == "seed"
    assert entries[0].body == "File-backed body."
