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
    session_factory = sessionmaker(
        bind=engine,
        expire_on_commit=False,
        autoflush=False,
    )

    with session_factory() as sess:
        sess.add_all(
            [
                StrategyMemory(
                    id="seed:senior_system_design",
                    slug="senior_system_design",
                    name="Senior System Design",
                    description="Deep probes for senior system design.",
                    display_name_zh="高级系统设计策略",
                    display_description_zh="用于高级候选人的系统设计追问。",
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
        with session_factory() as sess:
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
    assert entries[0].display_name_zh == "高级系统设计策略"
    assert entries[0].display_description_zh == "用于高级候选人的系统设计追问。"
    assert entries[0].source == "seed"
    assert entries[0].promotion_stage == "seed"
    assert "Senior System Design" in block
    assert "concrete trade-offs" in block


def test_render_strategies_for_prompt_uses_rank_aware_budgets() -> None:
    entries = [
        ss.StrategyEntry(
            path=Path(f"strategy-{idx}.md"),
            id=f"strategy-{idx}",
            name=f"Strategy {idx}",
            dimensions=["technical_depth"],
            job_levels=["junior"],
            body=chr(96 + idx) * 2000,
        )
        for idx in range(1, 4)
    ]

    result = ss.render_strategies_for_prompt(entries)

    assert result.budget_chars == 3200
    assert len(result.text) <= 3200
    assert result.runtime_truncated is True
    assert result.items[0]["body_budget_chars"] == 1200
    assert result.items[1]["body_budget_chars"] == 800
    assert result.items[2]["body_budget_chars"] == 500
    assert result.items[0]["injected_body_chars"] > result.items[2]["injected_body_chars"]
    assert result.items[0]["runtime_truncated"] is True
    assert result.items[0]["truncation_reason"] == "body_budget_exceeded"


def test_render_strategies_for_prompt_respects_total_slot_budget() -> None:
    entries = [
        ss.StrategyEntry(
            path=Path(f"strategy-{idx}.md"),
            id=f"strategy-{idx}",
            name="Verbose Strategy " + ("x" * 160),
            dimensions=["technical_depth", "system_design", "problem_solving"],
            job_levels=["junior", "mid", "senior"],
            body=str(idx) * 2000,
        )
        for idx in range(1, 8)
    ]

    result = ss.render_strategies_for_prompt(entries)

    assert len(result.text) <= result.budget_chars
    assert result.runtime_truncated is True
    assert len(result.items) == len(entries)
    assert any(
        item["truncation_reason"] in {"slot_budget_reduced", "slot_budget_omitted_body"}
        for item in result.items
    )
    assert "[Strategy 1]" in result.text
    assert "Verbose Strategy" in result.text


def test_render_strategies_for_prompt_accepts_dynamic_budget_diagnostics() -> None:
    entries = [
        ss.StrategyEntry(
            path=Path(f"strategy-{idx}.md"),
            id=f"strategy-{idx}",
            name=f"Dynamic Strategy {idx}",
            dimensions=["technical_depth"],
            job_levels=["junior"],
            body=chr(96 + idx) * 3000,
        )
        for idx in range(1, 4)
    ]

    result = ss.render_strategies_for_prompt(
        entries,
        slot_budget_chars=4800,
        rank_body_budgets=(1800, 1200, 800, 400),
        budget_level="expanded",
        budget_source="prompt_budget_diagnostics",
        global_budget_pressure="expanded",
    )
    diagnostics = result.as_diagnostics()

    assert result.budget_chars == 4800
    assert len(result.text) <= 4800
    assert result.items[0]["body_budget_chars"] == 1800
    assert result.items[1]["body_budget_chars"] == 1200
    assert result.items[2]["body_budget_chars"] == 800
    assert diagnostics["budget_level"] == "expanded"
    assert diagnostics["budget_source"] == "prompt_budget_diagnostics"
    assert diagnostics["global_budget_pressure"] == "expanded"


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
        "display_name_zh: 文件策略展示名\n"
        "display_description_zh: 文件策略中文描述。\n"
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
    assert entries[0].display_name_zh == "文件策略展示名"
    assert entries[0].display_description_zh == "文件策略中文描述。"
    assert entries[0].body == "File-backed body."
