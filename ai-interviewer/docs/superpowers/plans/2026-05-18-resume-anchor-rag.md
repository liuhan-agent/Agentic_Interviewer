# Resume Anchor RAG Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Re-activate the dormant RAG module by giving it one real, high-value job: semantic retrieval of candidate-resume fragments so the Generator can ask follow-up questions grounded in the candidate's actual experience instead of generic templates.

**Architecture:** Build a session-scoped resume vector store on PgVector (same Postgres instance as the existing tables). Treat resume upload parsing as a pre-session parse artifact, then bind that artifact to `session_id` inside `POST /sessions` and vectorize serially before the interview workflow starts. Add a new `_step_retrieve_resume_anchor` step before `draft_question`. Ship through `off -> shadow -> primary` rollout. Keep the existing rule-based `select_resume_anchor` intact and complementary — the new `resume_rag_block` is an additive prompt slot.

**Tech Stack:** FastAPI, SQLAlchemy ORM, PostgreSQL + pgvector extension, Pydantic settings, pytest, OpenAI-compatible embedding API, frontend TypeScript source tests.

---

## Background

The current source map for resume handling:

- `ai-interviewer/backend/app/services/resume_parser.py`
  - LLM-driven structured extraction. Produces `projects[]`, `focus_areas[]`, `skills[]`, summary, etc.
- `ai-interviewer/backend/app/services/resume_parse_jobs.py`
  - In-memory `ResumeParseJobManager` with `ThreadPoolExecutor(max_workers=4)`. Status: `running / completed / failed / expired`. These jobs run before an interview session exists, so they do not have `session_id`.
- `ai-interviewer/backend/app/api/v1/interview.py`
  - `POST /api/v1/interview/resume/parse` and `/resume/parse-jobs` are setup-time upload endpoints. They return `candidate.resume_parsed` for review/edit before `POST /sessions`.
  - `POST /api/v1/interview/sessions` creates the session. Today it receives structured `candidate.resume_parsed`, not raw resume text.
- `ai-interviewer/backend/app/engine/workflow/nodes/resume_parse.py`
  - Historical node name only. It does not parse raw resume bytes; it locks in rubric/dimensions from the already-submitted structured request.
- `ai-interviewer/backend/app/engine/resume_plan.py`
  - `select_resume_anchor` rule-based selector. Reads `candidate.resume_parsed.{projects, focus_areas}`, picks a single anchor by `(self_intro_match, dimension_match, unused, priority)`.
- `ai-interviewer/backend/app/engine/workflow/nodes/ask_question.py`
  - Initialises `ctx["resume_anchor"]` via `select_resume_anchor`. Plan steps consume it.
- `ai-interviewer/backend/app/engine/workflow/plans/ask_plans.py`
  - Four plan templates: `simple / quick_review / adaptive / deep_probe`. The first three call `retrieve_rag`, `retrieve_strategy`, `draft_question`. `deep_probe` adds `challenge_with_reference`.
- `ai-interviewer/backend/app/engine/agents/generator.py`
  - Generator prompt builder. Currently splices `retrieval_block`, `question_seed_block`, `candidate_anchor_block`, `strategy_block`, `skill_block`, `avoid_patterns_block`, `resume_anchor` into the prompt.
- `ai-interviewer/backend/app/engine/agents/prompts/generator_task.md`
  - Prompt template with the slots above.
- `ai-interviewer/backend/app/engine/rag/vectorstore.py`
  - `ChromaVectorStore` with in-memory fallback. Currently `count() == 0` — no real ingestion happens.
- `ai-interviewer/backend/app/engine/rag/ingestion.py`
  - `NON_RAG_JSON_SOURCES` + `NON_RAG_SOURCE_PREFIXES` strip every existing `knowledge/` subdirectory from RAG. `_iter_documents(knowledge/)` returns 0 chunks today.

## Core Decision

Re-activate RAG with one well-scoped role: **candidate resume semantic anchor retrieval**, not generic knowledge.

- Use PgVector on the existing Postgres (same instance as `question_seeds`, `skill_playbook_cards`, etc.).
- Keep the dormant ChromaVectorStore code as a labelled dead-code path. Cleanup belongs to a separate `RAG-cleanup` plan once this resume RAG path is in primary.
- Keep the existing rule-based `select_resume_anchor` and add an **additive** semantic block. The two coexist; the Generator sees both.
- Do **not** vectorize inside `ResumeParseJobManager._run_job`: the parse job has no `session_id`. Instead, save a short-lived parse artifact at upload/parse time, pass its id through setup, and bind/vectorize it serially during `POST /sessions`. `resume_parse.completed` means "structured extraction is ready"; `candidate.resume_vector_status.status == "ready"` means "resume RAG is queryable."

## Boundaries

In scope:

- PgVector enablement (extension + ORM model + index).
- Self-adaptive resume chunker with 4 modes (A/B/C/D).
- Strict PII redaction before vectorization.
- Session + resume-revision scoped filtering.
- New `_step_retrieve_resume_anchor` step in all relevant plan templates.
- `challenge_with_reference` switch from `retrieval_block` to `resume_rag_block`.
- Generator prompt `resume_rag_block` slot.
- Shadow → Primary rollout switch with per-mode hit-rate thresholds.
- Admin observation panel with mode-grouped metrics.
- Subject-deletion admin endpoint.
- Soft retention (`session lifetime + 24h`) plus periodic cleanup job.
- Embedding model version field for forward-compatible migration.

Out of scope:

- Knowledge RAG (industry docs, sample answers, etc.) — separate future plan.
- ChromaVectorStore removal — separate future cleanup plan.
- Evaluator runtime consumption of `evaluator_rubric_hints` / `score_bias_rules` (Skills playbook feature, separate plan).
- Cross-candidate query (always forbidden, double-filtered).
- Multi-language embedding switch (stay on the configured OpenAI-compatible endpoint until Shadow data motivates a change).
- Parallel execution of retrieve_strategy and retrieve_resume_anchor (kept serial in P0).
- LLM-based dynamic query enhancement using evaluator feedback (deferred until Shadow data shows the basic query underperforms).

## Risk Points

Critical:

- **R1 Cross-candidate leakage.** A `session_A` query must never recall `session_B` chunks. Enforced by namespace + metadata filter + dedicated unit tests.
- **R2 PII reverse-engineering from embeddings.** Short-text embeddings can leak partial originals. Mitigation: all chunks pass `redact_pii` before ingestion. Original text is still stored for prompt rendering convenience (the practical reversal risk is bounded by redaction, and an extra DB hit on every retrieval is worse).
- **R3 Right to be forgotten.** A candidate-driven delete must wipe `resume_chunks`, setup snapshots / current question payloads containing resume-derived material, short-lived parse artifacts, and any cached artifacts. Dedicated admin endpoint + dedicated test.
- **R3b Session binding gap.** Resume upload parse happens before `session_id` exists. Do not write session-scoped chunks from the parse job. Persist a short-lived parse artifact and consume it from `POST /sessions`, where both raw text and `session_id` are available.

High:

- **R4 Embedding model version drift.** Remote providers periodically update underlying models. The vector space silently shifts. Mitigation: `embedding_model_version` column; query must match the column value of stored chunks; degradation goes to rule anchor.
- **R5 Cascade from parse failure.** If `resume_parser` fails, `resume_parsed` is empty. The chunker still works directly on raw text — no hard dependency on `parsed`. The vectorize step is skipped if no text is available.
- **R6 Low-quality recall pollutes Generator prompt.** Threshold is set strict (`0.45` cosine). Below-threshold recalls drop. Prompt template adds defensive line: "If the resume_rag_block appears irrelevant, ignore it."
- **R7 Missing `seed.scenario_brief`.** Some legacy seeds may not declare it. Fallback query formula: `scenario_brief OR title OR intent`.

Medium:

- **R8 Test reproducibility.** Remote embedding is non-deterministic. Unit tests mock embeddings with fixed vectors. E2E smoke tests are isolated.
- **R9 Cost / size monitoring.** Daily embedding call count + PG `resume_chunks` row count surface as admin metrics. Cleanup job removes expired rows daily.
- **R10 Trace replay.** Once a session's chunks are cleaned, trace replay can show the recall ids, scores, and optional short redacted excerpts, but cannot re-run the query. Do not store full resume chunks in trace artifacts.
- **R11 Rollout staging.** `resume_rag_mode: Literal["off", "shadow", "primary"] = "off"` plus an optional `resume_rag_session_sample_rate: float = 1.0` for gradual ramp.
- **R12 Re-uploaded resume / revision drift.** If a candidate binds a newer resume artifact to the same session, create a new `resume_revision_id`. Retrieval must filter by `session_id + resume_revision_id + embedding_model_version`; if vectorization of the new revision fails, fallback to rule anchor rather than querying old revision chunks.

Low:

- **R13 Chinese vs English vs mixed resume.** OpenAI-compatible models handle mixed content acceptably. Future migration to a Chinese-strong local model is decided post-Shadow.
- **R14 Generator prompt length growth.** Cap `resume_rag_block` at 800 characters. Monitor mean/p99 prompt length.

## Data Model

Create `ai-interviewer/backend/app/models/resume_anchor.py`:

```python
class ResumeChunk(Base):
    __tablename__ = "resume_chunks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(96), index=True)
    resume_revision_id: Mapped[str] = mapped_column(String(96), index=True)
    source_artifact_id: Mapped[str | None] = mapped_column(String(96), index=True, nullable=True)
    chunk_index: Mapped[int] = mapped_column(Integer, default=0)
    tier: Mapped[str] = mapped_column(String(32), index=True)
    section_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    heading: Mapped[str | None] = mapped_column(String(200), nullable=True)
    project_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    text: Mapped[str] = mapped_column(Text, default="")
    tech_keywords: Mapped[list] = mapped_column(JSON, default=list)
    dimensions_hint: Mapped[list] = mapped_column(JSON, default=list)
    chunker_mode: Mapped[str] = mapped_column(String(8), index=True)
    embedding_model_version: Mapped[str] = mapped_column(String(96), index=True)
    embedding: Mapped[list[float]] = mapped_column(Vector(1536))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), index=True
    )
```

Notes:

- `tier in {"project", "highlight", "skill", "section", "window", "full"}`. The first three are Mode A. `section` is Mode B. `window` is Mode C. `full` is Mode D.
- `chunker_mode in {"A", "B", "C", "D"}` for grouped metrics.
- `embedding` is `pgvector.sqlalchemy.Vector` with dimension 1536 (OpenAI text-embedding-3-small default). Add a settings knob for the dimension if a future model uses something else.
- HNSW index on `embedding` with `vector_cosine_ops`; B-tree composite index on `(session_id, resume_revision_id, embedding_model_version, tier)`.
- `resume_revision_id` is the active revision recorded in `candidate.resume_vector_status.resume_revision_id`. The retriever must never query chunks for another revision, even inside the same session.
- `source_artifact_id` points back to the short-lived setup parse artifact for audit/debug only. It is nullable because legacy/manual setup flows can skip raw-text binding and fall back to rule anchor.
- `expires_at` is set to `now + session_lifetime + 24h` at insert time; cleanup job deletes rows where `expires_at < now()`.
- Original chunk `text` is stored (R2 mitigation: redact upstream, accept the convenience trade-off).

Schema bootstrap in `init_db()` must:

1. Import `app.models.resume_anchor` before `Base.metadata.create_all`.
2. Execute `CREATE EXTENSION IF NOT EXISTS vector;` against the engine (no-op if already installed).
3. Create the HNSW index via `Base.metadata.create_all` if SQLAlchemy supports it; otherwise add a guarded `CREATE INDEX IF NOT EXISTS` statement in `_POSTGRES_UPGRADES`.

## Settings

Add to `ai-interviewer/backend/app/core/settings.py`:

```python
resume_rag_mode: Literal["off", "shadow", "primary"] = "off"
resume_rag_top_k: int = 3
resume_rag_distance_threshold: float = 0.45
resume_rag_timeout_ms: int = 300
resume_rag_block_max_chars: int = 800
resume_rag_min_text_chars: int = 500
resume_rag_session_sample_rate: float = 1.0
resume_rag_session_ttl_hours: int = 24
resume_rag_parse_artifact_ttl_seconds: int = 3600
resume_rag_embedding_endpoint: str = "https://api.openai.com/v1"
resume_rag_embedding_model: str = "text-embedding-3-small"
resume_rag_embedding_dimension: int = 1536
resume_rag_embedding_api_key: str = ""
```

Rollout rule:

- Keep default `off` while Tasks 1–6 land.
- Flip to `shadow` in Task 7 only after admin parity checks are green.
- Flip to `primary` per-mode after the Shadow hit-rate threshold is met (Task 7 runbook).
- Preserve `off` as the fastest rollback switch.

Add the new fields to `ai-interviewer/backend/app/core/deployment_preflight.py`.

## Task 0: Golden Baseline Tests Before Any Workflow Change

**Files:**

- Create: `ai-interviewer/backend/tests/unit/test_resume_anchor_baseline.py`
- Modify: `ai-interviewer/backend/tests/unit/test_ask_question_selection_artifacts.py`

- [ ] Pin the current `select_resume_anchor` outputs for a representative parsed resume fixture.

```python
def test_rule_anchor_selects_dimension_match_when_unused(parsed_resume_fixture):
    anchor = select_resume_anchor(
        candidate={"resume_parsed": parsed_resume_fixture},
        job_spec={},
        dimension="system_design",
        qa_history=[],
        turn_idx=0,
    )
    assert anchor["focus_id"] is not None
    assert "system_design" in anchor["dimensions"]
```

- [ ] Pin the current Generator prompt slot order (`retrieval_block / question_seed_block / candidate_anchor_block / strategy_block / skill_block / avoid_patterns_block / resume_anchor`).

- [ ] Pin the four plan template step kinds.

```python
def test_plan_templates_step_kinds_baseline():
    assert [s["kind"] for s in PLAN_TEMPLATES["simple"]["steps"]] == [
        "retrieve_rag", "draft_question", "guardrail_check"
    ]
    assert [s["kind"] for s in PLAN_TEMPLATES["adaptive"]["steps"]] == [
        "retrieve_rag", "retrieve_strategy", "draft_question",
        "negotiate_contract", "guardrail_check"
    ]
    assert [s["kind"] for s in PLAN_TEMPLATES["quick_review"]["steps"]] == [
        "retrieve_rag", "draft_question", "guardrail_check"
    ]
    assert [s["kind"] for s in PLAN_TEMPLATES["deep_probe"]["steps"]] == [
        "retrieve_rag", "retrieve_strategy", "draft_question",
        "negotiate_contract", "challenge_with_reference", "guardrail_check"
    ]
```

- [ ] Run baseline tests.

```bash
cd D:\Agent\Agentic_Interviewer\ai-interviewer\backend
python -m pytest tests/unit/test_resume_anchor_baseline.py tests/unit/test_ask_question_selection_artifacts.py -q
```

Expected: all baseline assertions pass against the current code.

- [ ] Commit.

```bash
git add ai-interviewer/backend/tests/unit/test_resume_anchor_baseline.py ai-interviewer/backend/tests/unit/test_ask_question_selection_artifacts.py
git commit -m "test: pin resume anchor and plan template baselines"
```

## Task 1: PgVector Infrastructure

**Files:**

- Modify: `ai-interviewer/backend/requirements.txt` (add `pgvector` Python package)
- Create: `ai-interviewer/backend/app/models/resume_anchor.py`
- Modify: `ai-interviewer/backend/app/models/__init__.py`
- Modify: `ai-interviewer/backend/app/models/base.py`
- Modify: `ai-interviewer/backend/docker-compose.yml` (or equivalent) to use `pgvector/pgvector:pg17` image
- Create: `ai-interviewer/backend/tests/unit/test_resume_chunk_model.py`

- [ ] Pin the pgvector Python dependency.

```text
# requirements.txt
pgvector==0.3.6
```

- [ ] Implement the ORM model per the Data Model section. Use `pgvector.sqlalchemy.Vector`.

- [ ] Add `app.models.resume_anchor` to the import chain in `app/models/__init__.py`.

- [ ] Update `init_db()` to issue `CREATE EXTENSION IF NOT EXISTS vector;` before `Base.metadata.create_all`.

- [ ] Add a guarded HNSW index creation. If using `_POSTGRES_UPGRADES`, add:

```python
("resume_chunks", "embedding_hnsw_cosine"): (
    "CREATE INDEX IF NOT EXISTS ix_resume_chunks_embedding_hnsw "
    "ON resume_chunks USING hnsw (embedding vector_cosine_ops);"
)
```

- [ ] Add a SQLite-skip guard: SQLite cannot satisfy pgvector, so the resume RAG model must be skipped at table creation when the engine is SQLite (development fallback). Tests must still assert the model is loadable.

- [ ] Update `docker-compose.yml` / `Dockerfile` to use `pgvector/pgvector:pg17` (or matching Postgres version with the extension).

- [ ] Write the round-trip test using a Postgres test container (or a `vector`-enabled Postgres available in CI).

```python
def test_resume_chunk_round_trip_with_pgvector(pg_engine):
    Base.metadata.create_all(pg_engine)
    with Session(pg_engine) as s:
        s.add(ResumeChunk(
            session_id="sess_a",
            resume_revision_id="rev_1",
            source_artifact_id="artifact_1",
            chunk_index=0,
            tier="highlight",
            heading="数据查询优化",
            project_name="康乐智慧养老系统",
            text="实时数据按 iotId 落 Redis Hash, HMGET 批量回填",
            tech_keywords=["Redis", "HMGET", "MyBatis-Plus"],
            chunker_mode="A",
            embedding_model_version="text-embedding-3-small@v1",
            embedding=[0.1] * 1536,
        ))
        s.commit()
        row = s.scalar(select(ResumeChunk).where(ResumeChunk.session_id == "sess_a"))
    assert row.tier == "highlight"
    assert row.embedding[0] == pytest.approx(0.1)
```

- [ ] Run the model tests.

```bash
python -m pytest tests/unit/test_resume_chunk_model.py -q
```

Expected: round trip passes against a pgvector-enabled Postgres.

- [ ] Commit.

```bash
git add ai-interviewer/backend/requirements.txt ai-interviewer/backend/app/models/resume_anchor.py ai-interviewer/backend/app/models/__init__.py ai-interviewer/backend/app/models/base.py ai-interviewer/backend/docker-compose.yml ai-interviewer/backend/tests/unit/test_resume_chunk_model.py
git commit -m "feat: add resume chunk model with pgvector"
```

## Task 2: Self-Adaptive Resume Chunker

**Files:**

- Create: `ai-interviewer/backend/app/services/resume_chunker.py`
- Create: `ai-interviewer/backend/tests/unit/test_resume_chunker.py`
- Create: `ai-interviewer/backend/tests/fixtures/resumes/` (4 resume fixtures)

- [ ] Define the chunker public API.

```python
class ResumeChunkerMode(str, Enum):
    A = "A"  # high-structure: project + highlight + skill
    B = "B"  # medium-structure: section paragraphs
    C = "C"  # low-structure: sliding window
    D = "D"  # minimal: full text, do not vectorize

@dataclass(frozen=True)
class ResumeChunk:
    chunk_index: int
    tier: str
    section_name: str | None
    heading: str | None
    project_name: str | None
    text: str
    tech_keywords: list[str]
    dimensions_hint: list[str]


def detect_resume_structure(text: str, parsed: dict | None) -> ResumeChunkerMode:
    raise NotImplementedError


def chunk_resume(text: str, parsed: dict | None) -> tuple[ResumeChunkerMode, list[ResumeChunk]]:
    raise NotImplementedError


def normalize_resume_text(raw: str) -> str:
    raise NotImplementedError


def extract_tech_keywords(text: str) -> list[str]:
    raise NotImplementedError


def infer_dimensions_hint(text: str, tech_keywords: list[str]) -> list[str]:
    raise NotImplementedError
```

- [ ] Implement `normalize_resume_text(raw)`:

  - Collapse runs of whitespace (including U+00A0 / U+2009 / U+200B).
  - Fix common OCR garbage like `Java +新特性` → `Java 8新特性` (maintain a small lookup table; bias toward leaving uncertain spans untouched).
  - Normalise full-width punctuation to half-width inside ASCII tech tokens (`Java、Spring` stays as-is in Chinese context).

- [ ] Implement `detect_resume_structure(text, parsed)`. Signal weighting:

  - `+3` per matched section header keyword: `项目经验 / 工作经历 / 专业项目 / Projects / Experience / 教育背景`.
  - `+2` per detected sub-item delimiter pattern (`. ` at line start, `• `, `1.`).
  - `+2` for `>= 2` date ranges (`2024.05-2024.08`, `2024/05`, `2024年05月`).
  - `+1` per technical keyword dictionary hit (Java, Spring, Redis, Python, React, Kubernetes, etc.).

  Classification:

  - `text < resume_rag_min_text_chars (500)` → `D`.
  - section headers AND sub-items >= 3 AND date ranges >= 1 → `A`.
  - section headers AND date ranges >= 1 → `B`.
  - otherwise → `C`.

- [ ] Implement Mode A chunker. Walk projects and split each into highlight chunks by `. ` (or `•`) at line-leading positions. Tag each chunk with `tier=highlight`, plus one project-level summary chunk per project (`tier=project`), plus one chunk per skill line (`tier=skill`).

- [ ] Implement Mode B chunker. Split by date-anchored section boundaries; one chunk per section. `tier="section"`.

- [ ] Implement Mode C chunker. Sliding window of 300 characters with 60-character overlap; preserve sentence-ish boundaries when possible. `tier="window"`.

- [ ] Implement Mode D chunker. Return the full text as a single chunk with `tier="full"`. Callers must skip vectorisation when mode is D.

- [ ] Implement `extract_tech_keywords(text)`:

  - Walk a maintained tech dictionary (Java, Spring Boot, Spring Cloud, MyBatis-Plus, Redis, RabbitMQ, ElasticSearch, LangChain, etc.). Case-insensitive substring match with word-boundary heuristic.
  - Cap at 16 keywords per chunk.
  - If dictionary hits < 3, fall back to an inline LLM call that asks for `<=8 technical keywords` and never raises (returns `[]` on any error).

- [ ] Implement `infer_dimensions_hint(text, tech_keywords)`:

  - Use the tech keyword list and a static mapping (e.g. `{"Redis": ["system_design", "technical_depth"], "Spring Security": ["coding_quality", "system_design"]}`).
  - Return distinct dimensions, sorted.

- [ ] Add four fixture resumes covering the modes.

  - `fixture_high_structure_tech.md` (e.g. the Java backend resume content reused here).
  - `fixture_medium_structure_sales.md` (date-anchored paragraphs without sub-items).
  - `fixture_low_structure_freeform.md` (no headings, just paragraphs).
  - `fixture_minimal_intern.md` (< 500 characters).

- [ ] Write the chunker tests.

```python
def test_chunker_classifies_high_structure_resume():
    text = (FIXTURE_DIR / "fixture_high_structure_tech.md").read_text(encoding="utf-8")
    mode, chunks = chunk_resume(text, parsed=None)
    assert mode is ResumeChunkerMode.A
    tiers = [c.tier for c in chunks]
    assert tiers.count("highlight") >= 8
    assert tiers.count("skill") >= 5
    assert all(c.text.strip() for c in chunks)


def test_chunker_falls_back_to_full_on_minimal_resume():
    text = (FIXTURE_DIR / "fixture_minimal_intern.md").read_text(encoding="utf-8")
    mode, chunks = chunk_resume(text, parsed=None)
    assert mode is ResumeChunkerMode.D
    assert len(chunks) == 1


def test_chunker_extracts_tech_keywords_from_highlight():
    text = "Redis Hash 缓存 + Lua 脚本保证 RabbitMQ 异步写入"
    keywords = extract_tech_keywords(text)
    assert {"Redis", "Lua", "RabbitMQ"}.issubset(set(keywords))


def test_chunker_never_raises_on_garbage_input():
    mode, chunks = chunk_resume("", parsed=None)
    assert mode is ResumeChunkerMode.D
    assert chunks == [] or chunks[0].text == ""
```

- [ ] Run the chunker tests.

```bash
python -m pytest tests/unit/test_resume_chunker.py -q
```

Expected: all four modes are correctly classified; tech keyword extraction works; garbage input degrades gracefully.

- [ ] Commit.

```bash
git add ai-interviewer/backend/app/services/resume_chunker.py ai-interviewer/backend/tests/unit/test_resume_chunker.py ai-interviewer/backend/tests/fixtures/resumes/
git commit -m "feat: add self-adaptive resume chunker"
```

## Task 3: Embedding Service Wrapper

**Files:**

- Create: `ai-interviewer/backend/app/services/resume_embedding.py`
- Create: `ai-interviewer/backend/tests/unit/test_resume_embedding.py`

- [ ] Define the embedding service API.

```python
class ResumeEmbeddingError(RuntimeError):
    pass


def embed_chunks(
    texts: list[str],
    *,
    model: str | None = None,
    timeout_ms: int | None = None,
) -> list[list[float]]:
    """Batch-embed chunk texts. Raises ResumeEmbeddingError on any failure."""


def embed_query(
    text: str,
    *,
    model: str | None = None,
    timeout_ms: int | None = None,
    cache_key: str | None = None,
) -> list[float] | None:
    """Embed a single query string. Returns None on timeout/failure to keep the call site
    in a single safe branch. Uses a small in-memory LRU keyed on (model, cache_key)."""


def current_embedding_model_version() -> str:
    """Return the canonical `<model>@<version>` string written to ResumeChunk."""
```

- [ ] Implementation rules:

  - Use the OpenAI-compatible REST endpoint configured by `resume_rag_embedding_endpoint`. Do not bind the implementation to the `openai` Python package — use `httpx` so the endpoint can be swapped to any OpenAI-protocol-compatible provider via settings alone.
  - Batch requests; cap batch size at 64.
  - `embed_chunks` raises on any non-2xx or timeout.
  - `embed_query` is the production hot path: never raises, returns `None` so the call site only branches once. Log a single WARNING on failure.
  - LRU cache for `embed_query`: in-memory `dict[(model, cache_key), tuple[vector, monotonic_ts]]`, capped at 256 entries, TTL 5 minutes.

- [ ] Tests with mocked HTTP client.

```python
def test_embed_chunks_batches_under_64(mock_http):
    mock_http.add_post("/embeddings", lambda req: _ok_response(len(req["input"])))
    vectors = embed_chunks(["x"] * 150)
    assert len(vectors) == 150
    assert mock_http.call_count == 3  # 64 + 64 + 22


def test_embed_query_swallows_timeout(mock_http):
    mock_http.set_timeout()
    assert embed_query("缓存一致性") is None


def test_embed_query_cache_avoids_second_call(mock_http):
    mock_http.add_post("/embeddings", lambda req: _ok_response(1))
    v1 = embed_query("Redis 高并发", cache_key="seed1")
    v2 = embed_query("Redis 高并发", cache_key="seed1")
    assert v1 == v2
    assert mock_http.call_count == 1
```

- [ ] Run the embedding tests.

```bash
python -m pytest tests/unit/test_resume_embedding.py -q
```

Expected: batching, swallow-on-failure, and LRU cache behaviour all confirmed.

- [ ] Commit.

```bash
git add ai-interviewer/backend/app/services/resume_embedding.py ai-interviewer/backend/tests/unit/test_resume_embedding.py
git commit -m "feat: add resume embedding service wrapper"
```

## Task 4: Parse Artifact Binding + Session Vectorization

**Files:**

- Create: `ai-interviewer/backend/app/services/resume_parse_artifacts.py`
- Create: `ai-interviewer/backend/app/services/resume_vectorize.py`
- Modify: `ai-interviewer/backend/app/api/v1/interview.py`
- Modify: `ai-interviewer/backend/app/services/resume_parse_jobs.py`
- Modify: `ai-interviewer/frontend/src/lib/api/types.ts`
- Modify: `ai-interviewer/frontend/src/components/interview/SetupForm.tsx`
- Modify: `ai-interviewer/frontend/src/lib/storage/setupDrafts.ts`
- Create: `ai-interviewer/backend/tests/unit/test_resume_parse_artifacts.py`
- Create: `ai-interviewer/backend/tests/unit/test_resume_vectorize.py`
- Create: `ai-interviewer/backend/tests/unit/test_resume_rag_session_binding.py`
- Modify: `ai-interviewer/backend/tests/unit/test_resume_parse_jobs.py`
- Modify: `ai-interviewer/backend/tests/unit/test_interview_setup_api_contract.py`
- Modify: `ai-interviewer/frontend/tests/resumeUpload.test.js`

### Task 4a: Short-lived parse artifacts

- [ ] Create `resume_parse_artifacts.py`. This bridges setup-time resume parsing and session-scoped vectorization. Store redacted text, not raw PII.

```python
@dataclass(frozen=True)
class ResumeParseArtifact:
    artifact_id: str
    redacted_text: str
    parsed: dict[str, Any]
    filename: str | None
    text_sha256: str
    created_at: datetime
    expires_at: datetime


class ResumeParseArtifactStore:
    def put(self, *, text: str, parsed: dict[str, Any], filename: str | None) -> ResumeParseArtifact:
        cleaned = redact_pii(text or "").cleaned
        artifact = ResumeParseArtifact(
            artifact_id=secrets.token_urlsafe(24),
            redacted_text=cleaned,
            parsed=dict(parsed or {}),
            filename=filename,
            text_sha256=hashlib.sha256(cleaned.encode("utf-8")).hexdigest(),
            created_at=datetime.now(UTC),
            expires_at=datetime.now(UTC) + timedelta(
                seconds=max(60, get_settings().resume_rag_parse_artifact_ttl_seconds)
            ),
        )
        self._items[artifact.artifact_id] = artifact
        return artifact

    def consume(self, artifact_id: str) -> ResumeParseArtifact | None:
        artifact = self._items.pop(artifact_id, None)
        if artifact is None or artifact.expires_at <= datetime.now(UTC):
            return None
        return artifact
```

- [ ] Tests:

```python
def test_resume_parse_artifact_redacts_pii():
    store = ResumeParseArtifactStore()
    artifact = store.put(
        text="Alex 13800001111 alex@example.com did Redis work.",
        parsed={"summary": "Redis work"},
        filename="resume.txt",
    )
    assert "13800001111" not in artifact.redacted_text
    assert "alex@example.com" not in artifact.redacted_text


def test_resume_parse_artifact_consume_is_one_shot():
    store = ResumeParseArtifactStore()
    artifact = store.put(text="Redis project", parsed={}, filename=None)
    assert store.consume(artifact.artifact_id) is not None
    assert store.consume(artifact.artifact_id) is None
```

### Task 4b: Vectorize helper

```python
def vectorize_resume(
    *,
    session_id: str,
    resume_revision_id: str,
    source_artifact_id: str | None,
    raw_text: str,
    parsed: dict | None,
    db_session: Session | None = None,
) -> dict[str, Any]:
    """Normalize -> chunk -> redact -> embed -> upsert.

    Returns a status payload:
        {
            "status": "ready" | "skipped" | "failed",
            "mode": "A" | "B" | "C" | "D",
            "chunk_count": int,
            "embedding_model_version": str,
            "skipped_reason": str | None,
            "error": str | None,
        }

    Writes chunks for the exact ``session_id`` + ``resume_revision_id``.
    Older revisions may remain until cleanup, but the retriever must never
    query them for the new revision.
    Never raises — failures are returned as ``status="failed"``.
    """
```

- [ ] Implementation rules:

  - Always run inside a single transaction.
  - Mode D returns `status="skipped", skipped_reason="mode_d_minimal_resume"`. No DB writes.
  - Vectorize failure (embedding error) returns `status="failed"` and rolls back the transaction so no half-state remains.
  - Do not reuse previous chunks after failure. The active `resume_revision_id` recorded on `candidate.resume_vector_status` is the only revision the retriever may query.
  - Compute `expires_at = now() + session_ttl + 24h` for each row.
  - Use `redact_pii` on each chunk text before storing/embedding even though the parse artifact was already redacted.
  - Return `resume_revision_id`, `source_artifact_id`, `embedding_model_version`, and `text_sha256` when available.

### Task 4c: Parse endpoints return artifact ids, not vectors

- [ ] In `POST /resume/parse`, after `payload = result.payload`, create an artifact and return its id:

```python
artifact = create_resume_parse_artifact(
    text=result.text,
    parsed=payload,
    filename=file.filename,
)
payload["resume_source_id"] = artifact.artifact_id
payload["resume_source_expires_at"] = artifact.expires_at.isoformat()
```

- [ ] In `ResumeParseJobManager._run_job`, do the same after `payload = resume_parse_payload(parsed, text)`.
- [ ] Do **not** call `vectorize_resume` from `ResumeParseJobManager._run_job`. A completed parse job means "setup artifact is ready", not "session RAG is queryable".

### Task 4d: Bind artifact during `POST /sessions`

- [ ] Add `resume_source_id` to `StartSessionRequest` as a top-level optional field.

```python
class StartSessionRequest(BaseModel):
    session_id: str | None = Field(default=None, min_length=1, max_length=SESSION_ID_MAX_LENGTH)
    trace_id: str | None = Field(default=None, min_length=1, max_length=SESSION_ID_MAX_LENGTH)
    candidate: CandidateInput
    job_spec: JobSpecInput
    resume_source_id: str | None = Field(default=None, max_length=128)
    mode: str = "mixed"
```

- [ ] In `start_session`, consume the artifact and vectorize after `translate_request(req.model_dump(exclude_none=False))` returns `session_id`, before calling `manager.start`.

```python
def _bind_resume_rag_for_session(
    *,
    session_id: str,
    resume_source_id: str | None,
    candidate: dict[str, Any],
) -> dict[str, Any]:
    if not resume_source_id:
        return {
            "status": "skipped",
            "skipped_reason": "no_parse_artifact",
            "resume_revision_id": None,
        }
    artifact = consume_resume_parse_artifact(resume_source_id)
    if artifact is None:
        return {
            "status": "skipped",
            "skipped_reason": "parse_artifact_missing_or_expired",
            "resume_revision_id": None,
        }
    revision_id = secrets.token_urlsafe(18)
    return vectorize_resume(
        session_id=session_id,
        resume_revision_id=revision_id,
        source_artifact_id=artifact.artifact_id,
        raw_text=artifact.redacted_text,
        parsed=candidate.get("resume_parsed") or artifact.parsed,
    )
```

- [ ] Store the returned status on the workflow state and setup snapshot:

```python
vector_status = _bind_resume_rag_for_session(
    session_id=session_id,
    resume_source_id=req.resume_source_id,
    candidate=initial.get("candidate") or {},
)
initial.setdefault("candidate", {})["resume_vector_status"] = vector_status
setup_snapshot["resume_vector_status"] = vector_status
```

- [ ] If vectorization fails, `POST /sessions` still succeeds. The interview falls back to rule-based `select_resume_anchor`.

### Task 4e: Frontend carries artifact id through setup

- [ ] Extend `ParseResumeResponse` with `resume_source_id` and `resume_source_expires_at`.
- [ ] Preserve those fields in `SetupForm` upload state and setup drafts.
- [ ] Include `resume_source_id` in the `startSession(payload)` request. If the user manually edits parsed fields, keep the same artifact id; the vectorizer uses raw text for chunking and the edited `candidate.resume_parsed` only as auxiliary metadata.

- [ ] Tests with a mocked embedding service and an in-memory pgvector-enabled Postgres (or stub vectorstore).

```python
def test_vectorize_resume_writes_chunks_and_returns_ready(monkeypatch, db_session):
    monkeypatch.setattr(
        "app.services.resume_vectorize.embed_chunks",
        lambda texts, **kw: [[0.1] * 1536 for _ in texts],
    )
    status = vectorize_resume(
        session_id="sess_a",
        resume_revision_id="rev_1",
        source_artifact_id="artifact_1",
        raw_text=HIGH_STRUCTURE_TEXT,
        parsed=None,
        db_session=db_session,
    )
    assert status["status"] == "ready"
    assert status["mode"] == "A"
    assert status["chunk_count"] >= 10
    rows = db_session.scalars(select(ResumeChunk).where(ResumeChunk.session_id == "sess_a")).all()
    assert len(rows) == status["chunk_count"]


def test_vectorize_resume_writes_revision_id(monkeypatch, db_session):
    vectorize_resume(
        session_id="sess_a",
        resume_revision_id="rev_1",
        source_artifact_id="artifact_1",
        raw_text=V1,
        parsed=None,
        db_session=db_session,
    )
    vectorize_resume(
        session_id="sess_a",
        resume_revision_id="rev_2",
        source_artifact_id="artifact_2",
        raw_text=V2,
        parsed=None,
        db_session=db_session,
    )
    rows = db_session.scalars(select(ResumeChunk).where(ResumeChunk.session_id == "sess_a")).all()
    assert {row.resume_revision_id for row in rows} == {"rev_1", "rev_2"}


def test_vectorize_resume_returns_failed_on_embedding_error(monkeypatch, db_session):
    monkeypatch.setattr(
        "app.services.resume_vectorize.embed_chunks",
        lambda texts, **kw: (_ for _ in ()).throw(ResumeEmbeddingError("upstream 500")),
    )
    status = vectorize_resume(
        session_id="sess_a",
        resume_revision_id="rev_failed",
        source_artifact_id="artifact_failed",
        raw_text=HIGH_STRUCTURE_TEXT,
        parsed=None,
        db_session=db_session,
    )
    assert status["status"] == "failed"
    rows = db_session.scalars(select(ResumeChunk).where(ResumeChunk.session_id == "sess_a")).all()
    assert rows == []


def test_vectorize_resume_skips_mode_d():
    status = vectorize_resume(
        session_id="sess_b",
        resume_revision_id="rev_short",
        source_artifact_id="artifact_short",
        raw_text="too short.",
        parsed=None,
    )
    assert status["status"] == "skipped"
    assert status["mode"] == "D"
```

- [ ] Add session-binding tests:

```python
def test_start_session_binds_parse_artifact_and_vectorizes(monkeypatch, client):
    parse = client.post("/api/v1/interview/resume/parse", files=resume_upload()).json()
    assert parse["resume_source_id"]

    captured = {}
    monkeypatch.setattr(
        "app.api.v1.interview.vectorize_resume",
        lambda **kwargs: captured.update(kwargs) or {
            "status": "ready",
            "resume_revision_id": kwargs["resume_revision_id"],
            "chunk_count": 3,
        },
    )

    response = client.post(
        "/api/v1/interview/sessions",
        json={
            "candidate": {"name": "Alex", "resume_parsed": {"summary": parse["summary"]}},
            "job_spec": {"title": "Backend Engineer", "level": "senior"},
            "resume_source_id": parse["resume_source_id"],
        },
    )

    assert response.status_code == 200
    assert captured["session_id"] == response.json()["session_id"]


def test_start_session_without_artifact_falls_back_to_rule_anchor(client):
    response = client.post(
        "/api/v1/interview/sessions",
        json={
            "candidate": {"name": "Alex", "resume_parsed": {"summary": "manual"}},
            "job_spec": {"title": "Backend Engineer", "level": "senior"},
        },
    )

    assert response.status_code == 200
```

- [ ] Run the artifact/vectorize/session-binding tests.

```bash
python -m pytest \
  tests/unit/test_resume_parse_artifacts.py \
  tests/unit/test_resume_vectorize.py \
  tests/unit/test_resume_parse_jobs.py \
  tests/unit/test_resume_rag_session_binding.py \
  tests/unit/test_interview_setup_api_contract.py -q
```

Expected: parse endpoints return source artifacts, session start binds artifacts to `session_id`, vectorize succeeds, failed/expired/missing artifacts degrade to rule anchor, and Mode D skips.

- [ ] Commit.

```bash
git add ai-interviewer/backend/app/services/resume_parse_artifacts.py ai-interviewer/backend/app/services/resume_vectorize.py ai-interviewer/backend/app/api/v1/interview.py ai-interviewer/backend/app/services/resume_parse_jobs.py ai-interviewer/backend/tests/unit/test_resume_parse_artifacts.py ai-interviewer/backend/tests/unit/test_resume_vectorize.py ai-interviewer/backend/tests/unit/test_resume_rag_session_binding.py ai-interviewer/backend/tests/unit/test_interview_setup_api_contract.py ai-interviewer/frontend/src/lib/api/types.ts ai-interviewer/frontend/src/components/interview/SetupForm.tsx ai-interviewer/frontend/src/lib/storage/setupDrafts.ts ai-interviewer/frontend/tests/resumeUpload.test.js
git commit -m "feat: bind parsed resume artifacts to session rag"
```

## Task 5: Retrieve Step + Plan Wiring + Generator Slot

**Files:**

- Create: `ai-interviewer/backend/app/services/resume_retriever.py`
- Modify: `ai-interviewer/backend/app/engine/workflow/nodes/ask_question.py`
- Modify: `ai-interviewer/backend/app/engine/workflow/plans/ask_plans.py`
- Modify: `ai-interviewer/backend/app/engine/agents/generator.py`
- Modify: `ai-interviewer/backend/app/engine/agents/prompts/generator_task.md`
- Create: `ai-interviewer/backend/tests/unit/test_resume_retriever.py`
- Modify: `ai-interviewer/backend/tests/unit/test_ask_question_selection_artifacts.py`

### Task 5a: Retriever and step function

- [ ] Implement `resume_retriever.py`.

```python
@dataclass
class ResumeRagResult:
    block: str
    hits: list[ResumeChunkHit]
    latency_ms: int
    fallback_reason: str | None  # None on success
    skipped: bool


def retrieve_resume_anchor(
    *,
    session_id: str,
    resume_revision_id: str,
    dimension: str,
    seed: dict | None,
    target_skills: list[str] | None,
    rule_anchor: dict | None,
    db_session: Session | None = None,
) -> ResumeRagResult:
    raise NotImplementedError
```

- [ ] Implementation rules:

  - Build the query string: `seed.scenario_brief OR seed.title OR seed.intent`, joined with `dimension` and `target_skills`.
  - Cache key for `embed_query`: `f"{dimension}|{seed_id}|{','.join(target_skills)}"`. Query embedding may be reused across sessions because the filter is applied at SQL level.
  - Apply hard timeout `resume_rag_timeout_ms`. On timeout return `ResumeRagResult(block="", hits=[], fallback_reason="timeout", skipped=False)`.
  - Filter recalls by `embedding_model_version == current_embedding_model_version()`, `session_id == session_id`, and `resume_revision_id == resume_revision_id`. Drop everything else even if metadata says otherwise (defence in depth for R1/R12).
  - Apply distance threshold; drop low-score hits. If all dropped → `fallback_reason="low_score"`.
  - If the rule anchor's `project_name` is non-empty and matches a hit's `project_name`, mark the hit as "anchor_dedup" and either drop it or keep just the text (no header) — see Task 5d.
  - Render `block` capped at `resume_rag_block_max_chars`.

- [ ] Implement `_step_retrieve_resume_anchor` in `ask_question.py`.

```python
def _step_retrieve_resume_anchor(state: InterviewState, ctx: dict[str, Any]) -> None:
    settings = get_settings()
    mode = getattr(settings, "resume_rag_mode", "off")
    if mode == "off":
        ctx["resume_rag_block"] = ""
        ctx["resume_anchor_rag_artifact"] = {"status": "off"}
        return
    vector_status = ((state.get("candidate") or {}).get("resume_vector_status") or {})
    if vector_status.get("status") != "ready" or not vector_status.get("resume_revision_id"):
        ctx["resume_rag_block"] = ""
        ctx["resume_anchor_rag_artifact"] = {
            "status": "skipped",
            "fallback_reason": vector_status.get("skipped_reason") or vector_status.get("status") or "not_ready",
            "resume_revision_id": vector_status.get("resume_revision_id"),
        }
        return
    result = retrieve_resume_anchor(
        session_id=str(state.get("session_id") or ""),
        resume_revision_id=str(vector_status["resume_revision_id"]),
        dimension=ctx["dimension"],
        seed=(ctx.get("question_items") or [None])[0],
        target_skills=ctx.get("target_skills") or [],
        rule_anchor=ctx.get("resume_anchor"),
    )
    ctx["resume_rag_block"] = result.block if mode == "primary" else ""
    ctx["resume_anchor_rag_artifact"] = result.as_artifact(mode=mode)
```

  - Always sets `ctx["resume_rag_block"]` (empty string when not used).
  - Always sets `ctx["resume_anchor_rag_artifact"]` so downstream artifact writers find a stable key.
  - Reads readiness from `state["candidate"]["resume_vector_status"]`.
  - If readiness is missing/failed/skipped, returns `fallback_reason="not_ready"` or the stored skip/failure reason and does not query PgVector.
  - In Shadow mode, retrieves and writes the artifact, but **does not** set the block (block stays empty).
  - In Primary mode, sets the block when there are kept hits.

- [ ] Register the dispatch entry.

```python
_STEP_DISPATCH = {
    "retrieve_rag": _step_retrieve_rag,
    "retrieve_strategy": _step_retrieve_strategy,
    "retrieve_resume_anchor": _step_retrieve_resume_anchor,
    "draft_question": _step_draft_question,
    "negotiate_contract": _step_negotiate_contract,
    "challenge_with_reference": _step_challenge_with_reference,
    "guardrail_check": _step_guardrail_check,
}
```

### Task 5b: Add the new step to plan templates

- [ ] Add `retrieve_resume_anchor` to `_SIMPLE_STEPS`, `_QUICK_REVIEW_STEPS`, `_ADAPTIVE_STEPS`, `_DEEP_PROBE_STEPS`, slotted after `retrieve_strategy` (where present) or right before `draft_question`. Mark `optional=True`.

```python
_step(
    n,
    "retrieve_resume_anchor",
    goal="Pull semantically related resume fragments to ground follow-up questions.",
    success_criteria="resume_anchor_rag_artifact is set (status may be off/shadow/empty).",
    produced_keys=["resume_rag_block", "resume_anchor_rag_artifact"],
    dependencies=[<prev step id>],
    optional=True,
)
```

- [ ] Update the plan-template baseline test created in Task 0 so it reflects the new step kind in each template.

### Task 5c: challenge_with_reference rewires to resume_rag_block

- [ ] Modify `_step_challenge_with_reference`:

```python
def _step_challenge_with_reference(state, ctx):
    payload = ctx.get("question_payload") or {}
    # NEW: prefer resume_rag_block; legacy retrieval_block is the secondary source.
    primary = ctx.get("resume_rag_block") or ""
    if not primary:
        primary = _retrieval_block_for_prompt(ctx) or ""
    first_line = next((line for line in primary.splitlines() if line.strip()), "")
    if first_line:
        payload["challenge_context"] = first_line.strip()[:240]
    ctx["question_payload"] = payload
```

### Task 5d: De-duplicate resume_anchor and resume_rag overlap

- [ ] In `retrieve_resume_anchor`, when a hit's `project_name == rule_anchor.project_name`, set `hit.deduped = True` and render only the text body without the project-label header so the prompt does not say "康乐项目" twice.

### Task 5e: Generator prompt slot

- [ ] Modify `app/engine/agents/generator.py` to accept and splice `resume_rag_block`.

- [ ] Modify `prompts/generator_task.md` to add a new section, placed AFTER `resume_anchor` (which is rule-based and definitive) and BEFORE `strategy_block`:

```jinja
## 候选人简历语义片段（RAG 召回）

{% if resume_rag_block %}
以下片段来自候选人简历，与当前问题主题语义相关。请基于这些**真实经历**追问，不要发明候选人没写过的项目。
如果这些片段看起来与当前问题无关，请忽略它们并按其它信号出题。

{{ resume_rag_block }}
{% else %}
（暂无相关简历片段）
{% endif %}
```

- [ ] Add the new artifact key to `selection_artifacts`:

```python
ctx_artifacts["resume_anchor_rag"] = ctx.get("resume_anchor_rag_artifact", {"status": "off"})
```

### Tests for Task 5

- [ ] Write end-to-end retriever test.

```python
def test_retrieve_resume_anchor_returns_top_k_high_scores(monkeypatch, db_session):
    # Seed DB with high-score chunk for sess_a/rev_1, low-score chunk for sess_a/rev_1
    # Verify only high-score chunk is in result.hits.


def test_retrieve_resume_anchor_isolates_other_sessions(monkeypatch, db_session):
    # Seed sess_a/rev_1 chunks, sess_a/rev_old chunks, AND sess_b/rev_1 chunks.
    # Query for sess_a must never include sess_b chunks even if sess_b has higher score.
    # Query for sess_a/rev_1 must never include sess_a/rev_old chunks.


def test_retrieve_resume_anchor_returns_timeout_fallback(monkeypatch):
    monkeypatch.setattr("app.services.resume_retriever.embed_query", lambda *a, **kw: None)
    result = retrieve_resume_anchor(
        session_id="sess_a",
        resume_revision_id="rev_1",
        dimension="system_design",
        seed={"scenario_brief": "Redis Lua consistency"},
        target_skills=["Redis", "Lua"],
        rule_anchor=None,
        db_session=db_session,
    )
    assert result.fallback_reason == "timeout"
    assert result.block == ""


def test_retrieve_resume_anchor_dedups_against_rule_anchor(monkeypatch, db_session):
    # Rule anchor project = 康乐项目
    # Recall includes a 康乐项目 highlight
    # Result.block must not redundantly label 康乐项目 twice.


def test_resume_rag_shadow_writes_artifact_but_not_block(monkeypatch):
    monkeypatch.setattr(get_settings(), "resume_rag_mode", "shadow")
    ctx = {}
    _step_retrieve_resume_anchor(state, ctx)
    assert ctx["resume_rag_block"] == ""
    assert ctx["resume_anchor_rag_artifact"]["status"] == "shadow"


def test_challenge_with_reference_prefers_resume_rag_block_over_retrieval_block():
    ctx["resume_rag_block"] = "[简历亮点] 智学/优惠券超发\nLua 脚本扣减库存"
    ctx["retrieval_block"] = "(legacy stuff)"
    _step_challenge_with_reference(state, ctx)
    assert "智学/优惠券超发" in ctx["question_payload"]["challenge_context"]


def test_plan_templates_now_include_retrieve_resume_anchor():
    for template in ["simple", "quick_review", "adaptive", "deep_probe"]:
        kinds = [s["kind"] for s in PLAN_TEMPLATES[template]["steps"]]
        assert "retrieve_resume_anchor" in kinds
```

- [ ] Run Task 5 tests + selection-artifact test.

```bash
python -m pytest \
  tests/unit/test_resume_retriever.py \
  tests/unit/test_ask_question_selection_artifacts.py \
  tests/unit/test_resume_anchor_baseline.py -q
```

Expected: all pass; selection artifact baseline updated to include the new `resume_anchor_rag` key.

- [ ] Commit.

```bash
git add ai-interviewer/backend/app/services/resume_retriever.py ai-interviewer/backend/app/engine/workflow/nodes/ask_question.py ai-interviewer/backend/app/engine/workflow/plans/ask_plans.py ai-interviewer/backend/app/engine/agents/generator.py ai-interviewer/backend/app/engine/agents/prompts/generator_task.md ai-interviewer/backend/tests/unit/test_resume_retriever.py ai-interviewer/backend/tests/unit/test_ask_question_selection_artifacts.py
git commit -m "feat: integrate resume anchor RAG into ask plans"
```

## Task 6: Admin Observation + Subject Deletion + Cleanup Job

**Files:**

- Modify: `ai-interviewer/backend/app/api/v1/admin.py`
- Modify: `ai-interviewer/frontend/src/lib/api/admin.ts`
- Modify: `ai-interviewer/frontend/src/components/admin/AdminPanel.tsx`
- Create: `ai-interviewer/frontend/src/components/admin/ResumeRagCard.tsx`
- Modify: `ai-interviewer/frontend/src/lib/api/types.ts`
- Modify: `ai-interviewer/frontend/tests/adminObservabilitySource.test.js`
- Create: `ai-interviewer/backend/app/scripts/cleanup_resume_chunks.py`
- Create: `ai-interviewer/backend/tests/unit/test_admin_resume_rag.py`
- Create: `ai-interviewer/backend/tests/unit/test_cleanup_resume_chunks.py`

### Task 6a: Admin endpoints

- [ ] Add these routes (all behind `Depends(require_admin_token)`):

  - `GET /admin/resume-rag/summary` — overall counts, per-mode counts, current `resume_rag_mode`.
  - `GET /admin/resume-rag/metrics` — last 24h hit-rate / fallback_reason distribution / p50/p99 latency, grouped by mode A/B/C/D.
  - `DELETE /admin/sessions/{session_id}/resume-data` — subject deletion (R3): delete all `resume_chunks` for the session, remove any remaining parse artifacts for the session/source ids when present, scrub resume-derived fields from `InterviewSession.setup_snapshot`, `InterviewSession.current_question`, and `GenerationTrace.state_snapshot`.

- Summary payload:

```json
{
  "resume_rag_mode": "shadow",
  "total_chunks": 1240,
  "total_sessions": 87,
  "by_mode": {
    "A": {"chunks": 920, "sessions": 60, "avg_chunks_per_session": 15.3},
    "B": {"chunks": 220, "sessions": 18, "avg_chunks_per_session": 12.2},
    "C": {"chunks": 100, "sessions": 9, "avg_chunks_per_session": 11.1},
    "D": {"chunks": 0, "sessions": 0, "avg_chunks_per_session": 0}
  },
  "embedding_model_version": "text-embedding-3-small@v1"
}
```

- Metrics payload (per mode):

```json
{
  "window_hours": 24,
  "by_mode": {
    "A": {
      "total_retrievals": 540,
      "hit_count": 410,
      "hit_rate": 0.759,
      "fallback_distribution": {
        "low_score": 80,
        "timeout": 30,
        "empty": 20,
        "not_ready": 0,
        "skipped": 0
      },
      "latency_ms": {"p50": 145, "p99": 290}
    }
  }
}
```

### Task 6b: Admin frontend card

- [ ] Add `ResumeRagCard.tsx` rendering:

  - Current `resume_rag_mode` (off / shadow / primary) prominent.
  - Total chunks + sessions.
  - Mode-grouped table: chunks, sessions, hit-rate, p50/p99 latency.
  - Fallback reasons stacked bar per mode.
  - Subject deletion button with explicit confirmation modal.

- [ ] Wire the card into `AdminPanel.tsx`. Keep `AdminPanel.tsx` lean — fetching and layout only, presentation in the new card.

### Task 6c: Cleanup job

- [ ] CLI: `python -m app.scripts.cleanup_resume_chunks`

  - Iterates `resume_chunks` where `expires_at < now()`.
  - Deletes in batches of 1000.
  - Logs counts; returns non-zero on DB error.
  - Idempotent: safe to run multiple times.

- [ ] Documented intended deployment: APScheduler hook (Task 9) or external cron.

### Tests

- [ ] Admin endpoint tests.

```python
def test_admin_resume_rag_summary_requires_token(client):
    r = client.get("/admin/resume-rag/summary")
    assert r.status_code == 401


def test_admin_resume_rag_summary_returns_per_mode_counts(client_with_token, seeded_chunks):
    r = client_with_token.get("/admin/resume-rag/summary")
    assert r.status_code == 200
    body = r.json()
    assert body["by_mode"]["A"]["chunks"] > 0


def test_admin_delete_session_resume_data_wipes_chunks(client_with_token, seeded_chunks):
    r = client_with_token.delete("/admin/sessions/sess_a/resume-data")
    assert r.status_code == 200
    remaining = client_with_token.get("/admin/resume-rag/summary").json()
    assert "sess_a" not in [s["session_id"] for s in remaining.get("recent_sessions", [])]
```

- [ ] Cleanup job test.

```python
def test_cleanup_resume_chunks_deletes_expired_only(db_session):
    db_session.add_all([
        ResumeChunk(
            session_id="a",
            resume_revision_id="rev_a",
            source_artifact_id="artifact_a",
            chunk_index=0,
            tier="highlight",
            text="expired Redis chunk",
            tech_keywords=["Redis"],
            dimensions_hint=["system_design"],
            chunker_mode="A",
            embedding_model_version="text-embedding-3-small@v1",
            embedding=[0.1] * 1536,
            expires_at=datetime.now(UTC) - timedelta(days=1),
        ),
        ResumeChunk(
            session_id="b",
            resume_revision_id="rev_b",
            source_artifact_id="artifact_b",
            chunk_index=0,
            tier="highlight",
            text="fresh Redis chunk",
            tech_keywords=["Redis"],
            dimensions_hint=["system_design"],
            chunker_mode="A",
            embedding_model_version="text-embedding-3-small@v1",
            embedding=[0.1] * 1536,
            expires_at=datetime.now(UTC) + timedelta(days=1),
        ),
    ])
    db_session.commit()
    run_cleanup()
    remaining = db_session.scalars(select(ResumeChunk)).all()
    assert {r.session_id for r in remaining} == {"b"}
```

- [ ] Run all Task 6 tests.

```bash
python -m pytest tests/unit/test_admin_resume_rag.py tests/unit/test_cleanup_resume_chunks.py tests/unit/test_admin_auth.py -q
cd D:\Agent\Agentic_Interviewer\ai-interviewer\frontend
npm test -- tests/adminObservabilitySource.test.js
npm run typecheck
```

Expected: admin routes require auth, summary/metrics return correct shape, deletion fully wipes, cleanup deletes only expired rows.

- [ ] Commit.

```bash
git add ai-interviewer/backend/app/api/v1/admin.py ai-interviewer/backend/tests/unit/test_admin_resume_rag.py ai-interviewer/backend/app/scripts/cleanup_resume_chunks.py ai-interviewer/backend/tests/unit/test_cleanup_resume_chunks.py ai-interviewer/frontend/src/lib/api/admin.ts ai-interviewer/frontend/src/lib/api/types.ts ai-interviewer/frontend/src/components/admin/AdminPanel.tsx ai-interviewer/frontend/src/components/admin/ResumeRagCard.tsx ai-interviewer/frontend/tests/adminObservabilitySource.test.js
git commit -m "feat: observe resume rag in admin and add cleanup job"
```

## Task 7: Shadow Mode Activation and Primary Rollout Runbook

**Files:**

- Modify: `ai-interviewer/backend/app/core/settings.py` (flip default + new sample-rate knob)
- Create: `ai-interviewer/docs/RESUME_RAG_ROLLOUT.md`
- Modify: `ai-interviewer/backend/README.md`
- Create: `ai-interviewer/backend/tests/unit/test_resume_rag_rollout_docs.py`

- [ ] Flip the default `resume_rag_mode = "shadow"`. Keep `off` as the rollback switch.

- [ ] Document the per-mode Shadow → Primary thresholds:

| Mode | Hit-rate threshold | Minimum sessions | Notes |
|---|---|---|---|
| A | ≥ 70% | ≥ 5 | High-structure resume |
| B | ≥ 55% | ≥ 5 | Section paragraphs |
| C | ≥ 40% | ≥ 5 | Sliding window |
| D | n/a | n/a | Never promoted; rule anchor only |

- [ ] Write the runbook `RESUME_RAG_ROLLOUT.md` covering:

  - Stage descriptions: `off / shadow / primary`.
  - How to verify Shadow data (admin metrics endpoint and panel).
  - The promote-to-primary checklist.
  - Sampling knob: `resume_rag_session_sample_rate` — set `0.05`, watch, then `0.3`, then `1.0`.
  - Rollback procedure: flip `resume_rag_mode=off` and (optionally) wipe DB chunks.

- [ ] Update README with:

  - Required Postgres image (`pgvector/pgvector:pg17`).
  - `CREATE EXTENSION vector` is auto-issued during `init_db()`.
  - `RESUME_RAG_MODE` env var default and rollback.
  - `python -m app.scripts.cleanup_resume_chunks` recommended cron schedule.

- [ ] Write a docs-source test asserting README and runbook contain the required strings.

```python
def test_readme_contains_pgvector_image():
    assert "pgvector/pgvector" in README.read_text(encoding="utf-8")


def test_readme_contains_resume_rag_mode_rollback():
    text = README.read_text(encoding="utf-8")
    assert "RESUME_RAG_MODE=off" in text
    assert "RESUME_RAG_MODE=shadow" in text


def test_rollout_doc_lists_per_mode_thresholds():
    text = RUNBOOK.read_text(encoding="utf-8")
    assert "Mode A" in text and "≥ 70%" in text
    assert "Mode B" in text and "≥ 55%" in text
    assert "Mode C" in text and "≥ 40%" in text
```

- [ ] Run docs tests.

```bash
python -m pytest tests/unit/test_resume_rag_rollout_docs.py -q
```

- [ ] Commit.

```bash
git add ai-interviewer/backend/app/core/settings.py ai-interviewer/docs/RESUME_RAG_ROLLOUT.md ai-interviewer/backend/README.md ai-interviewer/backend/tests/unit/test_resume_rag_rollout_docs.py
git commit -m "feat: enable resume rag shadow by default with rollout runbook"
```

## Task 8: Privacy + Cross-Session Isolation Dedicated Suite

**Files:**

- Create: `ai-interviewer/backend/tests/unit/test_resume_rag_isolation.py`
- Create: `ai-interviewer/backend/tests/unit/test_resume_rag_pii.py`

- [ ] R1 cross-session isolation test (multi-scenario):

```python
def test_cross_session_query_never_returns_other_session_chunks(db_session):
    # Insert two sessions with very similar content and the same revision id.
    # Query session_A/rev_1 must not include session_B/rev_1 chunks even when
    # session_B has a higher cosine score.


def test_revision_filter_rejects_same_session_old_revision(db_session):
    # Insert sess_a/rev_old and sess_a/rev_new chunks.
    # Query sess_a/rev_new must not include rev_old chunks.


def test_session_and_revision_filters_are_both_required(db_session):
    # Removing either filter in the retriever should make this test fail:
    # one planted row differs only by session_id, the other only by revision_id.
```

- [ ] R2 PII redaction test:

```python
def test_phone_numbers_are_redacted_before_storing():
    raw = "联系电话 13800001111, alex@example.com, Redis 项目负责人"
    vectorize_resume(
        session_id="sess_a",
        resume_revision_id="rev_1",
        source_artifact_id="artifact_1",
        raw_text=raw,
        parsed=None,
        db_session=db_session,
    )
    rows = db_session.scalars(select(ResumeChunk).where(ResumeChunk.session_id == "sess_a")).all()
    for row in rows:
        assert "13800001111" not in row.text
        assert "alex@example.com" not in row.text


def test_id_card_numbers_are_redacted_before_storing():
    raw = "身份证 32010119900101003X, Redis 项目负责人"
    vectorize_resume(
        session_id="sess_a",
        resume_revision_id="rev_1",
        source_artifact_id="artifact_1",
        raw_text=raw,
        parsed=None,
        db_session=db_session,
    )
    for row in rows:
        assert "32010119900101003X" not in row.text


def test_subject_deletion_wipes_all_traces(client_with_token, db_session):
    seed_session_chunks("sess_x")
    r = client_with_token.delete("/admin/sessions/sess_x/resume-data")
    assert r.status_code == 200
    rows = db_session.scalars(select(ResumeChunk).where(ResumeChunk.session_id == "sess_x")).all()
    assert rows == []
```

- [ ] Run the isolation suite.

```bash
python -m pytest tests/unit/test_resume_rag_isolation.py tests/unit/test_resume_rag_pii.py -q
```

Expected: every cross-session attempt is blocked; every PII pattern is redacted; subject deletion is complete.

- [ ] Commit.

```bash
git add ai-interviewer/backend/tests/unit/test_resume_rag_isolation.py ai-interviewer/backend/tests/unit/test_resume_rag_pii.py
git commit -m "test: harden resume rag isolation and pii"
```

## Task 9: Final Regression and Deployment Wiring

**Files:**

- No new files expected.
- Modify if APScheduler is already wired: `ai-interviewer/backend/app/main.py` to register the cleanup job with APScheduler.

- [ ] Register the cleanup job (if APScheduler is already wired). If not, document the cron command in the runbook.

- [ ] Run backend full unit tests.

```bash
cd D:\Agent\Agentic_Interviewer\ai-interviewer\backend
python -m pytest tests/unit -q
```

Expected: all tests pass.

- [ ] Run targeted lint.

```bash
python -m ruff check \
  app/models/resume_anchor.py \
  app/services/resume_chunker.py \
  app/services/resume_embedding.py \
  app/services/resume_parse_artifacts.py \
  app/services/resume_vectorize.py \
  app/services/resume_retriever.py \
  app/services/resume_parse_jobs.py \
  app/api/v1/interview.py \
  app/engine/workflow/nodes/ask_question.py \
  app/engine/workflow/plans/ask_plans.py \
  app/engine/agents/generator.py \
  app/api/v1/admin.py \
  app/scripts/cleanup_resume_chunks.py \
  tests/unit/test_resume_*.py
```

Expected: `All checks passed!`

- [ ] Run frontend source/type checks.

```bash
cd D:\Agent\Agentic_Interviewer\ai-interviewer\frontend
npm test -- tests/adminObservabilitySource.test.js
npm run typecheck
npm run lint
```

Expected: tests pass, typecheck passes. Pre-existing lint warnings may remain if unrelated.

- [ ] Run end-to-end workflow regression for both seed-hit and seed-miss paths.

```bash
python -m pytest tests/unit/test_ask_question_selection_artifacts.py -q
```

Expected: each plan template produces both `resume_anchor` and `resume_anchor_rag` artifacts as part of `selection_artifacts`.

- [ ] Diff cleanliness.

```bash
git diff --check
```

Expected: no whitespace errors.

- [ ] Verify Admin parity in a local Postgres run.

  - Start backend with `RESUME_RAG_MODE=shadow`.
  - Upload a resume and run one interview turn.
  - Open Admin, confirm:
    - Total chunks > 0.
    - Per-mode breakdown matches expected mode for the uploaded resume.
    - One hit recorded for the run with `latency_ms` populated.

- [ ] Commit any final adjustments.

```bash
git add .
git commit -m "test: finalize resume anchor rag rollout"
```

## Future Phases (Explicitly Deferred)

These are intentionally not in scope for this plan:

- **Knowledge RAG revival.** Industry docs / failure case library / cross-candidate high-scoring answers. Separate plan once Shadow data shows the resume-anchor path is stable.
- **Local embedding model swap.** Considered if Shadow data shows remote latency p99 > 350ms consistently, or if Chinese semantic recall on Mode A is below the 70% threshold. First choice would be BGE-small-zh-v1.5 (340 MB), not BGE-M3.
- **Parallel `retrieve_strategy` + `retrieve_resume_anchor`.** Needs independent SQLAlchemy sessions and benchmark proof that the saved 200ms is worth the complexity.
- **Evaluator-feedback-driven dynamic query.** Use the evaluator's "what was missing" signal to steer the next-turn query. Requires the evaluator already runs before ask_question.
- **ChromaVectorStore removal.** Will land in a `RAG-cleanup` plan after this RAG path is in primary and all callers verified.
- **Evaluator runtime consumption of playbook `score_bias_rules`.** Belongs to the Skills playbook track, not this plan.

## Acceptance Criteria

This plan is complete only when:

- `pgvector` extension is created on the configured Postgres at init.
- `resume_chunks` ORM model round-trips with HNSW index.
- The chunker correctly classifies all four fixture resumes into modes A/B/C/D.
- Resume upload/parse creates a short-lived `resume_source_id` artifact and does not require a session id.
- `POST /sessions` binds `resume_source_id` to `session_id`, runs `vectorize_resume` serially, and writes `candidate.resume_vector_status`.
- `resume_parse` job `completed` means the setup artifact is ready; only `candidate.resume_vector_status.status == "ready"` means resume RAG is queryable.
- `_step_retrieve_resume_anchor` is wired into every relevant plan template with `optional=True`.
- `challenge_with_reference` prefers `resume_rag_block` first line over `retrieval_block`.
- Generator prompt includes the `resume_rag_block` slot, placed AFTER `resume_anchor` and BEFORE `strategy_block`.
- Cross-session isolation passes: a query for session_A never recalls session_B chunks even when scores are higher.
- PII redaction passes: phone numbers, emails, ID cards are absent from stored chunks.
- Subject deletion fully wipes a session's resume data on demand.
- Admin panel shows per-mode chunk counts, hit rate, latency, fallback reasons.
- Cleanup job removes expired chunks idempotently.
- Default `resume_rag_mode=shadow` after Task 7; `off` remains the documented rollback.
- README and `RESUME_RAG_ROLLOUT.md` document the rollout, rollback, and per-mode thresholds.
- Full backend unit tests pass.
- Frontend source tests, typecheck pass.

## Implementation Notes For Future Agent

- Do not use a new worktree unless the user explicitly asks. This project has already standardized on `D:\Agent\Agentic_Interviewer` as the only running workspace.
- Do not modify `.cursor` files unless the user explicitly asks.
- Do not change `select_resume_anchor` rule-based logic. The new RAG block is **additive**, not replacing.
- Keep `ChromaVectorStore` and its callers untouched. A dedicated future plan will remove them.
- Keep the OpenAI-compatible embedding client free of hard `openai` package dependency — `httpx` only, so the endpoint can be swapped per environment.
- Always run `redact_pii` before computing the embedding and before persisting the chunk text. Never embed raw text.
- The `embedding_model_version` field is the single source of truth for vector-space compatibility. Never query across versions.
- Mode D resumes never enter the vector store. Tests must continue to assert this so we do not accidentally vectorize an `< 500` char resume.
- Resume re-upload/new binding must create a new `resume_revision_id`; retrieval must filter by the active revision and never fall back to older revision chunks.
