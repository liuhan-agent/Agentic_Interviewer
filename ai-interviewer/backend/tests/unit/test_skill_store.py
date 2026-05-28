"""Tests for :mod:`app.memory.skill_store`.

Covers the three layers of the skill registry:

1. Frontmatter parsing (``SkillEntry`` shape coming off disk).
2. Relevance scoring (``retrieve_skills`` filters + ranking).
3. Prompt rendering (``build_skills_block`` / ``build_skills_index``).

The tests pin file-system behaviour by monkey-patching ``_skills_dir``
so they can run against a ``tmp_path`` sandbox and never touch the
real ``knowledge/skills/`` directory.
"""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.memory import skill_store
from app.models.base import Base
from app.models.skill_playbook import SkillPlaybookCard

_SKILL_CARD_A = """\
---
id: senior_backend_ownership
name: Senior Backend Ownership
description: Probe ownership, not buzzwords.
display_name_zh: 高级后端归属追问卡
display_description_zh: 引导回答明确个人负责的决策、行动和结果。
status: active
priority: 7
direction_tags: [internet_tech]
role_tags: [java_backend, architect]
dimensions: [leadership, system_design]
job_levels: [senior, staff]
probe_intents: [architecture_challenge]
failure_categories: [generic_storytelling]
generator_moves: [Ask what the candidate personally owned.]
watch_for: [Separates personal ownership from team context.]
avoid: ['Accepting "we built" without a personal action.']
evaluator_rubric_hints: [Reward concrete ownership evidence.]
positive_signals: ["Names decision, action, and outcome."]
negative_signals: [Only describes team-level work.]
score_bias_rules: [Soft positive for first-person accountable action.]
evaluator_visibility: true
---
Body A goes here.
Longer paragraph that explains the probe strategy in detail so the
Generator can follow.
"""

_SKILL_CARD_B = """\
---
name: Junior Algorithm Warm-up
description: Keep first-turn coding questions approachable.
dimensions: [coding]
job_levels: [junior]
---
Body B describes a warm-up strategy.
"""

_SKILL_CARD_UNIVERSAL = """\
---
name: Ask for Concrete Example
description: Always demand at least one concrete example.
---
Applies everywhere, regardless of dimension or level.
"""


def _write_skill(root: Path, name: str, body: str) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    path = root / name
    path.write_text(body, encoding="utf-8")
    return path


def _install_db_cards(
    monkeypatch: pytest.MonkeyPatch,
    cards: list[SkillPlaybookCard],
) -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    session_local = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    with session_local() as sess:
        sess.add_all(cards)
        sess.commit()

    @contextmanager
    def fake_get_session():
        with session_local() as sess:
            yield sess

    monkeypatch.setattr(skill_store, "get_session", fake_get_session, raising=False)


def _db_card(
    card_id: str,
    *,
    name: str = "DB Production Incident",
    status: str = "active",
    source: str = "manual_markdown",
    dimensions: list[str] | None = None,
    role_tags: list[str] | None = None,
) -> SkillPlaybookCard:
    return SkillPlaybookCard(
        id=card_id,
        name=name,
        description="DB-backed probe card.",
        display_name_zh="DB 生产事故追问卡",
        display_description_zh="引导 DB 卡片回答覆盖事故信号和预防措施。",
        body_markdown=f"Body for {card_id}.",
        status=status,
        priority=7,
        direction_tags=["internet_tech"],
        role_tags=role_tags or ["java_backend"],
        dimensions=dimensions or ["problem_solving"],
        job_levels=["senior"],
        probe_intents=["debugging_probe"],
        failure_categories=["root_cause_missing"],
        generator_moves=["Ask for detection signal."],
        watch_for=["Separates mitigation from prevention."],
        avoid=["Accepting generic monitoring claims."],
        evaluator_rubric_hints=["Credit concrete incident evidence."],
        positive_signals=["Names metric, owner, and rollback."],
        negative_signals=["Jumps to fix without diagnosis."],
        score_bias_rules=["Soft positive for measurable prevention."],
        evaluator_visibility=True,
        source=source,
        content_hash=f"sha1:{card_id}",
    )


@pytest.fixture
def skills_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Path:
    """Return a ``tmp_path / 'skills'`` root that ``skill_store`` sees.

    Uses ``monkeypatch.setattr`` on the module-local ``_skills_dir``
    so the tests never read the real ``knowledge/skills/`` directory
    and cannot accidentally mutate it.
    """
    root = tmp_path / "skills"
    monkeypatch.setattr(skill_store, "_skills_dir", lambda: root)
    monkeypatch.setattr(
        skill_store,
        "get_settings",
        lambda: SimpleNamespace(skill_playbook_backend="file"),
    )
    return root


def test_list_skills_empty_when_dir_missing(
    skills_root: Path,
) -> None:
    """No directory → empty list (do not raise, do not create)."""
    assert not skills_root.exists()
    assert skill_store.list_skills() == []


def test_list_skills_parses_frontmatter(skills_root: Path) -> None:
    _write_skill(skills_root, "a.md", _SKILL_CARD_A)
    entries = skill_store.list_skills()

    assert len(entries) == 1
    e = entries[0]
    assert e.name == "Senior Backend Ownership"
    assert e.description == "Probe ownership, not buzzwords."
    assert e.display_name_zh == "高级后端归属追问卡"
    assert e.display_description_zh == "引导回答明确个人负责的决策、行动和结果。"
    assert e.id == "senior_backend_ownership"
    assert e.status == "active"
    assert e.priority == 7
    assert e.direction_tags == ["internet_tech"]
    assert e.role_tags == ["java_backend", "architect"]
    assert e.dimensions == ["leadership", "system_design"]
    assert e.job_levels == ["senior", "staff"]
    assert e.probe_intents == ["architecture_challenge"]
    assert e.failure_categories == ["generic_storytelling"]
    assert e.generator_moves == ["Ask what the candidate personally owned."]
    assert e.watch_for == ["Separates personal ownership from team context."]
    assert e.avoid == ['Accepting "we built" without a personal action.']
    assert e.evaluator_rubric_hints == ["Reward concrete ownership evidence."]
    assert e.positive_signals == ["Names decision, action, and outcome."]
    assert e.negative_signals == ["Only describes team-level work."]
    assert e.score_bias_rules == [
        "Soft positive for first-person accountable action."
    ]
    assert e.evaluator_visibility is True
    assert "Body A goes here." in e.body
    # Frontmatter must be stripped from the body.
    assert "---" not in e.body.splitlines()[0]


def test_list_skills_ignores_index_file(skills_root: Path) -> None:
    """``SKILL.md`` is the navigation index, not a skill card."""
    _write_skill(skills_root, "SKILL.md", "# SKILL index file")
    _write_skill(skills_root, "a.md", _SKILL_CARD_A)
    entries = skill_store.list_skills()
    assert [e.path.name for e in entries] == ["a.md"]


def test_list_skills_db_backend_reads_manual_markdown_cards(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_db_cards(
        monkeypatch,
        [
            _db_card("tech_db_probe", name="DB Probe"),
            _db_card("generated_probe", name="Generated Probe", source="generated"),
        ],
    )

    entries = skill_store.list_skills(backend="db")

    assert [entry.id for entry in entries] == ["tech_db_probe"]
    assert entries[0].name == "DB Probe"
    assert entries[0].display_name_zh == "DB 生产事故追问卡"
    assert entries[0].display_description_zh == "引导 DB 卡片回答覆盖事故信号和预防措施。"
    assert entries[0].path.name == "tech_db_probe.md"
    assert entries[0].body == "Body for tech_db_probe."
    assert entries[0].generator_moves == ["Ask for detection signal."]
    assert entries[0].evaluator_visibility is True


def test_retrieve_skills_db_backend_ranks_and_filters_inactive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_db_cards(
        monkeypatch,
        [
            _db_card("db_incident", name="DB Incident Probe"),
            _db_card("db_draft", status="draft"),
            _db_card("db_archived", status="archived"),
        ],
    )

    entries = skill_store.retrieve_skills(
        dimension="problem_solving",
        job_level="senior",
        direction_tags=["internet_tech"],
        role_tags=["java_backend"],
        probe_intent="debugging_probe",
        failure_categories=["root_cause_missing"],
        backend="db",
    )

    assert [entry.id for entry in entries] == ["db_incident"]
    assert "role_tag:java_backend" in entries[0].match_reasons
    assert "probe_intent:debugging_probe" in entries[0].match_reasons
    assert "failure_category:root_cause_missing" in entries[0].match_reasons


def test_db_with_file_fallback_uses_file_when_db_has_no_active_cards(
    skills_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_db_cards(monkeypatch, [_db_card("db_draft_only", status="draft")])
    _write_skill(skills_root, "file.md", _SKILL_CARD_A)

    entries = skill_store.retrieve_skills(
        dimension="system_design",
        job_level="senior",
        direction_tags=["internet_tech"],
        role_tags=["java_backend"],
        backend="db_with_file_fallback",
    )

    assert [entry.id for entry in entries] == ["senior_backend_ownership"]


def test_db_with_file_fallback_uses_file_on_db_error(
    skills_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def failing_get_session():
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(skill_store, "get_session", failing_get_session, raising=False)
    _write_skill(skills_root, "file.md", _SKILL_CARD_A)

    entries = skill_store.retrieve_skills(
        dimension="system_design",
        job_level="senior",
        direction_tags=["internet_tech"],
        role_tags=["java_backend"],
        backend="db_with_file_fallback",
    )

    assert [entry.id for entry in entries] == ["senior_backend_ownership"]


def test_db_with_file_fallback_does_not_fallback_when_db_has_active_nonmatch(
    skills_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_db_cards(
        monkeypatch,
        [_db_card("db_coding_only", dimensions=["coding_quality"])],
    )
    _write_skill(skills_root, "file.md", _SKILL_CARD_A)

    entries = skill_store.retrieve_skills(
        dimension="system_design",
        job_level="senior",
        direction_tags=["internet_tech"],
        role_tags=["java_backend"],
        backend="db_with_file_fallback",
    )

    assert entries == []


def test_db_backend_does_not_fallback_to_file_on_error(
    skills_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def failing_get_session():
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(skill_store, "get_session", failing_get_session, raising=False)
    _write_skill(skills_root, "file.md", _SKILL_CARD_A)

    entries = skill_store.retrieve_skills(
        dimension="system_design",
        job_level="senior",
        direction_tags=["internet_tech"],
        role_tags=["java_backend"],
        backend="db",
    )

    assert entries == []


def test_retrieve_skills_scores_dimension_match_highest(
    skills_root: Path,
) -> None:
    _write_skill(skills_root, "a.md", _SKILL_CARD_A)
    _write_skill(skills_root, "b.md", _SKILL_CARD_B)
    _write_skill(skills_root, "u.md", _SKILL_CARD_UNIVERSAL)

    entries = skill_store.retrieve_skills(
        dimension="system_design",
        job_level="senior",
        direction_tags=["internet_tech"],
        role_tags=["java_backend"],
    )

    # "Senior Backend Ownership" matches both dimension (+2) and
    # level (+1) -> score 3 — ranks first.
    # Universal ("u.md") matches "no dimensions → +1" -> score 1.
    # "Junior Algorithm Warm-up" matches nothing (wrong dim, wrong
    # level) -> score 0 → dropped.
    names = [e.name for e in entries]
    assert names == [
        "Senior Backend Ownership",
        "Ask for Concrete Example",
    ]
    assert entries[0].match_score > entries[1].match_score
    assert "role_tag:java_backend" in entries[0].match_reasons
    assert "direction_tag:internet_tech" in entries[0].match_reasons


def test_retrieve_skills_returns_empty_when_nothing_matches(
    skills_root: Path,
) -> None:
    _write_skill(skills_root, "b.md", _SKILL_CARD_B)
    entries = skill_store.retrieve_skills(
        dimension="system_design", job_level="senior"
    )
    assert entries == []


def test_retrieve_skills_filters_inactive_and_role_mismatch(
    skills_root: Path,
) -> None:
    _write_skill(
        skills_root,
        "inactive.md",
        "---\n"
        "name: Draft Card\n"
        "status: draft\n"
        "dimensions: [system_design]\n"
        "job_levels: [senior]\n"
        "---\nDraft body",
    )
    _write_skill(
        skills_root,
        "frontend.md",
        "---\n"
        "name: Frontend Only\n"
        "status: active\n"
        "direction_tags: [internet_tech]\n"
        "role_tags: [frontend_web]\n"
        "dimensions: [system_design]\n"
        "job_levels: [senior]\n"
        "---\nFrontend body",
    )

    entries = skill_store.retrieve_skills(
        dimension="system_design",
        job_level="senior",
        direction_tags=["internet_tech"],
        role_tags=["java_backend"],
    )

    assert entries == []


def test_retrieve_skills_ranks_probe_and_failure_matches(
    skills_root: Path,
) -> None:
    _write_skill(
        skills_root,
        "generic.md",
        "---\n"
        "id: generic_metric_probe\n"
        "name: Generic Metric Probe\n"
        "priority: 4\n"
        "---\nGeneric body",
    )
    _write_skill(
        skills_root,
        "specific.md",
        "---\n"
        "id: java_incident_debugging\n"
        "name: Java Incident Debugging\n"
        "priority: 1\n"
        "direction_tags: [internet_tech]\n"
        "role_tags: [java_backend]\n"
        "dimensions: [problem_solving]\n"
        "job_levels: [senior]\n"
        "probe_intents: [debugging_probe]\n"
        "failure_categories: [root_cause_missing]\n"
        "---\nSpecific body",
    )

    entries = skill_store.retrieve_skills(
        dimension="problem_solving",
        job_level="senior",
        direction_tags=["internet_tech"],
        role_tags=["java_backend"],
        probe_intent="debugging_probe",
        failure_categories=["root_cause_missing"],
    )

    assert [entry.id for entry in entries] == [
        "java_incident_debugging",
        "generic_metric_probe",
    ]
    assert "probe_intent:debugging_probe" in entries[0].match_reasons
    assert "failure_category:root_cause_missing" in entries[0].match_reasons


def test_retrieve_skills_with_llm_selector_filters_keyword_set(
    skills_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``use_llm_selector=True`` must pipe the keyword-filtered
    candidates through :func:`select_memories_with_llm`; the final
    return order follows the LLM reply rather than the keyword
    score order. LLM is stubbed so the test stays fast and
    deterministic.
    """
    # Three matching skills; keyword score puts them in scan order.
    for i in range(3):
        _write_skill(
            skills_root,
            f"skill_{i}.md",
            f"---\n"
            f"name: Skill {i}\n"
            f"description: desc {i}.\n"
            f"display_name_zh: 技能 {i}\n"
            f"display_description_zh: 中文展示描述 {i}。\n"
            f"dimensions: [system_design]\n"
            f"job_levels: [senior]\n"
            f"---\nBody {i}",
        )

    import app.memory.skill_store as sstore

    # LLM picks {skill_2, skill_0} in a DIFFERENT order than keyword
    # would have produced — the test proves the LLM reply steers the
    # final selection.
    monkeypatch.setattr(
        sstore,
        "_skills_dir",
        lambda: skills_root,
    )

    def fake_select(candidates, context, *, top_n):
        assert [candidate.name for candidate in candidates] == [
            "Skill 0",
            "Skill 1",
            "Skill 2",
        ]
        assert [candidate.description for candidate in candidates] == [
            "desc 0.",
            "desc 1.",
            "desc 2.",
        ]
        assert all(not hasattr(candidate, "display_name_zh") for candidate in candidates)
        return ["skill_2.md", "skill_0.md"]

    # The skill_store imports ``select_memories_with_llm`` locally inside
    # the function; patch at the import path used by that function.
    monkeypatch.setattr(
        "app.memory.llm_selector.select_memories_with_llm",
        fake_select,
    )

    entries = skill_store.retrieve_skills(
        dimension="system_design",
        job_level="senior",
        limit=5,
        use_llm_selector=True,
    )
    names = [e.path.name for e in entries]
    assert names == ["skill_2.md", "skill_0.md"]


def test_retrieve_skills_llm_selector_fallback_on_none(
    skills_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """LLM selector returning ``None`` (provider failure / unparsable
    reply) must NOT drop the caller into an empty list — fall back
    to the keyword top-N untouched."""
    _write_skill(skills_root, "a.md", _SKILL_CARD_A)

    monkeypatch.setattr(
        "app.memory.llm_selector.select_memories_with_llm",
        lambda *args, **kwargs: None,
    )

    entries = skill_store.retrieve_skills(
        dimension="system_design",
        job_level="senior",
        limit=3,
        use_llm_selector=True,
        direction_tags=["internet_tech"],
        role_tags=["java_backend"],
    )
    assert [e.path.name for e in entries] == ["a.md"]


def test_retrieve_skills_respects_limit(skills_root: Path) -> None:
    # Seed 5 dimension-matching skill cards; limit=2 keeps top 2.
    for i in range(5):
        _write_skill(
            skills_root,
            f"skill_{i}.md",
            f"---\n"
            f"name: Skill {i}\n"
            f"description: Skill description {i}.\n"
            f"dimensions: [system_design]\n"
            f"job_levels: [senior]\n"
            f"---\nBody {i}",
        )
    entries = skill_store.retrieve_skills(
        dimension="system_design", job_level="senior", limit=2
    )
    assert len(entries) == 2


def test_retrieve_skills_adds_reward_shadow_without_changing_return_order(
    skills_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.models.skill_playbook import SkillRewardRollout, SkillUsageStats

    _write_skill(
        skills_root,
        "metadata_top.md",
        "---\n"
        "id: metadata_top\n"
        "name: Metadata Top\n"
        "priority: 10\n"
        "role_tags: [java_backend]\n"
        "dimensions: [system_design]\n"
        "job_levels: [senior]\n"
        "probe_intents: [evidence_probe]\n"
        "---\nMetadata top body",
    )
    _write_skill(
        skills_root,
        "reward_top.md",
        "---\n"
        "id: reward_top\n"
        "name: Reward Top\n"
        "priority: 1\n"
        "role_tags: [java_backend]\n"
        "dimensions: [system_design]\n"
        "job_levels: [senior]\n"
        "probe_intents: [evidence_probe]\n"
        "---\nReward top body",
    )

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    session_local = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    with session_local() as sess:
        sess.add_all(
            [
                SkillUsageStats(
                    id="skill-usage-stats:metadata",
                    skill_id="metadata_top",
                    skill_context_key="java_backend:senior:system_design:evidence_probe",
                    role="java_backend",
                    job_level="senior",
                    dimension="system_design",
                    probe_intent="evidence_probe",
                    uses=25,
                    injected_uses=25,
                    rewarded_uses=25,
                    avg_blended_reward=0.1,
                    pass_rate=0.2,
                    overrule_rate=0.0,
                ),
                SkillUsageStats(
                    id="skill-usage-stats:reward",
                    skill_id="reward_top",
                    skill_context_key="java_backend:senior:system_design:evidence_probe",
                    role="java_backend",
                    job_level="senior",
                    dimension="system_design",
                    probe_intent="evidence_probe",
                    uses=25,
                    injected_uses=25,
                    rewarded_uses=25,
                    avg_blended_reward=1.0,
                    pass_rate=1.0,
                    overrule_rate=0.0,
                ),
            ]
        )
        sess.commit()

    @contextmanager
    def fake_get_session():
        with session_local() as sess:
            yield sess

    monkeypatch.setattr(skill_store, "get_session", fake_get_session, raising=False)

    entries = skill_store.retrieve_skills(
        dimension="system_design",
        job_level="senior",
        role_tags=["java_backend"],
        probe_intent="evidence_probe",
        limit=2,
    )

    assert [entry.id for entry in entries] == ["metadata_top", "reward_top"]
    assert entries[0].reward_shadow_rank == 2
    assert entries[0].reward_shadow_rank_changed is True
    assert entries[1].reward_shadow_rank == 1
    assert entries[1].reward_shadow_rank_changed is True
    assert entries[1].usage_stats == {
        "uses": 25,
        "injected_uses": 25,
        "rewarded_uses": 25,
        "avg_score": None,
        "pass_rate": 1.0,
        "avg_immediate_reward": None,
        "avg_blended_reward": 1.0,
        "overrule_rate": 0.0,
    }
    assert entries[1].reward_shadow_reason["metadata_rank"] == 2
    assert entries[1].reward_shadow_reason["shadow_rank"] == 1
    assert entries[1].reward_shadow_reason["status"] == "scored"


def test_retrieve_skills_reward_rollout_can_change_return_order(
    skills_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.models.skill_playbook import SkillRewardRollout, SkillUsageStats

    for idx in range(5):
        _write_skill(
            skills_root,
            f"skill_{idx}.md",
            "---\n"
            f"id: skill_{idx}\n"
            f"name: Skill {idx}\n"
            f"priority: {10 - idx}\n"
            "role_tags: [java_backend]\n"
            "dimensions: [system_design]\n"
            "job_levels: [senior]\n"
            "probe_intents: [evidence_probe]\n"
            "---\nSkill body",
        )

    context_key = "java_backend:senior:system_design:evidence_probe"
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    session_local = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    with session_local() as sess:
        sess.add(SkillRewardRollout(context_key=context_key, mode="reward"))
        for idx in range(5):
            sess.add(
                SkillUsageStats(
                    id=f"skill-usage-stats:{idx}",
                    skill_id=f"skill_{idx}",
                    skill_context_key=context_key,
                    role="java_backend",
                    job_level="senior",
                    dimension="system_design",
                    probe_intent="evidence_probe",
                    uses=25,
                    injected_uses=25,
                    rewarded_uses=25,
                    avg_blended_reward=1.0 if idx == 4 else 0.1,
                    pass_rate=1.0 if idx == 4 else 0.2,
                    overrule_rate=0.0,
                )
            )
        sess.commit()

    @contextmanager
    def fake_get_session():
        with session_local() as sess:
            yield sess

    monkeypatch.setattr(skill_store, "get_session", fake_get_session, raising=False)

    entries = skill_store.retrieve_skills(
        dimension="system_design",
        job_level="senior",
        role_tags=["java_backend"],
        probe_intent="evidence_probe",
        limit=3,
    )

    assert [entry.id for entry in entries][:3] == ["skill_4", "skill_0", "skill_1"]
    assert entries[0].reward_shadow_reason["live_order"] == "reward"
    assert entries[0].reward_shadow_reason["rollout_mode"] == "reward"


def test_retrieve_skills_reward_rollout_falls_back_when_gate_blocks(
    skills_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.models.skill_playbook import SkillRewardRollout, SkillUsageStats

    for idx in range(2):
        _write_skill(
            skills_root,
            f"small_{idx}.md",
            "---\n"
            f"id: small_{idx}\n"
            f"name: Small {idx}\n"
            f"priority: {10 - idx}\n"
            "role_tags: [java_backend]\n"
            "dimensions: [system_design]\n"
            "job_levels: [senior]\n"
            "probe_intents: [evidence_probe]\n"
            "---\nSkill body",
        )

    context_key = "java_backend:senior:system_design:evidence_probe"
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    session_local = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    with session_local() as sess:
        sess.add(SkillRewardRollout(context_key=context_key, mode="reward"))
        for idx in range(2):
            sess.add(
                SkillUsageStats(
                    id=f"skill-usage-stats:small-{idx}",
                    skill_id=f"small_{idx}",
                    skill_context_key=context_key,
                    role="java_backend",
                    job_level="senior",
                    dimension="system_design",
                    probe_intent="evidence_probe",
                    uses=2,
                    injected_uses=2,
                    rewarded_uses=2,
                    avg_blended_reward=1.0 if idx == 1 else 0.1,
                    pass_rate=1.0,
                    overrule_rate=0.0,
                )
            )
        sess.commit()

    @contextmanager
    def fake_get_session():
        with session_local() as sess:
            yield sess

    monkeypatch.setattr(skill_store, "get_session", fake_get_session, raising=False)

    entries = skill_store.retrieve_skills(
        dimension="system_design",
        job_level="senior",
        role_tags=["java_backend"],
        probe_intent="evidence_probe",
        limit=2,
    )

    assert [entry.id for entry in entries] == ["small_0", "small_1"]
    assert entries[0].reward_shadow_reason["live_order"] == "metadata_fallback"
    assert "candidate_pool_below_min" in entries[0].reward_shadow_reason["gate_reasons"]
    assert "reward_samples_below_min" in entries[0].reward_shadow_reason["gate_reasons"]


def test_build_skills_block_empty_input_returns_placeholder(
    skills_root: Path,
) -> None:
    """Empty input list → stable placeholder string. Callers can
    unconditionally forward the result to the Generator prompt."""
    assert skill_store.build_skills_block([]) == (
        "(no relevant interview skills)"
    )


def test_build_skills_block_renders_entries(skills_root: Path) -> None:
    _write_skill(skills_root, "a.md", _SKILL_CARD_A)
    entries = skill_store.list_skills()
    block = skill_store.build_skills_block(entries)

    assert "[Skill 1] Senior Backend Ownership" in block
    assert "dims=leadership, system_design" in block
    assert "levels=senior, staff" in block
    assert "Generator moves:" in block
    assert "高级后端归属追问卡" not in block
    assert "引导回答明确个人负责的决策" not in block
    assert "Ask what the candidate personally owned." in block
    assert "Watch for:" in block
    assert "Avoid:" in block
    assert "Body A goes here." not in block


def test_build_skills_block_falls_back_to_body_for_legacy_cards(
    skills_root: Path,
) -> None:
    _write_skill(skills_root, "legacy.md", _SKILL_CARD_UNIVERSAL)
    entries = skill_store.list_skills()
    block = skill_store.build_skills_block(entries)

    assert "Applies everywhere, regardless of dimension or level." in block


def test_build_skills_block_truncates_long_body(
    skills_root: Path,
) -> None:
    long_body = "x" * 2000
    _write_skill(
        skills_root,
        "a.md",
        "---\nname: Long\ndescription: .\n---\n" + long_body,
    )
    entries = skill_store.list_skills()
    block = skill_store.build_skills_block(entries, max_body_chars=200)
    assert "truncated" in block
    assert "x" * 2000 not in block


def test_build_skills_index_compact_catalog(skills_root: Path) -> None:
    _write_skill(skills_root, "a.md", _SKILL_CARD_A)
    _write_skill(skills_root, "b.md", _SKILL_CARD_B)
    index = skill_store.build_skills_index()
    assert index.startswith("## Available Interview Skills")
    assert "Senior Backend Ownership" in index
    assert "Junior Algorithm Warm-up" in index
    assert "高级后端归属追问卡" not in index
    assert "引导回答明确个人负责的决策" not in index


def test_build_skills_index_empty_returns_empty_string(
    skills_root: Path,
) -> None:
    """Empty registry → empty string (caller can unconditionally
    concatenate into ``dynamic_system``)."""
    assert skill_store.build_skills_index() == ""
