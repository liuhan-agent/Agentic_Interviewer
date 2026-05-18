from __future__ import annotations

from sqlalchemy import create_engine, inspect, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import sessionmaker
from sqlalchemy.schema import CreateTable

from app.models import base as base_mod
from app.models.base import Base
from app.models.skill_playbook import SkillPlaybookCard


def _session_factory():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False, autoflush=False), engine


def test_skill_playbook_card_round_trips_structured_metadata() -> None:
    session_factory, _engine = _session_factory()
    with session_factory() as sess:
        sess.add(
            SkillPlaybookCard(
                id="tech_production_incident_probe",
                name="Production Incident Probe",
                description="Drive incident answers toward root cause and prevention.",
                body_markdown="Ask for detection signal, mitigation, root cause, and prevention.",
                status="active",
                priority=7,
                direction_tags=["internet_tech"],
                role_tags=["java_backend", "sre"],
                dimensions=["problem_solving", "technical_depth"],
                job_levels=["mid", "senior"],
                probe_intents=["debugging_probe", "escalation_probe"],
                failure_categories=["root_cause_missing", "poor_communication"],
                source="manual_markdown",
                version=2,
                content_hash="sha1:abc123",
            )
        )
        sess.commit()

        row = sess.scalar(
            select(SkillPlaybookCard).where(
                SkillPlaybookCard.id == "tech_production_incident_probe"
            )
        )

    assert row is not None
    assert row.name == "Production Incident Probe"
    assert row.description.startswith("Drive incident")
    assert "detection signal" in row.body_markdown
    assert row.status == "active"
    assert row.priority == 7
    assert row.direction_tags == ["internet_tech"]
    assert row.role_tags == ["java_backend", "sre"]
    assert row.dimensions == ["problem_solving", "technical_depth"]
    assert row.job_levels == ["mid", "senior"]
    assert row.probe_intents == ["debugging_probe", "escalation_probe"]
    assert row.failure_categories == ["root_cause_missing", "poor_communication"]
    assert row.source == "manual_markdown"
    assert row.version == 2
    assert row.content_hash == "sha1:abc123"
    assert row.created_at is not None
    assert row.updated_at is not None


def test_skill_playbook_card_defaults() -> None:
    session_factory, _engine = _session_factory()
    with session_factory() as sess:
        sess.add(
            SkillPlaybookCard(
                id="universal_concrete_evidence_probe",
                name="Concrete Evidence Probe",
                description="",
                body_markdown="Ask for one concrete example.",
            )
        )
        sess.commit()

        row = sess.scalar(select(SkillPlaybookCard))

    assert row is not None
    assert row.status == "active"
    assert row.priority == 0
    assert row.direction_tags == []
    assert row.role_tags == []
    assert row.dimensions == []
    assert row.job_levels == []
    assert row.probe_intents == []
    assert row.failure_categories == []
    assert row.source == "manual_markdown"
    assert row.version == 1
    assert row.content_hash is None


def test_skill_playbook_table_created_by_base_metadata() -> None:
    _, engine = _session_factory()

    tables = set(inspect(engine).get_table_names())

    assert "skill_playbook_cards" in tables


def test_init_db_creates_skill_playbook_table(monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    monkeypatch.setattr(base_mod, "get_engine", lambda: engine)

    base_mod.init_db()

    assert "skill_playbook_cards" in set(inspect(engine).get_table_names())


def test_skill_playbook_postgres_ddl_shape() -> None:
    ddl = str(
        CreateTable(SkillPlaybookCard.__table__).compile(
            dialect=postgresql.dialect()
        )
    )

    assert "skill_playbook_cards" in ddl
    assert "id VARCHAR(160) NOT NULL" in ddl
    assert "body_markdown TEXT NOT NULL" in ddl
    assert "direction_tags JSON NOT NULL" in ddl
    assert "role_tags JSON NOT NULL" in ddl
    assert "dimensions JSON NOT NULL" in ddl
    assert "job_levels JSON NOT NULL" in ddl
    assert "probe_intents JSON NOT NULL" in ddl
    assert "failure_categories JSON NOT NULL" in ddl
    assert "PRIMARY KEY (id)" in ddl
