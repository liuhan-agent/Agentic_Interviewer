from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
from app.models.strategy_memory import StrategyMemory
from app.services.strategy_memory_import import import_strategy_seed_dir


def _session_factory():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)


def _write_strategy(path: Path, *, body: str = "Use deep probes.") -> None:
    path.write_text(
        "\n".join(
            [
                "---",
                "name: Senior System Design Strategy",
                "description: Deep follow-ups for senior system design candidates",
                "display_name_zh: 高级系统设计追问策略",
                "display_description_zh: 用于高级候选人的系统设计深挖追问。",
                "type: strategy",
                "dimensions: [system_design, architecture]",
                "job_levels: [senior, staff]",
                "memory_key: seed:system_design:senior",
                "---",
                "",
                body,
                "",
            ]
        ),
        encoding="utf-8",
    )


def test_import_strategy_seed_dir_imports_markdown_and_skips_memory_index(
    tmp_path: Path,
) -> None:
    strategy_dir = tmp_path / "strategy"
    strategy_dir.mkdir()
    _write_strategy(strategy_dir / "senior_system_design.md")
    (strategy_dir / "MEMORY.md").write_text("# Index\n", encoding="utf-8")

    Session = _session_factory()
    with Session() as sess:
        result = import_strategy_seed_dir(strategy_dir, session=sess)
        sess.commit()
        rows = list(sess.scalars(select(StrategyMemory)))

    assert result.imported == 1
    assert result.updated == 0
    assert result.unchanged == 0
    assert result.skipped == 1
    assert len(rows) == 1

    row = rows[0]
    assert row.id == "seed:senior_system_design"
    assert row.slug == "senior_system_design"
    assert row.name == "Senior System Design Strategy"
    assert row.description == "Deep follow-ups for senior system design candidates"
    assert row.display_name_zh == "高级系统设计追问策略"
    assert row.display_description_zh == "用于高级候选人的系统设计深挖追问。"
    assert row.source == "seed"
    assert row.memory_key == "seed:system_design:senior"
    assert row.dimensions == ["system_design", "architecture"]
    assert row.job_levels == ["senior", "staff"]
    assert row.body_markdown == "Use deep probes."
    assert row.status == "active"
    assert row.promotion_stage == "seed"
    assert row.version == 1
    assert row.content_hash.startswith("sha1:")


def test_import_strategy_seed_dir_is_idempotent_and_versions_content_changes(
    tmp_path: Path,
) -> None:
    strategy_dir = tmp_path / "strategy"
    strategy_dir.mkdir()
    seed = strategy_dir / "senior_system_design.md"
    _write_strategy(seed, body="Use deep probes.")

    Session = _session_factory()
    with Session() as sess:
        first = import_strategy_seed_dir(strategy_dir, session=sess)
        second = import_strategy_seed_dir(strategy_dir, session=sess)
        first_row = sess.get(StrategyMemory, "seed:senior_system_design")
        assert first_row is not None
        first_hash = first_row.content_hash

        _write_strategy(seed, body="Use deep probes and quantify scale.")
        third = import_strategy_seed_dir(strategy_dir, session=sess)
        changed = sess.get(StrategyMemory, "seed:senior_system_design")

    assert first.imported == 1
    assert second.unchanged == 1
    assert third.updated == 1
    assert changed is not None
    assert changed.version == 2
    assert changed.content_hash != first_hash
    assert changed.body_markdown == "Use deep probes and quantify scale."
    assert changed.display_name_zh == "高级系统设计追问策略"
    assert changed.display_description_zh == "用于高级候选人的系统设计深挖追问。"
