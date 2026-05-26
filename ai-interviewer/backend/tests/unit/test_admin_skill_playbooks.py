from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.v1 import admin as admin_api
from app.models.base import Base
from app.models.skill_playbook import SkillPlaybookCard


def _session_factory():
    engine = create_engine(
        "sqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_local = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    with session_local() as sess:
        sess.add_all(
            [
                _card(
                    "tech_incident_probe",
                    name="Tech Incident Probe",
                    priority=8,
                    status="active",
                    direction_tags=["internet_tech"],
                    role_tags=["java_backend", "sre"],
                    dimensions=["problem_solving", "technical_depth"],
                ),
                _card(
                    "business_metric_probe",
                    name="Business Metric Probe",
                    priority=6,
                    status="draft",
                    direction_tags=["business"],
                    role_tags=["product_manager"],
                    dimensions=["metrics_thinking"],
                ),
                _card(
                    "universal_evidence_probe",
                    name="Universal Evidence Probe",
                    priority=5,
                    status="active",
                    direction_tags=[],
                    role_tags=[],
                    dimensions=[],
                ),
            ]
        )
        sess.commit()
    return session_local


def _card(
    card_id: str,
    *,
    name: str,
    priority: int,
    status: str,
    direction_tags: list[str],
    role_tags: list[str],
    dimensions: list[str],
) -> SkillPlaybookCard:
    return SkillPlaybookCard(
        id=card_id,
        name=name,
        description=f"{name} description.",
        display_name_zh=f"{name} 中文名",
        display_description_zh=f"{name} 中文描述。",
        body_markdown=f"{name} full body.\nSecond line.",
        status=status,
        priority=priority,
        direction_tags=direction_tags,
        role_tags=role_tags,
        dimensions=dimensions,
        job_levels=["mid", "senior"],
        probe_intents=["debugging_probe"],
        failure_categories=["missing_evidence"],
        generator_moves=["Ask for concrete evidence."],
        watch_for=["Names source, owner, and result."],
        avoid=["Accepting vague best practice claims."],
        evaluator_rubric_hints=["Credit specific before/after evidence."],
        positive_signals=["Concrete action and measurable result."],
        negative_signals=["Generic story with no owner."],
        score_bias_rules=["Soft positive for named metric."],
        evaluator_visibility=True,
        source="manual_markdown",
        version=1,
        content_hash=f"sha1:{card_id}",
    )


def _client(
    session_factory,
    *,
    knowledge_dir: Path | None = None,
    api_token: str | None = None,
    allow_open_admin: bool = True,
) -> TestClient:
    app = FastAPI()
    app.include_router(admin_api.router)
    app.include_router(admin_api.api_v1_router)

    @contextmanager
    def get_session():
        with session_factory() as sess:
            yield sess
            sess.commit()

    admin_api.get_settings = lambda: SimpleNamespace(
        app_env="dev",
        api_token=api_token,
        allow_open_admin=allow_open_admin,
        knowledge_dir=knowledge_dir or Path("knowledge"),
        skill_playbook_backend="db_with_file_fallback",
    )
    admin_api.get_session = get_session
    return TestClient(app)


def test_admin_skill_playbooks_list_sorts_and_summarizes() -> None:
    session_local = _session_factory()
    client = _client(session_local)

    response = client.get("/admin/skill-playbooks")

    assert response.status_code == 200
    body = response.json()
    assert body["runtime_backend"] == "db_with_file_fallback"
    assert body["count"] == 3
    assert body["active_count"] == 2
    assert body["status_counts"] == {"active": 2, "draft": 1}
    assert [row["id"] for row in body["skill_playbooks"]] == [
        "tech_incident_probe",
        "universal_evidence_probe",
        "business_metric_probe",
    ]
    first = body["skill_playbooks"][0]
    assert first["display_name_zh"] == "Tech Incident Probe 中文名"
    assert first["display_description_zh"] == "Tech Incident Probe 中文描述。"
    assert first["body_preview"] == "Tech Incident Probe full body. Second line."
    assert "body_markdown" not in first
    assert first["direction_tags"] == ["internet_tech"]
    assert first["role_tags"] == ["java_backend", "sre"]
    assert first["tags"] == {
        "direction_tags": ["internet_tech"],
        "role_tags": ["java_backend", "sre"],
        "probe_intents": ["debugging_probe"],
        "failure_categories": ["missing_evidence"],
    }
    assert first["generator_moves"] == ["Ask for concrete evidence."]
    assert first["watch_for"] == ["Names source, owner, and result."]
    assert first["avoid"] == ["Accepting vague best practice claims."]
    assert first["evaluator_rubric_hints"] == [
        "Credit specific before/after evidence."
    ]
    assert first["positive_signals"] == ["Concrete action and measurable result."]
    assert first["negative_signals"] == ["Generic story with no owner."]
    assert first["score_bias_rules"] == ["Soft positive for named metric."]
    assert first["evaluator_visibility"] is True


def test_admin_skill_playbooks_filters_by_status_role_direction_and_dimension() -> None:
    session_local = _session_factory()
    client = _client(session_local)

    response = client.get(
        "/admin/skill-playbooks"
        "?status=active&direction_tag=internet_tech&role_tag=sre&dimension=problem_solving"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    assert body["skill_playbooks"][0]["id"] == "tech_incident_probe"

    empty = client.get("/admin/skill-playbooks?role_tag=frontend_web")
    assert empty.status_code == 200
    assert empty.json()["count"] == 0


def test_admin_skill_playbook_detail_returns_full_body_and_404() -> None:
    session_local = _session_factory()
    client = _client(session_local)

    response = client.get("/admin/skill-playbooks/tech_incident_probe")

    assert response.status_code == 200
    card = response.json()["skill_playbook"]
    assert card["id"] == "tech_incident_probe"
    assert card["display_name_zh"] == "Tech Incident Probe 中文名"
    assert card["display_description_zh"] == "Tech Incident Probe 中文描述。"
    assert card["body_markdown"] == "Tech Incident Probe full body.\nSecond line."
    assert card["generator_moves"] == ["Ask for concrete evidence."]
    assert card["evaluator_visibility"] is True

    missing = client.get("/admin/skill-playbooks/missing_card")
    assert missing.status_code == 404


def test_admin_skill_playbook_import_uses_markdown_source_of_truth(
    tmp_path: Path,
) -> None:
    knowledge_dir = tmp_path / "knowledge"
    skill_dir = knowledge_dir / "skills"
    skill_dir.mkdir(parents=True)
    (skill_dir / "demo.md").write_text(
        "\n".join(
            [
                "---",
                "id: demo_probe",
                "name: Demo Probe",
                "description: Demo description.",
                "display_name_zh: 演示追问卡",
                "display_description_zh: 演示中文描述。",
                "status: active",
                "priority: 4",
                "direction_tags: [internet_tech]",
                "role_tags: [java_backend]",
                "dimensions: [system_design]",
                "---",
                "",
                "Demo body.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (skill_dir / "SKILL.md").write_text("# Index\n", encoding="utf-8")
    session_local = _session_factory()
    client = _client(session_local, knowledge_dir=knowledge_dir)

    imported = client.post("/admin/skill-playbooks/import")

    assert imported.status_code == 200
    assert imported.json() == {
        "imported": 1,
        "updated": 0,
        "unchanged": 0,
        "archived": 0,
        "skipped": 1,
    }
    detail = client.get("/admin/skill-playbooks/demo_probe")
    assert detail.status_code == 200
    assert detail.json()["skill_playbook"]["name"] == "Demo Probe"
    assert detail.json()["skill_playbook"]["display_name_zh"] == "演示追问卡"
    assert detail.json()["skill_playbook"]["display_description_zh"] == "演示中文描述。"


def test_admin_skill_playbook_import_forwards_archive_missing(
    tmp_path: Path,
) -> None:
    knowledge_dir = tmp_path / "knowledge"
    skill_dir = knowledge_dir / "skills"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("# Index\n", encoding="utf-8")
    session_local = _session_factory()
    client = _client(session_local, knowledge_dir=knowledge_dir)

    imported = client.post("/admin/skill-playbooks/import?archive_missing=true")

    assert imported.status_code == 200
    assert imported.json()["archived"] == 3
    with session_local() as sess:
        rows = list(sess.scalars(select(SkillPlaybookCard)))
    assert {row.status for row in rows} == {"archived"}


def test_admin_skill_playbook_import_returns_strict_errors(
    tmp_path: Path,
) -> None:
    knowledge_dir = tmp_path / "knowledge"
    skill_dir = knowledge_dir / "skills"
    skill_dir.mkdir(parents=True)
    (skill_dir / "broken.md").write_text("no frontmatter\n", encoding="utf-8")
    session_local = _session_factory()
    client = _client(session_local, knowledge_dir=knowledge_dir)

    response = client.post("/admin/skill-playbooks/import")

    assert response.status_code == 422
    assert "missing frontmatter" in "\n".join(response.json()["detail"]["errors"])


def test_admin_skill_playbooks_requires_admin_auth() -> None:
    session_local = _session_factory()
    client = _client(session_local, api_token="secret", allow_open_admin=False)

    response = client.get("/admin/skill-playbooks")

    assert response.status_code == 401
