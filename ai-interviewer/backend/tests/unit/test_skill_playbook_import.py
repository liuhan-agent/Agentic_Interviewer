from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
from app.models.skill_playbook import SkillPlaybookCard
from app.services.skill_playbook_import import (
    SkillPlaybookImportError,
    import_skill_playbook_dir,
    parse_skill_playbook_dir,
)


def _session_factory():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)


def _write_skill(
    path: Path,
    *,
    card_id: str = "tech_production_incident_probe",
    name: str = "Production Incident Probe",
    description: str = "Drive answers toward root cause and prevention.",
    status: str = "active",
    priority: str = "7",
    body: str = "Ask for detection signal, mitigation, root cause, and prevention.",
    extra_frontmatter: str = "",
) -> None:
    path.write_text(
        "\n".join(
            [
                "---",
                f"id: {card_id}",
                f"name: {name}",
                f"description: {description}",
                f"status: {status}",
                f"priority: {priority}",
                "direction_tags: [Internet Tech]",
                "role_tags: [Java Backend, SRE]",
                "dimensions: [Problem Solving, Technical Depth]",
                "job_levels: [Mid, Senior]",
                "probe_intents: [Debugging Probe]",
                "failure_categories: [Root Cause Missing]",
                "generator_moves:",
                "  - Ask for detection signal.",
                "  - Ask for first mitigation.",
                "watch_for: [Distinguishes mitigation from root cause]",
                "avoid: [Accepting generic monitoring claims]",
                "evaluator_rubric_hints: [Credit concrete blast radius evidence]",
                "positive_signals: [Names metric and owner]",
                "negative_signals: [Jumps to solution without diagnosis]",
                "score_bias_rules: [Soft positive for measurable prevention]",
                "evaluator_visibility: true",
                extra_frontmatter,
                "---",
                "",
                body,
                "",
            ]
        ),
        encoding="utf-8",
    )


def test_import_skill_playbook_dir_imports_markdown_and_skips_index(
    tmp_path: Path,
) -> None:
    skill_dir = tmp_path / "skills"
    skill_dir.mkdir()
    _write_skill(skill_dir / "incident.md")
    (skill_dir / "SKILL.md").write_text("# Index\n", encoding="utf-8")

    session_local = _session_factory()
    with session_local() as sess:
        result = import_skill_playbook_dir(skill_dir, session=sess)
        sess.commit()
        rows = list(sess.scalars(select(SkillPlaybookCard)))

    assert result.imported == 1
    assert result.updated == 0
    assert result.unchanged == 0
    assert result.archived == 0
    assert result.skipped == 1
    assert len(rows) == 1

    row = rows[0]
    assert row.id == "tech_production_incident_probe"
    assert row.name == "Production Incident Probe"
    assert row.description == "Drive answers toward root cause and prevention."
    assert row.body_markdown == (
        "Ask for detection signal, mitigation, root cause, and prevention."
    )
    assert row.status == "active"
    assert row.priority == 7
    assert row.direction_tags == ["internet_tech"]
    assert row.role_tags == ["java_backend", "sre"]
    assert row.dimensions == ["problem_solving", "technical_depth"]
    assert row.job_levels == ["mid", "senior"]
    assert row.probe_intents == ["debugging_probe"]
    assert row.failure_categories == ["root_cause_missing"]
    assert row.generator_moves == [
        "Ask for detection signal.",
        "Ask for first mitigation.",
    ]
    assert row.watch_for == ["Distinguishes mitigation from root cause"]
    assert row.avoid == ["Accepting generic monitoring claims"]
    assert row.evaluator_rubric_hints == [
        "Credit concrete blast radius evidence"
    ]
    assert row.positive_signals == ["Names metric and owner"]
    assert row.negative_signals == ["Jumps to solution without diagnosis"]
    assert row.score_bias_rules == ["Soft positive for measurable prevention"]
    assert row.evaluator_visibility is True
    assert row.source == "manual_markdown"
    assert row.version == 1
    assert row.content_hash is not None
    assert row.content_hash.startswith("sha1:")


def test_parse_bundled_skill_playbooks_is_strict_clean() -> None:
    skill_dir = Path(__file__).resolve().parents[2] / "knowledge" / "skills"

    cards, skipped = parse_skill_playbook_dir(skill_dir)

    assert skipped == 1
    assert len(cards) >= 18
    assert {card.values["id"] for card in cards} >= {
        "universal_concrete_evidence_probe",
        "tech_production_incident_probe",
        "business_user_metric_probe",
        "service_escalation_probe",
        "tech_debug_root_cause_probe",
        "tech_ai_evaluation_probe",
    }
    assert all(card.values["generator_moves"] for card in cards)
    assert any(card.values["evaluator_rubric_hints"] for card in cards)


def test_parse_bundled_skill_playbooks_covers_p1_expansion_cards() -> None:
    """P1 expansion (2026-05) — pin each newly added card as it lands.

    P1 is rolled out one card at a time. Each new card is appended to
    the ``p1_expansion`` dict below so the catalog stops a regression
    that quietly drops the card from the markdown source of truth.
    """
    skill_dir = Path(__file__).resolve().parents[2] / "knowledge" / "skills"

    cards, _skipped = parse_skill_playbook_dir(skill_dir)
    by_id = {card.values["id"]: card.values for card in cards}

    p1_expansion = {
        "tech_sre_slo_capacity_probe": {
            "direction_tags": {"internet_tech"},
            "role_tags": {"sre", "architect"},
            "job_levels": {"senior", "staff", "principal"},
        },
    }

    missing = sorted(p1_expansion.keys() - by_id.keys())
    assert not missing, f"P1 expansion cards missing from catalog: {missing}"

    for card_id, expected in p1_expansion.items():
        values = by_id[card_id]
        assert values["status"] == "active", f"{card_id}: must be active"
        assert int(values["priority"]) >= 6, (
            f"{card_id}: P1 cards should land with priority >= 6"
        )
        assert values["generator_moves"], f"{card_id}: generator_moves required"
        assert values["watch_for"], f"{card_id}: watch_for required"
        assert values["avoid"], f"{card_id}: avoid required"
        assert values["evaluator_rubric_hints"], (
            f"{card_id}: evaluator_rubric_hints required"
        )
        for field, expected_subset in expected.items():
            actual = set(values.get(field, []))
            assert expected_subset <= actual, (
                f"{card_id}: {field} missing values {expected_subset - actual}"
            )


def test_parse_bundled_skill_playbooks_covers_p0_expansion_cards() -> None:
    """P0 expansion (2026-05) — five new cards must all pass strict import.

    Pinning the id set here protects the playbook catalog from accidental
    deletion or renaming of the freshly added direction / role / level
    coverage cards. Each card is also asserted to carry the structured
    fields the runtime + admin observability paths consume.
    """
    skill_dir = Path(__file__).resolve().parents[2] / "knowledge" / "skills"

    cards, _skipped = parse_skill_playbook_dir(skill_dir)
    by_id = {card.values["id"]: card.values for card in cards}

    p0_expansion = {
        "tech_data_engineering_pipeline_probe": {
            "direction_tags": {"internet_tech"},
            "role_tags": {"java_backend", "ai_algorithm", "architect"},
            "job_levels": {"mid", "senior", "staff", "principal"},
        },
        "tech_frontend_perf_render_probe": {
            "direction_tags": {"internet_tech"},
            "role_tags": {"frontend_web", "mobile", "ai_fullstack"},
            "job_levels": {"mid", "senior", "staff"},
        },
        "tech_mobile_platform_probe": {
            "direction_tags": {"internet_tech"},
            "role_tags": {"mobile"},
            "job_levels": {"junior", "mid", "senior", "staff"},
        },
        "business_executive_strategy_probe": {
            "direction_tags": {"business"},
            "role_tags": {"general_management", "product_manager", "operations"},
            "job_levels": {"staff", "principal"},
        },
        "business_data_analyst_insight_probe": {
            "direction_tags": {"business"},
            "role_tags": {"data_analyst"},
            "job_levels": {"junior", "mid", "senior", "staff"},
        },
    }

    missing = sorted(p0_expansion.keys() - by_id.keys())
    assert not missing, f"P0 expansion cards missing from catalog: {missing}"

    for card_id, expected in p0_expansion.items():
        values = by_id[card_id]
        assert values["status"] == "active", f"{card_id}: must be active"
        assert int(values["priority"]) >= 7, (
            f"{card_id}: P0 cards should land with priority >= 7"
        )
        assert values["generator_moves"], f"{card_id}: generator_moves required"
        assert values["watch_for"], f"{card_id}: watch_for required"
        assert values["avoid"], f"{card_id}: avoid required"
        assert values["evaluator_rubric_hints"], (
            f"{card_id}: evaluator_rubric_hints required"
        )
        for field, expected_subset in expected.items():
            actual = set(values.get(field, []))
            assert expected_subset <= actual, (
                f"{card_id}: {field} missing values {expected_subset - actual}"
            )


def test_import_skill_playbook_dir_fails_atomically_with_full_error_list(
    tmp_path: Path,
) -> None:
    skill_dir = tmp_path / "skills"
    skill_dir.mkdir()
    _write_skill(skill_dir / "valid.md")
    _write_skill(
        skill_dir / "invalid.md",
        card_id="tech_production_incident_probe",
        status="retired",
        priority="high",
        extra_frontmatter=(
            "direction_tags: [unknown_direction]\n"
            "role_tags: [unknown_role]\n"
            "probe_intents: [debugging_probe, debugging_probe]\n"
            "generator_moves: [ask, ask]\n"
            "evaluator_visibility: maybe"
        ),
    )

    session_local = _session_factory()
    with session_local() as sess:
        with pytest.raises(SkillPlaybookImportError) as exc:
            import_skill_playbook_dir(skill_dir, session=sess)
        sess.commit()
        rows = list(sess.scalars(select(SkillPlaybookCard)))

    message = "\n".join(exc.value.errors)
    assert "duplicate skill card id: tech_production_incident_probe" in message
    assert "invalid status: retired" in message
    assert "priority must be an integer" in message
    assert "invalid direction_tags" in message
    assert "invalid role_tags" in message
    assert "duplicate probe_intents" in message
    assert "duplicate generator_moves" in message
    assert "evaluator_visibility must be a boolean" in message
    assert rows == []


def test_import_skill_playbook_dir_rejects_missing_frontmatter_and_empty_body(
    tmp_path: Path,
) -> None:
    skill_dir = tmp_path / "skills"
    skill_dir.mkdir()
    (skill_dir / "plain.md").write_text("No frontmatter here.\n", encoding="utf-8")
    _write_skill(skill_dir / "empty.md", body="  \n")

    session_local = _session_factory()
    with session_local() as sess:
        with pytest.raises(SkillPlaybookImportError) as exc:
            import_skill_playbook_dir(skill_dir, session=sess)

    message = "\n".join(exc.value.errors)
    assert "plain.md: missing frontmatter" in message
    assert "empty.md: body_markdown must not be empty" in message


def test_import_skill_playbook_dir_is_idempotent_and_versions_changed_content(
    tmp_path: Path,
) -> None:
    skill_dir = tmp_path / "skills"
    skill_dir.mkdir()
    skill_path = skill_dir / "incident.md"
    _write_skill(skill_path, body="Ask for root cause.")

    session_local = _session_factory()
    with session_local() as sess:
        first = import_skill_playbook_dir(skill_dir, session=sess)
        second = import_skill_playbook_dir(skill_dir, session=sess)
        first_row = sess.get(SkillPlaybookCard, "tech_production_incident_probe")
        assert first_row is not None
        first_hash = first_row.content_hash

        _write_skill(skill_path, body="Ask for root cause and prevention.")
        third = import_skill_playbook_dir(skill_dir, session=sess)
        changed = sess.get(SkillPlaybookCard, "tech_production_incident_probe")

    assert first.imported == 1
    assert second.unchanged == 1
    assert third.updated == 1
    assert changed is not None
    assert changed.version == 2
    assert changed.content_hash != first_hash
    assert changed.body_markdown == "Ask for root cause and prevention."


def test_import_skill_playbook_dir_archive_missing_is_explicit(
    tmp_path: Path,
) -> None:
    skill_dir = tmp_path / "skills"
    skill_dir.mkdir()
    _write_skill(skill_dir / "incident.md")

    session_local = _session_factory()
    with session_local() as sess:
        sess.add(
            SkillPlaybookCard(
                id="manual_absent_card",
                name="Absent",
                description="Absent from markdown.",
                body_markdown="Old body",
                status="active",
                source="manual_markdown",
            )
        )
        sess.add(
            SkillPlaybookCard(
                id="generated_absent_card",
                name="Generated",
                description="Not markdown-owned.",
                body_markdown="Generated body",
                status="active",
                source="generated",
            )
        )
        default_result = import_skill_playbook_dir(skill_dir, session=sess)
        assert sess.get(SkillPlaybookCard, "manual_absent_card").status == "active"

        archive_result = import_skill_playbook_dir(
            skill_dir,
            session=sess,
            archive_missing=True,
        )
        manual = sess.get(SkillPlaybookCard, "manual_absent_card")
        generated = sess.get(SkillPlaybookCard, "generated_absent_card")

    assert default_result.archived == 0
    assert archive_result.archived == 1
    assert manual is not None
    assert manual.status == "archived"
    assert generated is not None
    assert generated.status == "active"


def test_import_skill_playbooks_script_uses_default_archive_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.scripts import import_skill_playbooks

    calls: dict[str, object] = {}
    settings = SimpleNamespace(knowledge_dir=tmp_path / "knowledge")

    monkeypatch.setattr(import_skill_playbooks, "get_settings", lambda: settings)
    monkeypatch.setattr(
        import_skill_playbooks,
        "init_db",
        lambda: calls.setdefault("init_db", True),
    )

    @contextmanager
    def fake_get_session():
        yield "session"

    def fake_import(skill_dir, *, session, archive_missing):
        calls["skill_dir"] = skill_dir
        calls["session"] = session
        calls["archive_missing"] = archive_missing
        return SimpleNamespace(
            imported=1,
            updated=0,
            unchanged=0,
            archived=0,
            skipped=1,
        )

    monkeypatch.setattr(import_skill_playbooks, "get_session", fake_get_session)
    monkeypatch.setattr(
        import_skill_playbooks,
        "import_skill_playbook_dir",
        fake_import,
    )

    import_skill_playbooks.main()

    assert calls["init_db"] is True
    assert calls["skill_dir"] == tmp_path / "knowledge" / "skills"
    assert calls["session"] == "session"
    assert calls["archive_missing"] is False


def test_import_skill_playbooks_script_forwards_archive_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.scripts import import_skill_playbooks

    calls: dict[str, object] = {}
    settings = SimpleNamespace(knowledge_dir=tmp_path / "knowledge")

    monkeypatch.setattr(import_skill_playbooks, "get_settings", lambda: settings)
    monkeypatch.setattr(import_skill_playbooks, "init_db", lambda: None)

    @contextmanager
    def fake_get_session():
        yield "session"

    def fake_import(skill_dir, *, session, archive_missing):
        calls["archive_missing"] = archive_missing
        return SimpleNamespace(
            imported=0,
            updated=0,
            unchanged=1,
            archived=0,
            skipped=1,
        )

    monkeypatch.setattr(import_skill_playbooks, "get_session", fake_get_session)
    monkeypatch.setattr(
        import_skill_playbooks,
        "import_skill_playbook_dir",
        fake_import,
    )

    import_skill_playbooks.main(archive_missing=True)

    assert calls["archive_missing"] is True
