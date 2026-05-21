# Interview Directions / Job Templates DB Registry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move `interview_directions.json` and its derived job-template behavior into a DB-backed registry, without changing interview behavior, reward keys, strategy memory keys, or director dimension routing.

**Architecture:** Keep the current `InterviewDirection` / `DimensionCatalogItem` service contract stable, add a DB registry behind it, and ship through a staged `file -> db_with_file_fallback -> db` rollout. Treat job templates as a projection of the direction registry in the first cut; do not revive `job_templates.json` as a second runtime source.

**Tech Stack:** FastAPI, SQLAlchemy ORM, SQLite fallback, Postgres, Pydantic settings, pytest, frontend TypeScript source tests.

---

## Background

This plan is intentionally **not recommended as the next immediate task**. It should be executed after the setup/product shape is stable, because `interview_directions` is not ordinary copy: it defines the role catalog, dimension catalog, default skills, JD template text, and per-direction RAG alpha. Those fields are read by setup, JD parsing, dimension labels, question-bank alignment, skill playbook selection, RAG fallback, reward attribution, and strategy memory keys.

Current source map:

- `ai-interviewer/backend/knowledge/interview_directions.json`
  - Current runtime source of truth for interview directions.
  - Contains `industry`, `direction`, `label`, `default_title`, `default_level`, `skills`, `template`, optional `retrieval.alpha`, and `dimension_catalog`.
- `ai-interviewer/backend/knowledge/job_templates.json`
  - Deprecated; current application code no longer reads it.
  - Keep excluded from RAG and do not reintroduce as an active source.
- `ai-interviewer/backend/app/services/job_directions.py`
  - Parses the JSON file into `InterviewDirection`.
  - Exposes `list_interview_directions()`, `get_interview_direction()`, `all_dimension_options()`, `dimension_label()`.
- `ai-interviewer/backend/app/services/job_templates.py`
  - Derives `JobTemplate` from `InterviewDirection.template`.
  - This is a projection, not a separate content source.
- `ai-interviewer/backend/app/services/interview_setup.py`
  - Builds `/directions`, `/dimensions`, and `/job-template` API payloads.
- `ai-interviewer/backend/app/services/jd_parser.py`
  - Uses direction catalog to constrain rubric dimensions and prompt the JD parser.
- `ai-interviewer/backend/app/engine/workflow/nodes/ask_question.py`
  - Reads direction `retrieval_alpha` for hybrid RAG.
- `ai-interviewer/backend/app/engine/workflow/policy_context.py`
  - Builds reward/strategy context keys using direction and dimension IDs.
- `ai-interviewer/backend/app/services/question_seed_lint.py` and question-bank tests
  - Treat direction dimension catalogs as the allowed alignment surface.
- `ai-interviewer/frontend/src/lib/api/types.ts`
  - Defines frontend shape for `InterviewDirection` and `JobTemplateResponse`.
- `ai-interviewer/frontend/src/lib/api/interview.ts`
  - Calls `/api/v1/interview/directions`, `/dimensions`, and `/job-template`.

## Core Decision

Use one DB registry table for the current direction JSON shape:

- `InterviewDirectionRegistry` owns the canonical `template` field.
- `JobTemplateResponse` remains derived from `InterviewDirectionRegistry.template`.
- Do not create a separate `job_template_registry` table in the first implementation.
- Add a separate template table only after the product explicitly needs level-specific, org-specific, or A/B-test templates.

This keeps the first migration close to today’s data model and avoids divergence between “direction dimensions” and “job template dimensions.”

## Boundaries

In scope:

- DB model for direction registry.
- Strict import from `knowledge/interview_directions.json`.
- Runtime service backend switch: `file`, `db`, `db_with_file_fallback`.
- Admin observation/import/parity endpoints.
- Deployment docs and rollback switches.
- Tests proving API payload parity and key stability.

Out of scope:

- Full Admin CRUD/config-center editing.
- Org-specific or tenant-specific direction catalogs.
- Level-specific template variants.
- New direction IDs or dimension IDs.
- Reward key migration.
- Strategy memory key migration.
- Director routing changes.
- Question-bank content changes.
- Runtime auto-import during app startup.
- Reintroducing `job_templates.json` as active runtime input.

## Risk Points

- Direction IDs are part of reward and strategy-memory context keys, e.g. `java_backend:senior:technical_depth`. Renaming a direction silently forks history.
- Dimension IDs are part of evaluator, final report, reward, strategy memory, question-bank alignment, and UI labels. Renaming a dimension is a data migration, not a content edit.
- Missing or malformed `dimension_catalog` can break JD parsing and director selection quality.
- DB-backed registry can drift from file-backed registry if imports are partial or non-transactional.
- Admin edits without lint can create invalid catalogs that still “look fine” in setup UI.
- Startup auto-import would create hidden content writes and make deployment behavior harder to reason about.
- If DB has active directions but a specific direction is missing, fallback policy must be explicit; otherwise production can hide bad imports.
- `db` mode must fail closed on database errors. Returning `[]` from a broken DB backend would make `/directions` look healthy while setup, JD parsing, question selection, and RAG alpha are actually degraded.
- File order is observable behavior. `list_interview_directions()` currently preserves JSON order, and `all_dimension_options()` deduplicates dimension labels by first occurrence; DB mode must preserve that order with an explicit `display_order`.
- Cache invalidation is part of the rollout contract. File and DB loaders must be clearable in tests, and Admin import must clear runtime catalog caches after a successful import.
- `frontend` is intentionally mapped to question-bank role tag `frontend_web`; other direction IDs mostly map to same-named role tags. Registry migration must not change this selector behavior.

## Data Model

Create `ai-interviewer/backend/app/models/interview_catalog.py`:

```python
class InterviewDirectionRegistry(Base):
    __tablename__ = "interview_direction_registry"

    direction: Mapped[str] = mapped_column(String(96), primary_key=True)
    industry: Mapped[str] = mapped_column(String(64), index=True)
    label: Mapped[str] = mapped_column(String(160))
    default_title: Mapped[str] = mapped_column(String(200))
    default_level: Mapped[str] = mapped_column(String(32), default="mid", index=True)
    skills: Mapped[list] = mapped_column(JSON, default=list)
    template: Mapped[str] = mapped_column(Text, default="")
    dimension_catalog: Mapped[list] = mapped_column(JSON, default=list)
    retrieval_alpha: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    priority: Mapped[int] = mapped_column(Integer, default=0, index=True)
    display_order: Mapped[int] = mapped_column(Integer, default=0, index=True)
    source: Mapped[str] = mapped_column(String(64), default="manual_json", index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    content_hash: Mapped[str | None] = mapped_column(String(128), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC))
```

Notes:

- Keep `dimension_catalog` JSON-shaped in P0 to preserve the existing API payload exactly.
- Do not normalize dimensions into a child table in the first cut.
- `status=active` is required for runtime selection.
- `display_order` preserves the current file order exactly. Runtime list order is `display_order asc`, then `direction asc`.
- `priority` is reserved for a later product ordering feature and must not replace file-order parity in this migration.
- `content_hash` uses each direction record’s canonical JSON, not the entire file, so single-row versioning is stable.

## Settings

Add to `ai-interviewer/backend/app/core/settings.py`:

```python
interview_catalog_backend: Literal["file", "db", "db_with_file_fallback"] = "file"
```

Rollout rule:

- Keep default `file` during model/import/Admin tasks.
- Flip default to `db_with_file_fallback` only in the final runtime-switch task.
- Preserve `file` as the fastest rollback switch.

Add `interview_catalog_backend` to `ai-interviewer/backend/app/core/deployment_preflight.py`.

## Task 0: Golden Parity Tests Before Any Runtime Change

**Files:**

- Modify: `ai-interviewer/backend/tests/unit/test_jd_parser.py`
- Modify: `ai-interviewer/backend/tests/unit/test_interview_setup_api_contract.py`
- Create: `ai-interviewer/backend/tests/unit/test_interview_catalog_parity.py`

- [ ] Add helpers in `test_interview_catalog_parity.py` that capture the full file-backed baseline.

```python
def _directions_by_id(payload):
    return {row["direction"]: row for row in payload["directions"]}


def test_file_backed_catalog_has_expected_current_size_and_order(client):
    response = client.get("/api/v1/interview/directions")
    assert response.status_code == 200
    directions = response.json()["directions"]
    assert len(directions) == 15
    assert [row["direction"] for row in directions][:3] == [
        "java_backend",
        "frontend",
        "ai_fullstack",
    ]
```

- [ ] Add a file-backed golden test for `/api/v1/interview/directions`.

```python
def test_file_backed_directions_payload_has_stable_contract(client):
    response = client.get("/api/v1/interview/directions")
    assert response.status_code == 200
    body = response.json()
    java = {d["direction"]: d for d in body["directions"]}["java_backend"]
    assert {"industry", "direction", "label", "default_title", "default_level", "skills", "dimension_catalog", "rubric_dimensions", "retrieval_alpha"} <= set(java)
    assert java["rubric_dimensions"] == [d["id"] for d in java["dimension_catalog"]]
    assert java["retrieval_alpha"] == 0.5
```

- [ ] Add a file-backed golden test for `/api/v1/interview/job-template`.

```python
def test_file_backed_job_template_is_derived_from_direction(client):
    response = client.get("/api/v1/interview/job-template", params={"direction": "java_backend", "level": "junior"})
    assert response.status_code == 200
    body = response.json()
    assert body["direction"] == "java_backend"
    assert body["level"] == "junior"
    assert body["template"].strip()
    assert body["rubric_dimensions"]
```

- [ ] Add a key-stability test for reward/strategy context keys.

```python
def test_direction_policy_context_keys_stay_stable():
    from app.engine.workflow.policy_context import policy_context_keys

    keys = policy_context_keys(
        {"interview_direction": "java_backend", "level": "senior"},
        "technical_depth",
    )

    assert keys == [
        "java_backend:senior:technical_depth",
        "senior:technical_depth",
    ]
```

- [ ] Run the golden tests.

```bash
cd D:\Agent\Agentic_Interviewer\ai-interviewer\backend
python -m pytest tests/unit/test_jd_parser.py tests/unit/test_interview_setup_api_contract.py -q
```

Expected: existing behavior passes before migration starts.

- [ ] Commit.

```bash
git add ai-interviewer/backend/tests/unit/test_jd_parser.py ai-interviewer/backend/tests/unit/test_interview_setup_api_contract.py ai-interviewer/backend/tests/unit/test_interview_catalog_parity.py
git commit -m "test: pin interview catalog file-backed contract"
```

## Task 1: DB Model And Schema Initialization

**Files:**

- Create: `ai-interviewer/backend/app/models/interview_catalog.py`
- Modify: `ai-interviewer/backend/app/models/__init__.py`
- Modify: `ai-interviewer/backend/app/models/base.py`
- Create: `ai-interviewer/backend/tests/unit/test_interview_catalog_models.py`

- [ ] Write a model round-trip test using SQLite in-memory.

```python
def test_interview_direction_registry_round_trips_catalog():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    with Session() as sess:
        sess.add(InterviewDirectionRegistry(
            direction="java_backend",
            industry="internet",
            label="Java 后端开发",
            default_title="Java 后端开发工程师",
            default_level="senior",
            skills=["java", "spring"],
            template="岗位职责...",
            dimension_catalog=[{"id": "technical_depth", "label": "技术深度", "description": "基础", "triggers": ["java"]}],
            retrieval_alpha=0.5,
            display_order=0,
            content_hash="sha256:abc",
        ))
        sess.commit()
        row = sess.get(InterviewDirectionRegistry, "java_backend")
    assert row is not None
    assert row.dimension_catalog[0]["id"] == "technical_depth"
    assert row.status == "active"
    assert row.source == "manual_json"
    assert row.version == 1
    assert row.display_order == 0
```

- [ ] Implement `InterviewDirectionRegistry` using the model shape in the Data Model section.

- [ ] Export `InterviewDirectionRegistry` from `app/models/__init__.py`.

- [ ] Ensure `init_db()` imports `app.models.interview_catalog` before `Base.metadata.create_all(engine)`.

- [ ] Add schema-upgrade coverage for existing DBs only if the project needs to add `display_order` to an already-created `interview_direction_registry` table during development.

If the table is brand new in all deployed environments, `Base.metadata.create_all(engine)` is enough for the first release. If a local/dev DB might already have the table from an earlier branch, add `display_order`, `priority`, `content_hash`, and timestamp columns to `_SQLITE_UPGRADES` / `_POSTGRES_UPGRADES` with the same additive-column pattern used by existing tables.

- [ ] Run model/schema tests.

```bash
python -m pytest tests/unit/test_interview_catalog_models.py tests/unit/test_schema_upgrade.py -q
```

Expected: all tests pass.

- [ ] Commit.

```bash
git add ai-interviewer/backend/app/models/interview_catalog.py ai-interviewer/backend/app/models/__init__.py ai-interviewer/backend/app/models/base.py ai-interviewer/backend/tests/unit/test_interview_catalog_models.py
git commit -m "feat: add interview catalog registry model"
```

## Task 2: Strict JSON Import Service And CLI

**Files:**

- Create: `ai-interviewer/backend/app/services/interview_catalog_import.py`
- Create: `ai-interviewer/backend/app/scripts/import_interview_catalog.py`
- Create: `ai-interviewer/backend/tests/unit/test_interview_catalog_import.py`

- [ ] Create strict parser tests.

Validation rules:

- Root must be a list.
- Each row must include `industry`, `direction`, `label`, `default_title`, `default_level`, `skills`, `template`, `dimension_catalog`.
- `direction` must be a stable slug: lowercase letters, numbers, and underscores.
- `default_level` must be one of `junior`, `mid`, `senior`, `staff`, `principal`.
- `skills` must be a non-empty list of strings.
- `dimension_catalog` must be a non-empty list.
- Each dimension must include `id`, `label`, `description`, `triggers`.
- Dimension `id` must be a stable slug.
- `triggers` must be a non-empty list of strings.
- Duplicate direction IDs fail the whole import.
- Duplicate dimension IDs inside a direction fail the whole import.
- `retrieval.alpha`, when present, must be numeric and between `0` and `1`.
- Failure reports all errors before writing DB rows.

- [ ] Add canonical hash tests.

```python
def test_direction_content_hash_ignores_input_key_order():
    from app.services.interview_catalog_import import direction_content_hash

    left = {"direction": "java_backend", "skills": ["java"], "template": "x"}
    right = {"template": "x", "skills": ["java"], "direction": "java_backend"}

    assert direction_content_hash(left) == direction_content_hash(right)
    assert direction_content_hash(left).startswith("sha256:")
```

- [ ] Implement `parse_interview_directions_file(path: Path)`.

Return parsed values in the same shape accepted by `InterviewDirectionRegistry`.
Each parsed record must include `display_order` from the JSON list index and `content_hash` from a shared `direction_content_hash(record)` helper.

- [ ] Implement `import_interview_directions(path, session, archive_missing=False)`.

Write behavior:

- Parse and validate the full file first.
- Upsert rows in one transaction.
- Do not call `session.commit()` inside the service. The caller owns transaction commit through `get_session()` or an explicit test session.
- New row: `version=1`.
- Existing row with same `content_hash`: count as `unchanged`.
- Existing row with changed hash: update fields and increment `version`.
- Existing row with only `display_order` changed: update `display_order` and count as `updated` without changing content fields.
- `archive_missing=False`: leave extra DB rows unchanged.
- `archive_missing=True`: mark absent `source="manual_json"` rows as `archived`.

- [ ] Implement CLI.

```bash
python -m app.scripts.import_interview_catalog
python -m app.scripts.import_interview_catalog --archive-missing
```

CLI behavior:

- Calls `init_db()`.
- Reads `get_settings().knowledge_dir / "interview_directions.json"`.
- Prints `imported`, `updated`, `unchanged`, `archived`.
- Returns non-zero on strict validation failure.
- Catches `InterviewCatalogImportError`, prints every validation error, and exits with `SystemExit(1)`.

- [ ] Run import tests.

```bash
python -m pytest tests/unit/test_interview_catalog_import.py tests/unit/test_interview_catalog_models.py -q
```

Expected: valid bundled catalog imports; invalid shapes fail atomically.

- [ ] Commit.

```bash
git add ai-interviewer/backend/app/services/interview_catalog_import.py ai-interviewer/backend/app/scripts/import_interview_catalog.py ai-interviewer/backend/tests/unit/test_interview_catalog_import.py
git commit -m "feat: import interview catalog registry"
```

## Task 3: Service Backend With File / DB / Fallback Modes

**Files:**

- Modify: `ai-interviewer/backend/app/core/settings.py`
- Modify: `ai-interviewer/backend/app/core/deployment_preflight.py`
- Modify: `ai-interviewer/backend/app/services/job_directions.py`
- Modify: `ai-interviewer/backend/app/services/job_templates.py`
- Create: `ai-interviewer/backend/tests/unit/test_interview_catalog_backend.py`

- [ ] Add `interview_catalog_backend` setting, defaulting to `file`.

- [ ] Refactor `job_directions.py` into explicit private loaders:

```python
def _list_file_interview_directions() -> list[InterviewDirection]: ...
def _list_db_interview_directions() -> list[InterviewDirection]: ...
def _list_interview_directions_for_backend(backend: str | None = None) -> list[InterviewDirection]: ...
def clear_interview_catalog_cache_for_tests() -> None: ...
```

- [ ] Replace the module-level `_CATALOG_PATH` constant with a settings-backed path helper.

```python
def _catalog_path() -> Path:
    return Path(get_settings().knowledge_dir) / "interview_directions.json"
```

All file reads must go through `_catalog_path()` so tests and local imports can point `knowledge_dir` at temporary fixtures.

- [ ] Preserve the public API exactly:

```python
def list_interview_directions() -> list[InterviewDirection]: ...
def get_interview_direction(direction: str) -> InterviewDirection: ...
def all_dimension_options() -> list[dict[str, str]]: ...
def dimension_label(dim: str) -> str: ...
```

- [ ] Map `InterviewDirectionRegistry` rows into the existing `InterviewDirection` dataclass.

DB row mapping:

- `direction`, `industry`, `label`, `default_title`, `default_level`, `skills`, `template`, `retrieval_alpha` map directly.
- `dimension_catalog` JSON maps through `_parse_dimension`.
- Only `status="active"` rows participate.
- Sort active rows by `display_order asc`, then `direction asc`. Do not sort by `priority` in this migration.

- [ ] Implement fallback behavior.

Backend modes:

- `file`: read only `interview_directions.json`.
- `db`: read only active DB rows. DB exceptions must raise a catalog backend error; public setup API callers should surface this as 503 instead of returning an empty healthy-looking catalog.
- `db_with_file_fallback`: fallback to file only when DB query fails or active DB row count is `0`.
- Do not fallback when DB has active rows but one requested direction is missing. Missing direction must raise `InterviewDirectionNotFound`.

- [ ] Add backend failure tests.

Assertions:

- `db` mode with a DB exception raises the catalog backend error and does not read the file.
- `/api/v1/interview/directions` maps that error to 503 in `db` mode.
- `db_with_file_fallback` reads the file when DB query raises.
- `db_with_file_fallback` reads the file when active DB row count is `0`.
- `db_with_file_fallback` does not fallback for a missing direction when active DB rows exist.

- [ ] Add full file-vs-DB payload parity tests after importing the bundled JSON into an in-memory SQLite DB.

Assertions:

- `/directions` payload is identical in file mode and DB mode, including direction order, `dimension_catalog`, `rubric_dimensions`, and `retrieval_alpha`.
- `/dimensions` payload is identical in file mode and DB mode, including first-seen label order.
- `/job-template` payload is identical for every bundled direction and a representative level.

- [ ] Keep `job_templates.py` derived from `get_interview_direction(direction)`.

Do not read `job_templates.json`.

- [ ] Clear or replace the existing `@lru_cache(maxsize=1)` strategy.

Use separate cache keys for backend mode, or remove caching until a measured need appears. Tests must be able to clear DB/file cache deterministically.
Admin import must call the cache-clear helper after a successful import so operators can import and immediately verify parity without restarting the server.

- [ ] Run backend tests.

```bash
python -m pytest tests/unit/test_interview_catalog_backend.py tests/unit/test_jd_parser.py tests/unit/test_retriever_alpha.py tests/unit/test_interview_setup_api_contract.py -q
```

Expected: file mode preserves current API shape; DB mode returns equivalent payloads after import.

- [ ] Commit.

```bash
git add ai-interviewer/backend/app/core/settings.py ai-interviewer/backend/app/core/deployment_preflight.py ai-interviewer/backend/app/services/job_directions.py ai-interviewer/backend/app/services/job_templates.py ai-interviewer/backend/tests/unit/test_interview_catalog_backend.py
git commit -m "feat: support db-backed interview catalog"
```

## Task 4: Admin Observation And Parity Check

**Files:**

- Modify: `ai-interviewer/backend/app/api/v1/admin.py`
- Modify: `ai-interviewer/frontend/src/lib/api/admin.ts`
- Modify: `ai-interviewer/frontend/src/components/admin/AdminPanel.tsx`
- Create: `ai-interviewer/frontend/src/components/admin/InterviewCatalogCard.tsx`
- Modify: `ai-interviewer/frontend/src/lib/api/types.ts`
- Modify: `ai-interviewer/frontend/tests/adminObservabilitySource.test.js`
- Create: `ai-interviewer/backend/tests/unit/test_admin_interview_catalog.py`

- [ ] Add backend Admin endpoints.

Routes:

- `GET /admin/interview-directions`
- `GET /admin/interview-directions/{direction}`
- `POST /admin/interview-directions/import?archive_missing=false`
- `GET /admin/interview-directions/parity`

Auth:

- All routes use `require_admin_token`.

List payload:

```json
{
  "runtime_backend": "file",
  "count": 18,
  "active_count": 18,
  "status_counts": {"active": 18},
  "directions": [
    {
      "direction": "java_backend",
      "industry": "internet",
      "label": "Java 后端开发",
      "default_title": "Java 后端开发工程师",
      "default_level": "senior",
      "skills": ["java"],
      "rubric_dimensions": ["technical_depth"],
      "dimension_catalog": [{"id": "technical_depth", "label": "技术深度"}],
      "retrieval_alpha": 0.5,
      "status": "active",
      "source": "manual_json",
      "version": 1,
      "content_hash": "sha256:..."
    }
  ]
}
```

Parity payload:

```json
{
  "file_count": 18,
  "db_active_count": 18,
  "missing_in_db": [],
  "extra_in_db": [],
  "hash_mismatches": [],
  "dimension_mismatches": [],
  "order_mismatches": []
}
```

- [ ] Add frontend API client types and methods.

Also add `retrieval_alpha?: number | null` to `InterviewDirection` in `frontend/src/lib/api/types.ts` so public direction payloads, Admin payloads, and TypeScript source checks agree.

Methods:

- `getInterviewCatalogDirections(filters?)`
- `getInterviewCatalogDirection(direction)`
- `importInterviewCatalog(archiveMissing=false)`
- `getInterviewCatalogParity()`

- [ ] Add a lightweight AdminPanel card.

Implement the card in `InterviewCatalogCard.tsx`; keep `AdminPanel.tsx` limited to fetching state and rendering the new component, matching the existing Question Bank / Skills Playbook observation pattern without making `AdminPanel.tsx` larger than necessary.

Display:

- backend mode
- active count
- parity summary
- recent/listed directions
- detail body with template and dimension catalog
- import and import-with-archive buttons

Do not add CRUD controls in this task.
After import succeeds, refresh list/detail/parity and rely on the backend cache-clear hook from Task 3.

- [ ] Run backend and frontend tests.

```bash
python -m pytest tests/unit/test_admin_interview_catalog.py tests/unit/test_admin_auth.py -q
cd D:\Agent\Agentic_Interviewer\ai-interviewer\frontend
npm test -- tests/adminObservabilitySource.test.js
npm run typecheck
```

Expected: Admin routes require auth, import is manual, frontend observes but cannot edit.

- [ ] Commit.

```bash
git add ai-interviewer/backend/app/api/v1/admin.py ai-interviewer/backend/tests/unit/test_admin_interview_catalog.py ai-interviewer/frontend/src/lib/api/admin.ts ai-interviewer/frontend/src/lib/api/types.ts ai-interviewer/frontend/src/components/admin/AdminPanel.tsx ai-interviewer/frontend/src/components/admin/InterviewCatalogCard.tsx ai-interviewer/frontend/tests/adminObservabilitySource.test.js
git commit -m "feat: observe interview catalog registry in admin"
```

## Task 5: Runtime Switch And Workflow Regression

**Files:**

- Modify: `ai-interviewer/backend/app/core/settings.py`
- Modify: `ai-interviewer/backend/tests/unit/test_jd_parser.py`
- Modify: `ai-interviewer/backend/tests/unit/test_interview_setup_api_contract.py`
- Modify: `ai-interviewer/backend/tests/unit/test_retriever_alpha.py`
- Modify: `ai-interviewer/backend/tests/unit/test_question_seed_lint.py`
- Modify: `ai-interviewer/backend/tests/unit/test_ask_question_selection_artifacts.py`

- [ ] Flip default `interview_catalog_backend` to `db_with_file_fallback`.

- [ ] Add regression tests for setup APIs in DB mode.

Assertions:

- `/directions` returns active DB directions.
- `/dimensions` uses DB dimension catalog labels.
- `/job-template` derives from DB direction `template`.
- Unknown direction returns the same status as file mode.

- [ ] Add regression tests for JD parser.

Assertions:

- DB-backed `dimension_catalog` constrains LLM-selected dimensions.
- Invalid LLM dimensions are filtered out against DB catalog.
- Missing DB direction in `db` mode is rejected instead of falling back silently.

- [ ] Add regression tests for RAG alpha.

Assertions:

- `ask_question._resolve_direction_alpha()` reads DB `retrieval_alpha`.
- `rag_mode=vector` still skips the lookup.
- Missing `retrieval_alpha` falls back to global retriever default.

- [ ] Add question-bank lint regression.

Assertions:

- Lint reads the DB-backed catalog when backend is DB.
- Direction/dimension alignment failures are still caught.
- Existing YAML question-bank strict lint passes after catalog import.

- [ ] Add structured-question role tag regression.

Assertions:

- `resolve_question_bank_tags(job_spec={"interview_direction": "frontend"})` still returns role tag `frontend_web`.
- `java_backend`, `sre`, `ai_agent`, `ai_fullstack`, `mobile`, `ai_algorithm`, and `architect` still map to same-named role tags.
- Business directions still map to `direction_tags=["business"]` and same-named role tags.

- [ ] Run focused workflow tests.

```bash
cd D:\Agent\Agentic_Interviewer\ai-interviewer\backend
python -m pytest tests/unit/test_jd_parser.py tests/unit/test_interview_setup_api_contract.py tests/unit/test_retriever_alpha.py tests/unit/test_question_seed_lint.py tests/unit/test_ask_question_selection_artifacts.py -q
```

Expected: DB-backed catalog is behaviorally equivalent after import.

- [ ] Commit.

```bash
git add ai-interviewer/backend/app/core/settings.py ai-interviewer/backend/tests/unit/test_jd_parser.py ai-interviewer/backend/tests/unit/test_interview_setup_api_contract.py ai-interviewer/backend/tests/unit/test_retriever_alpha.py ai-interviewer/backend/tests/unit/test_question_seed_lint.py ai-interviewer/backend/tests/unit/test_ask_question_selection_artifacts.py
git commit -m "feat: make interview catalog db-backed by default"
```

## Task 6: Deployment Docs And Operational Guardrails

**Files:**

- Modify: `ai-interviewer/backend/README.md`
- Modify: `ai-interviewer/docs/本地开发命令速查.md`
- Create: `ai-interviewer/backend/tests/unit/test_interview_catalog_deployment_docs.py`

- [ ] Document first deployment commands.

```bash
cd D:\Agent\Agentic_Interviewer\ai-interviewer\backend
python -m app.scripts.import_interview_catalog --archive-missing
python -m app.scripts.import_question_seeds --archive-missing
python -m app.scripts.import_skill_playbooks --archive-missing
```

- [ ] Document rollback switches.

```bash
INTERVIEW_CATALOG_BACKEND=file
QUESTION_SELECTOR_MODE=structured_shadow
SKILL_PLAYBOOK_BACKEND=file
```

- [ ] Document explicit non-auto-import policy.

Required sentence:

```text
Interview catalog, question seeds, and skill playbooks are explicit operator imports; backend startup must not import or mutate content.
```

- [ ] Add doc source test.

Assertions:

- README includes `python -m app.scripts.import_interview_catalog --archive-missing`.
- README includes `INTERVIEW_CATALOG_BACKEND=file`.
- README includes `INTERVIEW_CATALOG_BACKEND=db_with_file_fallback`.
- README states `INTERVIEW_CATALOG_BACKEND=db` fails closed on DB errors and is intended only after Admin parity is green.
- README says startup does not auto-import content.
- Local dev command guide includes Admin verification for Interview Catalog, Question Bank, and Skills Playbook.

- [ ] Run docs test.

```bash
python -m pytest tests/unit/test_interview_catalog_deployment_docs.py -q
```

Expected: docs contain the operational commands and rollback switches.

- [ ] Commit.

```bash
git add ai-interviewer/backend/README.md ai-interviewer/docs/本地开发命令速查.md ai-interviewer/backend/tests/unit/test_interview_catalog_deployment_docs.py
git commit -m "docs: document interview catalog registry deployment"
```

## Task 7: Final Regression And Rollout Checklist

**Files:**

- No new files expected.

- [ ] Run backend full unit tests.

```bash
cd D:\Agent\Agentic_Interviewer\ai-interviewer\backend
python -m pytest tests/unit -q
```

Expected: all tests pass.

- [ ] Run targeted lint.

```bash
python -m ruff check app/models/interview_catalog.py app/services/interview_catalog_import.py app/scripts/import_interview_catalog.py app/services/job_directions.py app/services/job_templates.py app/api/v1/admin.py tests/unit/test_interview_catalog_models.py tests/unit/test_interview_catalog_import.py tests/unit/test_interview_catalog_backend.py tests/unit/test_admin_interview_catalog.py
```

Expected: `All checks passed!`

- [ ] Run frontend source/type checks.

```bash
cd D:\Agent\Agentic_Interviewer\ai-interviewer\frontend
npm test -- tests/adminObservabilitySource.test.js
npm run typecheck
npm run lint
```

Expected: tests and typecheck pass; existing lint warnings may remain if unrelated.

- [ ] Run diff check.

```bash
cd D:\Agent\Agentic_Interviewer
git diff --check
```

Expected: no whitespace errors.

- [ ] Import into the target DB manually.

```bash
cd D:\Agent\Agentic_Interviewer\ai-interviewer\backend
python -m app.scripts.import_interview_catalog --archive-missing
```

Expected: import counters show active rows matching `interview_directions.json`.

- [ ] Verify Admin parity.

Open Admin and confirm:

- Interview Catalog active count is non-zero.
- `missing_in_db` is empty.
- `extra_in_db` is empty after `--archive-missing`.
- `hash_mismatches` is empty immediately after import.

- [ ] Commit any final test or doc adjustments.

```bash
git add .
git commit -m "test: harden interview catalog registry rollout"
```

## Future Config Center Phase

Do not implement this phase during the first registry migration. Keep it as a later product/config-center project.

When product shape is stable, add:

- Admin create/edit/archive direction forms.
- Field-level validation UI.
- Preview for `/directions`, `/dimensions`, `/job-template`, JD parser prompt catalog, and question-bank coverage.
- Draft/publish workflow.
- Version history and rollback.
- Optional `JobTemplateVariant` table for `direction + level + org_id` templates.
- Optional normalized `InterviewDimensionRegistry` table if product needs dimension-level editing across directions.

Config-center-specific risks:

- A UI edit can break reward/strategy continuity by renaming IDs.
- A template edit can make JD parsing worse while setup UI still looks normal.
- A dimension edit can desynchronize question-bank coverage.
- Admin CRUD needs a publish gate, not direct writes to active runtime config.

## Acceptance Criteria

This migration is complete only when:

- `interview_directions.json` imports strictly into DB.
- `job_templates.json` remains deprecated and unread.
- `/directions`, `/dimensions`, and `/job-template` payloads are equivalent in file and DB modes after import.
- DB mode preserves the existing JSON direction order through `display_order`.
- `INTERVIEW_CATALOG_BACKEND=db` fails closed on DB errors instead of returning an empty catalog.
- `INTERVIEW_CATALOG_BACKEND=db_with_file_fallback` falls back only for DB failure or zero active rows, not for per-direction misses.
- JD parser dimension filtering behaves the same in file and DB modes.
- RAG alpha lookup behaves the same in file and DB modes.
- Question-bank alignment lint still catches catalog mismatches.
- Structured-question role tag mapping remains stable, including `frontend -> frontend_web`.
- No app startup path writes catalog rows.
- Rollback to `INTERVIEW_CATALOG_BACKEND=file` works without DB data.
- Full backend unit tests pass.
- Frontend Admin source tests and typecheck pass.
- Frontend `InterviewDirection` type includes `retrieval_alpha?: number | null`.
- Deployment docs state import commands, Admin verification steps, and rollback switches.

## Implementation Notes For Future Agent

- Do not use a new worktree unless the user explicitly asks. This project has already standardized on `D:\Agent\Agentic_Interviewer` as the only running workspace.
- Do not modify `.cursor` files unless the user explicitly asks.
- Preserve existing direction IDs and dimension IDs exactly.
- Prefer strict import and manual operator action over startup magic.
- Keep `job_templates.py` thin; it should continue deriving its response from the direction registry.
- If a test reveals that a product direction is missing from the DB, fix the import or source content rather than adding silent per-direction fallback.
