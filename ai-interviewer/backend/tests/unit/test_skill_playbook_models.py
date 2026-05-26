from __future__ import annotations

from sqlalchemy import create_engine, inspect, select, text
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
                display_name_zh="生产事故追问卡",
                display_description_zh="引导事故回答覆盖发现信号、缓解动作、根因和预防措施。",
                body_markdown="Ask for detection signal, mitigation, root cause, and prevention.",
                status="active",
                priority=7,
                direction_tags=["internet_tech"],
                role_tags=["java_backend", "sre"],
                dimensions=["problem_solving", "technical_depth"],
                job_levels=["mid", "senior"],
                probe_intents=["debugging_probe", "escalation_probe"],
                failure_categories=["root_cause_missing", "poor_communication"],
                generator_moves=["Ask for detection signal and first mitigation."],
                watch_for=["Distinguishes mitigation from root-cause fix."],
                avoid=["Accepting generic monitoring claims."],
                evaluator_rubric_hints=["Credit concrete blast radius evidence."],
                positive_signals=["Names metric, owner, rollback, and prevention."],
                negative_signals=["Jumps to solution without diagnosis."],
                score_bias_rules=["Soft-positive when prevention is measurable."],
                evaluator_visibility=True,
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
    assert row.display_name_zh == "生产事故追问卡"
    assert row.display_description_zh == "引导事故回答覆盖发现信号、缓解动作、根因和预防措施。"
    assert "detection signal" in row.body_markdown
    assert row.status == "active"
    assert row.priority == 7
    assert row.direction_tags == ["internet_tech"]
    assert row.role_tags == ["java_backend", "sre"]
    assert row.dimensions == ["problem_solving", "technical_depth"]
    assert row.job_levels == ["mid", "senior"]
    assert row.probe_intents == ["debugging_probe", "escalation_probe"]
    assert row.failure_categories == ["root_cause_missing", "poor_communication"]
    assert row.generator_moves == ["Ask for detection signal and first mitigation."]
    assert row.watch_for == ["Distinguishes mitigation from root-cause fix."]
    assert row.avoid == ["Accepting generic monitoring claims."]
    assert row.evaluator_rubric_hints == ["Credit concrete blast radius evidence."]
    assert row.positive_signals == ["Names metric, owner, rollback, and prevention."]
    assert row.negative_signals == ["Jumps to solution without diagnosis."]
    assert row.score_bias_rules == ["Soft-positive when prevention is measurable."]
    assert row.evaluator_visibility is True
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
    assert row.display_name_zh == ""
    assert row.display_description_zh == ""
    assert row.priority == 0
    assert row.direction_tags == []
    assert row.role_tags == []
    assert row.dimensions == []
    assert row.job_levels == []
    assert row.probe_intents == []
    assert row.failure_categories == []
    assert row.generator_moves == []
    assert row.watch_for == []
    assert row.avoid == []
    assert row.evaluator_rubric_hints == []
    assert row.positive_signals == []
    assert row.negative_signals == []
    assert row.score_bias_rules == []
    assert row.evaluator_visibility is False
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
    assert "display_name_zh VARCHAR(200) NOT NULL" in ddl
    assert "display_description_zh VARCHAR(512) NOT NULL" in ddl
    assert "body_markdown TEXT NOT NULL" in ddl
    assert "direction_tags JSON NOT NULL" in ddl
    assert "role_tags JSON NOT NULL" in ddl
    assert "dimensions JSON NOT NULL" in ddl
    assert "job_levels JSON NOT NULL" in ddl
    assert "probe_intents JSON NOT NULL" in ddl
    assert "failure_categories JSON NOT NULL" in ddl
    assert "generator_moves JSON NOT NULL" in ddl
    assert "watch_for JSON NOT NULL" in ddl
    assert "avoid JSON NOT NULL" in ddl
    assert "evaluator_rubric_hints JSON NOT NULL" in ddl
    assert "positive_signals JSON NOT NULL" in ddl
    assert "negative_signals JSON NOT NULL" in ddl
    assert "score_bias_rules JSON NOT NULL" in ddl
    assert "evaluator_visibility BOOLEAN NOT NULL" in ddl
    assert "PRIMARY KEY (id)" in ddl


def test_schema_upgrade_adds_playbook_quality_columns_to_legacy_sqlite() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE skill_playbook_cards (
                    id VARCHAR(160) PRIMARY KEY,
                    name VARCHAR(200),
                    description VARCHAR(512),
                    body_markdown TEXT,
                    status VARCHAR(32),
                    priority INTEGER,
                    direction_tags JSON,
                    role_tags JSON,
                    dimensions JSON,
                    job_levels JSON,
                    probe_intents JSON,
                    failure_categories JSON,
                    source VARCHAR(64),
                    version INTEGER,
                    content_hash VARCHAR(128),
                    created_at DATETIME,
                    updated_at DATETIME
                )
                """
            )
        )

    base_mod._upgrade_schema(engine)

    cols = {col["name"] for col in inspect(engine).get_columns("skill_playbook_cards")}
    assert {
        "display_name_zh",
        "display_description_zh",
        "generator_moves",
        "watch_for",
        "avoid",
        "evaluator_rubric_hints",
        "positive_signals",
        "negative_signals",
        "score_bias_rules",
        "evaluator_visibility",
    } <= cols
