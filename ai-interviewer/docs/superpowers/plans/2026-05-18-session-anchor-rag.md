# Candidate Session Anchor RAG Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Re-activate the dormant RAG module by giving it one real, high-value job: semantic retrieval of session-scoped candidate anchors from the resume and long opening self-introduction, so the Generator can ask follow-up questions grounded in the candidate's actual experience instead of generic templates.

**Architecture:** Build a session-scoped candidate-anchor vector store on PgVector (same Postgres instance as the existing tables). Treat resume upload parsing as a pre-session parse artifact, bind that artifact to `session_id` inside `POST /sessions`, and vectorize resume anchors before the workflow starts. Parse the opening self-introduction in the existing `self_intro_parser` LLM call; if it is long enough, extract bounded `anchor_cards` and vectorize them after `self_intro_parse_node`, before the first formal `ask_question`. Add a `_step_retrieve_candidate_anchors` step before `draft_question`; it retrieves resume and self-intro anchors with source-aware revision filters, source quotas, and separate prompt slots. Ship through `off -> shadow -> primary` rollout. Keep the existing rule-based `select_resume_anchor` intact and complementary.

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
  - Historical node name. Today it does not parse raw resume bytes; it only locks in rubric/dimensions from the already-submitted structured request. This plan expands the node's responsibility: it will additionally consume the parse artifact (one-shot) and call `vectorize_resume` so the resume RAG is queryable by the time `ask_question_node` runs. The 300-600 ms vectorize cost is hidden behind the 60-120 s self-intro speaking window that follows immediately, so user-perceived latency stays unchanged.
- `ai-interviewer/backend/app/engine/resume_plan.py`
  - `select_resume_anchor` rule-based selector. Reads `candidate.resume_parsed.{projects, focus_areas}`, picks a single anchor by `(self_intro_match, dimension_match, unused, priority)`.
- `ai-interviewer/backend/app/engine/agents/self_intro.py`
  - Parses the first user answer into `self_intro_profile` with one LLM call and a deterministic fallback. Existing heuristic marks `< 40` chars as unclear and treats `>= 120` chars with structure markers as clear.
- `ai-interviewer/backend/app/engine/workflow/nodes/self_intro.py`
  - Runs after the opening answer, stores `self_intro_answer` and `self_intro_profile`, then advances to the first formal question path. This is the correct lifecycle point for long self-intro anchor-card vectorization.
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

Re-activate RAG with one well-scoped role: **session-scoped candidate semantic anchor retrieval**, not generic knowledge.

- Use PgVector on the existing Postgres (same instance as `question_seeds`, `skill_playbook_cards`, etc.).
- Keep the dormant ChromaVectorStore code as a labelled dead-code path. Cleanup belongs to a separate `RAG-cleanup` plan once this resume RAG path is in primary.
- Keep the existing rule-based `select_resume_anchor` and add **additive** semantic blocks. The Generator sees the rule anchor, resume recall, and self-intro recall as separate source-labelled signals.
- Do **not** vectorize inside `ResumeParseJobManager._run_job`: the parse job has no `session_id`. Persist a short-lived parse artifact to the new `resume_parse_artifacts` Postgres table at upload/parse time, pass `resume_source_id` through setup, validate it (read-only) in `POST /sessions` so the synchronous HTTP path adds no embedding latency, and consume + vectorize the artifact inside `resume_parse_node` where both `session_id` and the raw text are available. Raw resume text never enters the LangGraph state. `resume_parse.completed` means "structured extraction is ready"; `candidate.resume_vector_status.status == "ready"` means "resume RAG is queryable"; the intermediate `status == "pending_node"` means "artifact stamped, awaiting `resume_parse_node`."
- Do **not** add a second LLM call for self-intro anchors. Extend the existing `parse_self_intro_profile` response schema with bounded `anchor_cards`, clean them, and vectorize only when the sanitized self-intro is long enough.
- Treat short self-intros as query-side/profile signals only. Treat long self-intros as a separate `source_type="self_intro"` evidence source, never as resume facts.

## Boundaries

In scope:

- PgVector enablement (extension + ORM model + index).
- Self-adaptive resume chunker with 4 modes (A/B/C/D).
- Long self-introduction anchor-card extraction in the existing `self_intro_parser` call.
- Session-scoped self-intro anchor vectorization when `len(sanitized_self_intro) >= session_anchor_self_intro_min_chars`.
- Strict PII redaction before vectorization.
- Session + source-revision scoped filtering.
- New `_step_retrieve_candidate_anchors` step in all relevant plan templates.
- `challenge_with_reference` switch from `retrieval_block` to `resume_rag_block`, then `self_intro_rag_block` when no resume recall is available.
- Generator prompt `resume_rag_block` and `self_intro_rag_block` slots.
- Shadow → Primary rollout switch with per-mode hit-rate thresholds.
- Admin observation panel with mode-grouped metrics.
- Subject-deletion admin endpoint for all session-scoped anchors.
- Soft retention (`session lifetime + 24h`) plus periodic cleanup job.
- Embedding model version field for forward-compatible migration.

Out of scope:

- Knowledge RAG (industry docs, sample answers, etc.) — separate future plan.
- ChromaVectorStore removal — separate future cleanup plan.
- Evaluator runtime consumption of `evaluator_rubric_hints` / `score_bias_rules` (Skills playbook feature, separate plan).
- Cross-candidate query (always forbidden, double-filtered).
- Cross-session candidate memory (self-intro anchors expire with the session, just like resume anchors).
- Mid-interview ad hoc claim extraction (`source_type="adhoc_claim"`) — Future Phase only.
- Multi-language embedding switch (stay on the configured OpenAI-compatible endpoint until Shadow data motivates a change).
- Parallel execution of retrieve_strategy and retrieve_candidate_anchors (kept serial in P0).
- LLM-based dynamic query enhancement using evaluator feedback (deferred until Shadow data shows the basic query underperforms).
- Mid-interview resume swap (C4): re-uploading a resume during an ongoing interview is out of scope. The supported flow is "end the current session, start a new session with the new resume." No `PUT /sessions/{id}/resume` endpoint is added in P0; `resume_revision_id` remains a forward-compatible field for that future feature.

## Risk Points

Critical:

- **R1 Cross-candidate leakage.** A `session_A` query must never recall `session_B` chunks. Enforced by namespace + metadata filter + dedicated unit tests.
- **R2 PII reverse-engineering from embeddings.** Short-text embeddings can leak partial originals. Mitigation: all chunks pass `redact_pii` before ingestion. Original text is still stored for prompt rendering convenience (the practical reversal risk is bounded by redaction, and an extra DB hit on every retrieval is worse).
- **R3 Right to be forgotten.** A candidate-driven delete must wipe `session_anchor_chunks` rows, `resume_parse_artifacts` rows for any parse artifact still bound to the session (whether consumed or not), setup snapshots / current question payloads containing resume- or self-intro-derived material, short-lived self-intro anchor artifacts, and any cached artifacts. Dedicated admin endpoint + dedicated test.
- **R3b Session binding gap.** Resume upload parse happens before `session_id` exists. Do not write session-scoped chunks from the parse job. Persist a short-lived parse artifact to the `resume_parse_artifacts` Postgres table, validate (read-only) the supplied `resume_source_id` inside `POST /sessions`, then consume the artifact exactly once inside `resume_parse_node` where `session_id` is also available. Cross-worker deployments stay correct because the artifact lives in shared Postgres, not in any process-local dict.

High:

- **R4 Embedding model version drift.** Remote providers periodically update underlying models. The vector space silently shifts. Mitigation: `embedding_model_version` column; query must match the column value of stored chunks; degradation goes to rule anchor.
- **R5 Cascade from parse failure.** If `resume_parser` fails, `resume_parsed` is empty. The chunker still works directly on raw text — no hard dependency on `parsed`. The vectorize step is skipped if no text is available.
- **R6 Low-quality recall pollutes Generator prompt.** Threshold is set strict (`0.45` cosine). Below-threshold recalls drop. Prompt template adds defensive lines: "If the resume_rag_block or self_intro_rag_block appears irrelevant, ignore it."
- **R7 Missing `seed.scenario_brief`.** Some legacy seeds may not declare it. Fallback query formula: `scenario_brief OR title OR intent`.

Medium:

- **R8 Test reproducibility.** Remote embedding is non-deterministic. Unit tests mock embeddings with fixed vectors. E2E smoke tests are isolated.
- **R9 Cost / size monitoring.** Daily embedding call count + PG `session_anchor_chunks` row count surface as admin metrics. Cleanup job removes expired rows daily.
- **R10 Trace replay.** Once a session's chunks are cleaned, trace replay can show the recall ids, scores, source type, and optional short redacted excerpts, but cannot re-run the query. Do not store full resume or self-intro chunks in trace artifacts.
- **R11 Rollout staging.** `resume_rag_mode: Literal["off", "shadow", "primary"] = "off"` plus an optional `resume_rag_session_sample_rate: float = 1.0` for gradual ramp.
- **R12 Re-uploaded resume / revision drift.** If a candidate binds a newer resume artifact to the same session, create a new resume `source_revision_id`. Retrieval must filter by `session_id + source_type + source_revision_id + embedding_model_version`; if vectorization of the new revision fails, fallback to rule anchor rather than querying old revision chunks.
- **R12b Self-intro vectorize failure.** `vectorize_self_intro_anchor_cards` can fail independently of resume vectorization (LLM card cleaning failure, embedding 429 after retries exhausted, transient PG outage). When it does, `self_intro_vector_status.status = "failed"` and the retriever queries only the resume source for the session. `self_intro_profile` (the structured signal already used by Generator and `select_resume_anchor`) remains available, so the interview never loses access to the candidate's spoken emphasis even when its semantic anchor source is offline. The node MUST NOT raise the embedding error to its workflow caller — the graph keeps running on rule anchor + resume RAG only.
- **R15 Source contamination.** A self-intro claim may not appear in the resume. The retriever and Generator must keep `resume_rag_block` and `self_intro_rag_block` separate so the prompt never phrases a self-intro-only claim as "your resume says". Conflicts trigger clarification, not silent merge.
- **R16 Long self-intro cost growth.** Long spoken answers can produce noisy chunks. Mitigation: `session_anchor_self_intro_min_chars=200`, `session_anchor_self_intro_max_cards=8`, `session_anchor_self_intro_card_max_chars=500`, one chunk per cleaned anchor card, and no extra LLM call.

Low:

- **R13 Chinese vs English vs mixed resume.** OpenAI-compatible models handle mixed content acceptably. Future migration to a Chinese-strong local model is decided post-Shadow.
- **R14 Generator prompt length growth.** Cap `resume_rag_block` at 800 characters. Monitor mean/p99 prompt length.

## Data Model

Create `ai-interviewer/backend/app/models/session_anchor.py`:

```python
class SessionAnchorChunk(Base):
    __tablename__ = "session_anchor_chunks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(96), index=True)
    source_type: Mapped[str] = mapped_column(String(32), index=True)
    source_revision_id: Mapped[str] = mapped_column(String(96), index=True)
    source_artifact_id: Mapped[str | None] = mapped_column(String(96), index=True, nullable=True)
    source_turn_id: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)
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
    embedding: Mapped[list[float]] = mapped_column(
        Vector(int(get_settings().resume_rag_embedding_dimension or 1536))
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), index=True
    )
```

Notes:

- `source_type in {"resume", "self_intro"}` in P0. `adhoc_claim` is reserved for the Future Phase below.
- For resume rows: `source_revision_id == candidate.resume_vector_status.resume_revision_id`, `source_artifact_id == resume_source_id`, `source_turn_id is None`.
- For self-intro rows: `source_revision_id == state.self_intro_vector_status.self_intro_revision_id`, `source_artifact_id is None`, `source_turn_id == the opening self-intro turn_idx`.
- `tier in {"project", "highlight", "skill", "section", "window", "full", "anchor_card"}`. The first six are resume tiers. `anchor_card` is used for self-intro anchor cards.
- `chunker_mode in {"A", "B", "C", "D", "SI"}` for grouped metrics. `SI` means self-introduction anchor cards.
- `embedding` is `pgvector.sqlalchemy.Vector`. The dimension is read once at import time from `get_settings().resume_rag_embedding_dimension` (default 1536 for OpenAI `text-embedding-3-small`). Switching to a different embedding model also requires updating that setting; the Task 1 sanity test pins ORM dim and the active settings dim to the same value to prevent silent drift.
- HNSW index on `embedding` with `vector_cosine_ops`; B-tree composite index on `(session_id, source_type, source_revision_id, embedding_model_version, tier)`.
- The retriever must never query a source without matching `source_type + source_revision_id`, even inside the same session. Resume and self-intro revisions are independent.
- `source_artifact_id` points back to the short-lived setup parse artifact for resume audit/debug only. It is nullable because self-intro and legacy/manual setup flows do not have a setup artifact.
- `expires_at` is set to `now + session_lifetime + 24h` at insert time; cleanup job deletes rows where `expires_at < now()`.
- Original chunk `text` is stored (R2 mitigation: redact upstream, accept the convenience trade-off).

Schema bootstrap in `init_db()` must:

1. Import `app.models.session_anchor` before `Base.metadata.create_all`.
2. Execute `CREATE EXTENSION IF NOT EXISTS vector;` against the engine (no-op if already installed).
3. Create the HNSW index via `Base.metadata.create_all` if SQLAlchemy supports it; otherwise add a guarded `CREATE INDEX IF NOT EXISTS` statement in `_POSTGRES_UPGRADES`.

## Settings

Add to `ai-interviewer/backend/app/core/settings.py`:

```python
resume_rag_mode: Literal["off", "shadow", "primary"] = "off"
session_anchor_top_k_resume: int = 2
session_anchor_top_k_self_intro: int = 1
resume_rag_distance_threshold: float = 0.45
resume_rag_timeout_ms: int = 300
resume_rag_block_max_chars: int = 800
resume_rag_min_text_chars: int = 500
session_anchor_self_intro_min_chars: int = 200
session_anchor_self_intro_max_cards: int = 8
session_anchor_self_intro_card_max_chars: int = 500
resume_rag_session_sample_rate: float = 1.0
resume_rag_session_ttl_hours: int = 24
resume_rag_parse_artifact_ttl_seconds: int = 3600
resume_rag_embedding_endpoint: str = "https://api.openai.com/v1"
resume_rag_embedding_model: str = "text-embedding-3-small"
resume_rag_embedding_dimension: int = 1536
resume_rag_embedding_api_key: str = ""
resume_rag_embedding_concurrency: int = 4
resume_rag_embedding_max_retries: int = 3
resume_rag_embedding_retry_backoff_seconds: float = 1.0
resume_rag_used_project_penalty: float = 0.05
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

- [ ] Pin `_retrieval_block_for_prompt` empty-on-seed-hit semantics (C3 contract). Future refactors that accidentally pass the new `resume_rag_block` / `self_intro_rag_block` through this helper will trip both this baseline and the C3 anchor-block-survives test added in Task 5.

```python
def test_retrieval_block_for_prompt_returns_empty_on_seed_hit():
    ctx = {"structured_primary_seed_hit": True, "retrieval_block": "something"}
    assert _retrieval_block_for_prompt(ctx) == ""

def test_retrieval_block_for_prompt_returns_block_without_seed_hit():
    ctx = {"structured_primary_seed_hit": False, "retrieval_block": "knowledge body"}
    assert _retrieval_block_for_prompt(ctx) == "knowledge body"
```

- [ ] Pin that `_step_select_structured_question` consumes the **rule** anchor only (D8 contract). RAG hits must never reach seed selection or `build_question_fit_profile` in P0; if a future change wires them in, this baseline fails.

```python
def test_step_select_structured_question_uses_rule_anchor_only(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        "app.engine.workflow.nodes.ask_question.select_question_candidates",
        lambda **kwargs: captured.setdefault("kwargs", kwargs) or [],
    )
    monkeypatch.setattr(
        "app.engine.workflow.nodes.ask_question.build_question_fit_profile",
        lambda **kwargs: captured.setdefault("fit_kwargs", kwargs) or {},
    )
    state = _ready_state()
    ctx = {
        "dimension": "system_design",
        "resume_anchor": {"project_name": "智学", "tech_stack": ["Redis"]},
        # These keys are written by `_step_retrieve_candidate_anchors`
        # in later turns. P0 must NOT pass them upstream.
        "resume_rag_block": "[resume] Redis Lua coupon guard",
        "self_intro_rag_block": "[self_intro] 50w QPS Lua atomic",
        "candidate_anchor_rag_artifact": {"status": "primary"},
    }
    _step_select_structured_question(state, ctx, probe_intent=None)
    assert captured["kwargs"]["resume_anchor_text"]  # uses rule anchor
    assert "resume_rag_block" not in captured["kwargs"]
    assert "self_intro_rag_block" not in captured["kwargs"]
    assert "candidate_anchor_rag_artifact" not in captured["kwargs"]
    assert "resume_rag_block" not in captured["fit_kwargs"]
    assert "self_intro_rag_block" not in captured["fit_kwargs"]
```

- [ ] Pin that `selection_artifacts` keys evolve as a strict superset: every existing key keeps appearing after `candidate_anchor_rag` is added in Task 5. Drops are caught here before the change reaches admin / trace replay consumers.

```python
def test_selection_artifacts_baseline_keys_superset_after_rag():
    ctx = _seed_hit_ctx()
    artifacts = _build_selection_artifacts(ctx)
    expected_baseline = {
        "rag",
        "strategies",
        "skills",
        "avoid_patterns",
        "question_items",
        "failure_categories",
    }
    assert expected_baseline.issubset(set(artifacts.keys()))
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
- Create: `ai-interviewer/backend/app/models/session_anchor.py`
- Modify: `ai-interviewer/backend/app/models/__init__.py`
- Modify: `ai-interviewer/backend/app/models/base.py`
- Modify: `ai-interviewer/backend/docker-compose.yml` (or equivalent) to use `pgvector/pgvector:pg17` image
- Create: `ai-interviewer/backend/tests/unit/test_session_anchor_chunk_model.py`

- [ ] Pin the pgvector Python dependency.

```text
# requirements.txt
pgvector==0.3.6
```

- [ ] Implement the ORM model per the Data Model section. Use `pgvector.sqlalchemy.Vector`.

- [ ] Add `app.models.session_anchor` to the import chain in `app/models/__init__.py`.

- [ ] Update `init_db()` to issue `CREATE EXTENSION IF NOT EXISTS vector;` before `Base.metadata.create_all`.

- [ ] Add a guarded HNSW index creation. If using `_POSTGRES_UPGRADES`, add:

```python
("session_anchor_chunks", "embedding_hnsw_cosine"): (
    "CREATE INDEX IF NOT EXISTS ix_session_anchor_chunks_embedding_hnsw "
    "ON session_anchor_chunks USING hnsw (embedding vector_cosine_ops);"
)
```

- [ ] Add a SQLite-skip guard: SQLite cannot satisfy pgvector, so the resume RAG model must be skipped at table creation when the engine is SQLite (development fallback). Tests must still assert the model is loadable.

- [ ] Update `docker-compose.yml` / `Dockerfile` to use `pgvector/pgvector:pg17` (or matching Postgres version with the extension).

- [ ] Write the round-trip test using a Postgres test container (or a `vector`-enabled Postgres available in CI).

```python
def test_session_anchor_chunk_round_trip_with_pgvector(pg_engine):
    Base.metadata.create_all(pg_engine)
    with Session(pg_engine) as s:
        s.add(SessionAnchorChunk(
            session_id="sess_a",
            source_type="resume",
            source_revision_id="rev_1",
            source_artifact_id="artifact_1",
            source_turn_id=None,
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
        row = s.scalar(select(SessionAnchorChunk).where(SessionAnchorChunk.session_id == "sess_a"))
    assert row.tier == "highlight"
    assert row.source_type == "resume"
    assert row.embedding[0] == pytest.approx(0.1)


def test_session_anchor_chunk_embedding_dim_matches_settings():
    """Pin ORM embedding dimension and active settings dimension together.

    Switching to a different embedding model requires updating
    ``resume_rag_embedding_dimension`` as well; this test fires loudly
    if either side drifts so the vector space is never silently
    corrupted (R4 model version drift defence in depth at the schema
    layer).
    """
    expected = int(get_settings().resume_rag_embedding_dimension or 1536)
    assert SessionAnchorChunk.__table__.c.embedding.type.dim == expected
```

- [ ] Run the model tests.

```bash
python -m pytest tests/unit/test_session_anchor_chunk_model.py -q
```

Expected: round trip passes against a pgvector-enabled Postgres.

- [ ] Commit.

```bash
git add ai-interviewer/backend/requirements.txt ai-interviewer/backend/app/models/session_anchor.py ai-interviewer/backend/app/models/__init__.py ai-interviewer/backend/app/models/base.py ai-interviewer/backend/docker-compose.yml ai-interviewer/backend/tests/unit/test_session_anchor_chunk_model.py
git commit -m "feat: add session anchor chunk model with pgvector"
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
    """Return the canonical `<model>@<version>` string written to SessionAnchorChunk."""
```

- [ ] Implementation rules:

  - Use the OpenAI-compatible REST endpoint configured by `resume_rag_embedding_endpoint`. Do not bind the implementation to the `openai` Python package — use `httpx` so the endpoint can be swapped to any OpenAI-protocol-compatible provider via settings alone.
  - Batch requests; cap batch size at 64.
  - A module-level `threading.Semaphore` initialised once from `get_settings().resume_rag_embedding_concurrency` (default 4) wraps every outbound embedding call so cross-session traffic cannot exhaust upstream rate limits. Both `embed_chunks` and `embed_query` acquire the same semaphore so they share one global budget. Single-session impact is unchanged because the two-stage vectorization (`resume_parse_node` then `self_intro_parse_node`) is already serial within a session; the cap protects against multi-session bursts.
  - Retry on `httpx.HTTPStatusError(429)`, `httpx.TimeoutException`, and `httpx.ConnectError` up to `get_settings().resume_rag_embedding_max_retries` (default 3) extra attempts. Exponential backoff: sleep `resume_rag_embedding_retry_backoff_seconds * (2 ** attempt)` seconds before each retry (default sequence 1s / 2s / 4s). All other HTTP error statuses raise immediately without retry.
  - `embed_chunks` raises `ResumeEmbeddingError` only after retries are exhausted.
  - `embed_query` is the production hot path: never raises, returns `None` so the call site only branches once. Log a single WARNING after retries are exhausted.
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


def test_embed_chunks_retries_on_429(mock_http):
    mock_http.add_post(
        "/embeddings",
        [_status_response(429), _ok_response(1)],
    )
    vectors = embed_chunks(["x"])
    assert len(vectors) == 1
    assert mock_http.call_count == 2


def test_embed_chunks_raises_after_retries_exhausted(mock_http):
    max_retries = int(get_settings().resume_rag_embedding_max_retries)
    mock_http.add_post("/embeddings", [_status_response(429)] * (max_retries + 1))
    with pytest.raises(ResumeEmbeddingError):
        embed_chunks(["x"])
    assert mock_http.call_count == max_retries + 1


def test_embed_chunks_semaphore_matches_settings_concurrency():
    """Pin the module-level semaphore cap to the configured concurrency.

    Defence in depth for D1: if the settings drift, the semaphore
    must drift with them so cross-session bursts never silently fan
    out beyond the configured upstream budget.
    """
    from app.services.resume_embedding import _embed_semaphore

    assert _embed_semaphore._value == int(
        get_settings().resume_rag_embedding_concurrency
    )
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

## Task 4: Parse Artifact Persistence + Session Anchor Vectorization in Workflow Nodes

**Design summary:**

The two-stage vectorization runs entirely inside LangGraph background nodes so user-perceived latency on `POST /sessions` stays unchanged (the `resume_parse_node` and `self_intro_parse_node` are not on the synchronous HTTP path):

- `POST /resume/parse` and `ResumeParseJobManager` write a short-lived parse artifact to a new `resume_parse_artifacts` Postgres table and return the `artifact_id`. They never call `vectorize_resume`.
- `POST /sessions` validates the supplied `resume_source_id` (read-only, does not consume) and stamps `candidate.resume_source_id` plus `candidate.resume_vector_status = {"status": "pending_node", ...}` into the workflow state. No vectorization runs synchronously on the HTTP request.
- `resume_parse_node` reads the artifact (one-shot consume, marks `consumed_at`), generates a fresh `resume_revision_id`, calls `vectorize_resume`, and writes the resulting `resume_vector_status` back into `state["candidate"]`. The whole 300-600 ms cost is hidden behind the 60-120 s self-intro speaking window before any RAG-consuming step runs.
- `self_intro_parse_node` calls `vectorize_self_intro_anchor_cards` after `parse_self_intro_profile` returns, writing `state["self_intro_vector_status"]`. Both stages are serialized within a single session; cross-session bursts are throttled by the embedding semaphore from Task 3.

Storing artifacts in Postgres (instead of a process-local dict) makes the contract durable across the multi-HTTP-request flow (`/resume/parse` → user review → `/sessions` → first node) and across multiple FastAPI workers. The raw resume text never enters the LangGraph state and is therefore not persisted by any checkpoint backend, keeping the R2 PII exposure surface as narrow as possible.

**Files:**

- Create: `ai-interviewer/backend/app/models/resume_parse_artifact.py`
- Create: `ai-interviewer/backend/app/services/resume_parse_artifacts.py`
- Create: `ai-interviewer/backend/app/services/session_anchor_vectorize.py`
- Modify: `ai-interviewer/backend/app/api/v1/interview.py`
- Modify: `ai-interviewer/backend/app/services/resume_parse_jobs.py`
- Modify: `ai-interviewer/backend/app/engine/agents/self_intro.py`
- Modify: `ai-interviewer/backend/app/engine/workflow/nodes/resume_parse.py`
- Modify: `ai-interviewer/backend/app/engine/workflow/nodes/self_intro.py`
- Modify: `ai-interviewer/backend/app/engine/workflow/state.py`
- Modify: `ai-interviewer/backend/app/models/__init__.py`
- Modify: `ai-interviewer/frontend/src/lib/api/types.ts`
- Modify: `ai-interviewer/frontend/src/components/interview/SetupForm.tsx`
- Modify: `ai-interviewer/frontend/src/lib/storage/setupDrafts.ts`
- Create: `ai-interviewer/backend/tests/unit/test_resume_parse_artifacts.py`
- Create: `ai-interviewer/backend/tests/unit/test_session_anchor_vectorize.py`
- Create: `ai-interviewer/backend/tests/unit/test_self_intro_anchor_cards.py`
- Create: `ai-interviewer/backend/tests/unit/test_resume_rag_session_binding.py`
- Create: `ai-interviewer/backend/tests/unit/test_resume_parse_node_vectorize.py`
- Modify: `ai-interviewer/backend/tests/unit/test_resume_parse_jobs.py`
- Modify: `ai-interviewer/backend/tests/unit/test_interview_setup_api_contract.py`
- Modify: `ai-interviewer/frontend/tests/resumeUpload.test.js`

### Task 4a: Postgres-backed parse artifacts

The artifact bridges setup-time resume parsing and node-scoped vectorization. Two HTTP requests and (in production) two different FastAPI workers may sit between `POST /resume/parse` and the first `resume_parse_node` invocation, so a process-local dict is not safe. The artifact stores **redacted text only**.

- [ ] Add the ORM model in `app/models/resume_parse_artifact.py`:

```python
class ResumeParseArtifact(Base):
    __tablename__ = "resume_parse_artifacts"

    artifact_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    redacted_text: Mapped[str] = mapped_column(Text, default="")
    parsed: Mapped[dict] = mapped_column(JSON, default=dict)
    filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    text_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), index=True
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), index=True
    )
    consumed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
```

Register the model in `app/models/__init__.py` so `init_db()` picks it up.

- [ ] Implement the service `resume_parse_artifacts.py`. Public API:

```python
@dataclass(frozen=True)
class ResumeParseArtifactPayload:
    artifact_id: str
    redacted_text: str
    parsed: dict[str, Any]
    filename: str | None
    text_sha256: str
    created_at: datetime
    expires_at: datetime
    consumed_at: datetime | None


def create_resume_parse_artifact(
    *,
    text: str,
    parsed: dict[str, Any],
    filename: str | None,
    db_session: Session | None = None,
) -> ResumeParseArtifactPayload:
    """Redact, persist, return a fresh artifact row."""


def read_resume_parse_artifact(
    artifact_id: str,
    *,
    db_session: Session | None = None,
) -> ResumeParseArtifactPayload | None:
    """Read without consuming. Returns ``None`` when missing, expired, or already consumed.
    Used by ``POST /sessions`` to validate the supplied source id before stamping
    state without committing the consume side effect."""


def consume_resume_parse_artifact(
    artifact_id: str,
    *,
    db_session: Session | None = None,
) -> ResumeParseArtifactPayload | None:
    """One-shot consume. Marks ``consumed_at = now()`` atomically and returns the
    payload. Returns ``None`` when missing, expired, or already consumed.
    Used by ``resume_parse_node`` to fetch the body exactly once."""


def cleanup_expired_resume_parse_artifacts(
    *,
    db_session: Session | None = None,
) -> int:
    """Delete rows where ``expires_at < now()``. Returns count deleted."""
```

- [ ] Implementation rules:

  - All public functions accept an optional `db_session`; production callers pass `None` to use the default session, tests pass an isolated session.
  - `create_resume_parse_artifact`: run `redact_pii` on the raw text, generate `artifact_id = secrets.token_urlsafe(24)`, set `expires_at = now() + max(60, settings.resume_rag_parse_artifact_ttl_seconds)`, set `consumed_at = None`, INSERT one row.
  - `read_resume_parse_artifact`: single SELECT filtered by `artifact_id`. Returns `None` if the row is missing, `expires_at <= now()`, or `consumed_at IS NOT NULL`.
  - `consume_resume_parse_artifact`: single UPDATE ... SET `consumed_at = now()` WHERE `artifact_id = :id AND consumed_at IS NULL AND expires_at > now()` RETURNING all columns. The row is not deleted so the cleanup job can audit consumption; expired rows are reaped by `cleanup_expired_resume_parse_artifacts`.
  - `redact_pii` runs before storage so the database never holds raw phone numbers / emails / ID cards even on disk.
  - All writes happen inside a single transaction; never raise to HTTP callers — log a WARNING and return `None` so callers fall back to rule anchor.

- [ ] Tests:

```python
def test_create_resume_parse_artifact_redacts_pii(db_session):
    artifact = create_resume_parse_artifact(
        text="Alex 13800001111 alex@example.com did Redis work.",
        parsed={"summary": "Redis work"},
        filename="resume.txt",
        db_session=db_session,
    )
    assert "13800001111" not in artifact.redacted_text
    assert "alex@example.com" not in artifact.redacted_text


def test_read_resume_parse_artifact_does_not_consume(db_session):
    artifact = create_resume_parse_artifact(
        text="Redis project", parsed={}, filename=None, db_session=db_session,
    )
    assert read_resume_parse_artifact(artifact.artifact_id, db_session=db_session) is not None
    assert read_resume_parse_artifact(artifact.artifact_id, db_session=db_session) is not None


def test_consume_resume_parse_artifact_is_one_shot(db_session):
    artifact = create_resume_parse_artifact(
        text="Redis project", parsed={}, filename=None, db_session=db_session,
    )
    first = consume_resume_parse_artifact(artifact.artifact_id, db_session=db_session)
    second = consume_resume_parse_artifact(artifact.artifact_id, db_session=db_session)
    assert first is not None and first.consumed_at is not None
    assert second is None


def test_read_returns_none_after_consume(db_session):
    artifact = create_resume_parse_artifact(
        text="Redis project", parsed={}, filename=None, db_session=db_session,
    )
    consume_resume_parse_artifact(artifact.artifact_id, db_session=db_session)
    assert read_resume_parse_artifact(artifact.artifact_id, db_session=db_session) is None


def test_cleanup_expired_resume_parse_artifacts_deletes_only_expired(db_session, monkeypatch):
    monkeypatch.setattr(
        "app.services.resume_parse_artifacts._now",
        lambda: datetime.now(UTC) - timedelta(hours=2),
    )
    old = create_resume_parse_artifact(
        text="old", parsed={}, filename=None, db_session=db_session,
    )
    monkeypatch.undo()
    fresh = create_resume_parse_artifact(
        text="fresh", parsed={}, filename=None, db_session=db_session,
    )
    deleted = cleanup_expired_resume_parse_artifacts(db_session=db_session)
    assert deleted == 1
    assert read_resume_parse_artifact(fresh.artifact_id, db_session=db_session) is not None
    assert read_resume_parse_artifact(old.artifact_id, db_session=db_session) is None


def test_artifact_cross_worker_simulation(db_engine):
    """Different SQLAlchemy Sessions (simulating different FastAPI workers)
    must see the same artifact when one writes and another reads."""
    with Session(db_engine) as writer:
        artifact = create_resume_parse_artifact(
            text="Redis", parsed={}, filename=None, db_session=writer,
        )
        writer.commit()
    with Session(db_engine) as reader:
        found = read_resume_parse_artifact(artifact.artifact_id, db_session=reader)
        assert found is not None
        assert found.redacted_text == artifact.redacted_text
```

### Task 4b: Session anchor vectorize helpers

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
    """Normalize -> chunk -> redact -> embed -> upsert resume rows.

    Returns a status payload:
        {
            "status": "ready" | "skipped" | "failed",
            "mode": "A" | "B" | "C" | "D",
            "chunk_count": int,
            "embedding_model_version": str,
            "skipped_reason": str | None,
            "error": str | None,
        }

    Writes chunks with ``source_type="resume"`` for the exact
    ``session_id`` + ``resume_revision_id``. Older revisions may remain until
    cleanup, but the retriever must never query them for the new revision.
    Never raises — failures are returned as ``status="failed"``.
    """


def vectorize_self_intro_anchor_cards(
    *,
    session_id: str,
    self_intro_revision_id: str,
    turn_idx: int,
    sanitized_answer: str,
    anchor_cards: list[dict[str, Any]],
    db_session: Session | None = None,
) -> dict[str, Any]:
    """Clean -> redact -> embed -> upsert opening self-intro anchor cards.

    Returns ``status="skipped", skipped_reason="skipped_short"`` when the
    sanitized answer is shorter than ``session_anchor_self_intro_min_chars``.
    Uses ``source_type="self_intro"``, ``source_revision_id`` equal to the
    supplied self-intro revision, ``source_turn_id`` equal to the opening turn,
    ``tier="anchor_card"``, and ``chunker_mode="SI"``.
    """
```

- [ ] Implementation rules:

  - Always run inside a single transaction.
  - Resume Mode D returns `status="skipped", skipped_reason="mode_d_minimal_resume"`. No DB writes.
  - Self-intro text shorter than `session_anchor_self_intro_min_chars` returns `status="skipped", skipped_reason="skipped_short"`. No DB writes.
  - Self-intro cards are capped by `session_anchor_self_intro_max_cards`; each card `text` is capped by `session_anchor_self_intro_card_max_chars`.
  - If the LLM returns no usable self-intro cards, build 1-3 conservative cards from `summary`, `emphasized_projects`, and `emphasized_skills`; if those are still empty, use the sanitized self-intro answer as one fallback card.
  - Vectorize failure (embedding error) returns `status="failed"` and rolls back the transaction so no half-state remains.
  - Do not reuse previous chunks after failure. The active resume `source_revision_id` recorded on `candidate.resume_vector_status` and the active self-intro `source_revision_id` recorded on `state["self_intro_vector_status"]` are the only revisions the retriever may query.
  - Compute `expires_at = now() + session_ttl + 24h` for each row.
  - Use `redact_pii` on each chunk text before storing/embedding even though the parse artifact was already redacted.
  - Return `resume_revision_id`, `self_intro_revision_id`, `source_type`, `source_artifact_id`, `embedding_model_version`, and `text_sha256` when available.

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

### Task 4d: Stamp `resume_source_id` during `POST /sessions` (no vectorization)

`POST /sessions` must stay on the synchronous HTTP path with no extra LLM / embedding latency. The artifact is only **validated** here, not consumed; the workflow node consumes it later. If validation fails (missing or expired artifact), the session still succeeds and falls back to the rule-based `select_resume_anchor`.

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

- [ ] In `start_session`, after `translate_request(req.model_dump(exclude_none=False))` returns `session_id` and before `manager.start`, stamp the artifact id and a pending vector status into the initial workflow state. **Do not call `vectorize_resume` here.**

```python
def _stamp_resume_source_for_session(
    *,
    resume_source_id: str | None,
) -> dict[str, Any]:
    if not resume_source_id:
        return {
            "status": "skipped",
            "skipped_reason": "no_parse_artifact",
            "resume_source_id": None,
            "resume_revision_id": None,
        }
    artifact = read_resume_parse_artifact(resume_source_id)
    if artifact is None:
        return {
            "status": "skipped",
            "skipped_reason": "parse_artifact_missing_or_expired",
            "resume_source_id": resume_source_id,
            "resume_revision_id": None,
        }
    return {
        "status": "pending_node",
        "resume_source_id": artifact.artifact_id,
        "resume_revision_id": None,
        "expires_at": artifact.expires_at.isoformat(),
    }
```

- [ ] Store the stamped status on the workflow state and setup snapshot:

```python
vector_status = _stamp_resume_source_for_session(
    resume_source_id=req.resume_source_id,
)
candidate = initial.setdefault("candidate", {})
candidate["resume_vector_status"] = vector_status
if vector_status.get("status") == "pending_node":
    candidate["resume_source_id"] = vector_status["resume_source_id"]
setup_snapshot["resume_vector_status"] = vector_status
```

- [ ] `POST /sessions` always succeeds regardless of artifact state. Failure modes:
  - No `resume_source_id` provided → `skipped/no_parse_artifact`; node skips vectorize.
  - `resume_source_id` invalid or expired → `skipped/parse_artifact_missing_or_expired`; node skips vectorize. Interview proceeds with rule anchor only.
  - Artifact valid → `pending_node`; `resume_parse_node` will consume + vectorize.

### Task 4d2: Vectorize resume inside `resume_parse_node`

`resume_parse_node` already runs first in the LangGraph topology before any user-facing prompt. It now also owns resume vectorization. The 300-600 ms cost hides behind the immediately following 60-120 s self-intro speaking window, so no consuming step (ask_question) sees a not-ready resume in practice.

- [ ] Modify `app/engine/workflow/nodes/resume_parse.py`:

```python
def resume_parse_node(state: InterviewState) -> dict[str, Any]:
    job_spec = state.get("job_spec", {})
    dims = list(job_spec.get("rubric_dimensions") or state.get("dimensions") or [])
    if not dims:
        dims = ["technical_depth", "problem_solving", "communication"]
    rubric = job_spec.get("rubric") or {d: f"Assess {d.replace('_', ' ')}." for d in dims}
    status = state.get("dimension_status") or {d: "pending" for d in dims}

    candidate = state.get("candidate") or {}
    resume_vector_status = _vectorize_resume_for_node(
        session_id=str(state.get("session_id") or ""),
        candidate=candidate,
    )

    log.info(
        "resume_parse: session=%s dims=%s title=%r vector_status=%s",
        state.get("session_id"),
        dims,
        job_spec.get("title"),
        resume_vector_status.get("status"),
    )
    try:
        get_tracer().trace_session_started(dict(state))
    except Exception as e:  # pragma: no cover
        log.warning("tracer.trace_session_started failed: %s", e)

    return {
        "dimensions": dims,
        "rubric": rubric,
        "dimension_status": status,
        "scores_per_dim": state.get("scores_per_dim") or {d: None for d in dims},
        "candidate": {**candidate, "resume_vector_status": resume_vector_status},
    }


def _vectorize_resume_for_node(
    *,
    session_id: str,
    candidate: dict[str, Any],
) -> dict[str, Any]:
    """One-shot consume the parse artifact and vectorize. Never raises;
    all failure modes are folded into the returned status payload so the
    workflow keeps going on rule anchor."""
    prior = candidate.get("resume_vector_status") or {}
    source_id = candidate.get("resume_source_id") or prior.get("resume_source_id")
    if not source_id:
        return {
            "status": "skipped",
            "skipped_reason": prior.get("skipped_reason") or "no_parse_artifact",
            "resume_source_id": None,
            "resume_revision_id": None,
        }
    artifact = consume_resume_parse_artifact(source_id)
    if artifact is None:
        return {
            "status": "skipped",
            "skipped_reason": "parse_artifact_missing_or_expired",
            "resume_source_id": source_id,
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

- [ ] Implementation rules:

  - `resume_parse_node` must continue to return its existing keys (`dimensions / rubric / dimension_status / scores_per_dim`). Vectorize side effects do not change those values; they only add `resume_vector_status` under `candidate`.
  - `_vectorize_resume_for_node` must never raise. Any unexpected exception is caught and returned as `{"status": "failed", "error": str(exc), "resume_source_id": source_id, "resume_revision_id": None}` so downstream nodes can fall back to rule anchor without dropping the whole graph.
  - `consume_resume_parse_artifact` is intentionally called inside the node (not in `start_session`), so the one-shot consume side effect happens only after `manager.start` has actually launched the graph; a failed `manager.start` leaves the artifact reusable until its TTL expires.
  - The artifact row is not deleted by consume; cleanup remains responsibility of `cleanup_expired_resume_parse_artifacts` (Task 6c).
  - Raw resume text never enters `state`. After `vectorize_resume` returns, `artifact.redacted_text` falls out of scope; only the structured `resume_vector_status` (containing `resume_revision_id`, chunk counts, mode, error metadata) is written back into `state["candidate"]`.

- [ ] Tests in `test_resume_parse_node_vectorize.py`:

```python
def test_resume_parse_node_vectorizes_when_source_id_present(monkeypatch, db_session):
    artifact = create_resume_parse_artifact(
        text=HIGH_STRUCTURE_TEXT, parsed={"summary": "Redis"}, filename="r.md",
        db_session=db_session,
    )
    monkeypatch.setattr(
        "app.engine.workflow.nodes.resume_parse.vectorize_resume",
        lambda **kw: {
            "status": "ready", "mode": "A", "chunk_count": 12,
            "resume_revision_id": kw["resume_revision_id"],
            "embedding_model_version": "text-embedding-3-small@v1",
        },
    )
    state = {
        "session_id": "sess_a",
        "job_spec": {"title": "Backend"},
        "candidate": {"resume_source_id": artifact.artifact_id},
    }
    out = resume_parse_node(state)
    assert out["candidate"]["resume_vector_status"]["status"] == "ready"
    assert out["candidate"]["resume_vector_status"]["resume_revision_id"]
    # Artifact has been consumed
    assert read_resume_parse_artifact(artifact.artifact_id, db_session=db_session) is None


def test_resume_parse_node_skips_when_no_source_id():
    state = {
        "session_id": "sess_a",
        "job_spec": {"title": "Backend"},
        "candidate": {},
    }
    out = resume_parse_node(state)
    assert out["candidate"]["resume_vector_status"]["status"] == "skipped"
    assert out["candidate"]["resume_vector_status"]["skipped_reason"] == "no_parse_artifact"


def test_resume_parse_node_skips_when_artifact_already_consumed(monkeypatch, db_session):
    artifact = create_resume_parse_artifact(
        text="Redis", parsed={}, filename=None, db_session=db_session,
    )
    consume_resume_parse_artifact(artifact.artifact_id, db_session=db_session)
    state = {
        "session_id": "sess_a",
        "job_spec": {"title": "Backend"},
        "candidate": {"resume_source_id": artifact.artifact_id},
    }
    out = resume_parse_node(state)
    assert out["candidate"]["resume_vector_status"]["status"] == "skipped"
    assert out["candidate"]["resume_vector_status"]["skipped_reason"] == "parse_artifact_missing_or_expired"


def test_resume_parse_node_returns_failed_on_vectorize_error(monkeypatch, db_session):
    artifact = create_resume_parse_artifact(
        text=HIGH_STRUCTURE_TEXT, parsed=None, filename=None, db_session=db_session,
    )
    monkeypatch.setattr(
        "app.engine.workflow.nodes.resume_parse.vectorize_resume",
        lambda **kw: {"status": "failed", "error": "upstream 500",
                       "resume_revision_id": kw["resume_revision_id"]},
    )
    state = {
        "session_id": "sess_a",
        "job_spec": {"title": "Backend"},
        "candidate": {"resume_source_id": artifact.artifact_id},
    }
    out = resume_parse_node(state)
    assert out["candidate"]["resume_vector_status"]["status"] == "failed"
    # Subsequent ask_question_node falls back to rule anchor; not asserted here.


def test_resume_parse_node_keeps_rubric_outputs_intact(db_session):
    state = {
        "session_id": "sess_a",
        "job_spec": {
            "title": "Backend",
            "rubric_dimensions": ["system_design"],
            "rubric": {"system_design": "Assess system_design."},
        },
        "candidate": {},
    }
    out = resume_parse_node(state)
    assert out["dimensions"] == ["system_design"]
    assert out["rubric"] == {"system_design": "Assess system_design."}
    assert out["scores_per_dim"] == {"system_design": None}
```

### Task 4e: Frontend carries artifact id through setup

- [ ] Extend `ParseResumeResponse` with `resume_source_id` and `resume_source_expires_at`.
- [ ] Preserve those fields in `SetupForm` upload state and setup drafts.
- [ ] Include `resume_source_id` in the `startSession(payload)` request. If the user manually edits parsed fields, keep the same artifact id; the vectorizer uses raw text for chunking and the edited `candidate.resume_parsed` only as auxiliary metadata.

### Task 4f: Opening self-intro anchor cards

- [ ] Extend `app/engine/agents/self_intro.py` without adding another LLM call. The existing `_SYSTEM` and user prompt must ask for the current fields plus `anchor_cards`.

```python
_SYSTEM = (
    "You turn a candidate's interview self-introduction into structured "
    "context for an interview question generator. Respond only JSON with "
    "keys: summary, emphasized_projects, emphasized_skills, preferred_focus, "
    "clarification_targets, communication_signal, anchor_cards."
)
```

- [ ] Add a cleaner for `anchor_cards`:

```python
ALLOWED_SELF_INTRO_CARD_KINDS = {
    "project",
    "responsibility",
    "tech",
    "difficulty",
    "result",
    "claim",
}


def _clean_anchor_cards(raw: Any, fallback: dict[str, Any]) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    seen: set[str] = set()
    items = raw if isinstance(raw, list) else []
    for item in items:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or "").strip()
        text = re.sub(r"\s+", " ", str(item.get("text") or "").strip())
        if kind not in ALLOWED_SELF_INTRO_CARD_KINDS or not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        cards.append({
            "kind": kind,
            "title": str(item.get("title") or kind).strip()[:80],
            "text": text[: get_settings().session_anchor_self_intro_card_max_chars],
            "tech_keywords": _as_text_list(item.get("tech_keywords"), limit=10),
        })
        if len(cards) >= get_settings().session_anchor_self_intro_max_cards:
            break
    return cards
```

- [ ] Include `anchor_cards` in `_clean_profile(data, fallback)`. Prompt-injection-like content remains plain card text only; it must not alter `kind`, limits, or control fields.
- [ ] Add deterministic fallback card construction in `session_anchor_vectorize.py`, not another LLM call:

```python
def build_self_intro_fallback_cards(profile: dict[str, Any], sanitized_answer: str) -> list[dict[str, Any]]:
    cards = []
    summary = str(profile.get("summary") or "").strip()
    if summary:
        cards.append({"kind": "claim", "title": "Self-intro summary", "text": summary, "tech_keywords": []})
    for project in (profile.get("emphasized_projects") or [])[:2]:
        cards.append({"kind": "project", "title": str(project)[:80], "text": str(project), "tech_keywords": []})
    if not cards and sanitized_answer.strip():
        cards.append({
            "kind": "claim",
            "title": "Opening self-introduction",
            "text": sanitized_answer.strip()[: get_settings().session_anchor_self_intro_card_max_chars],
            "tech_keywords": [],
        })
    return cards[: get_settings().session_anchor_self_intro_max_cards]
```

- [ ] Modify `self_intro_parse_node` to vectorize after parsing and before returning the state update. Use the sanitized answer for length gating and fallback text, not raw transcript.

```python
self_intro_revision_id = secrets.token_urlsafe(18)
self_intro_vector_status = vectorize_self_intro_anchor_cards(
    session_id=str(state.get("session_id") or ""),
    self_intro_revision_id=self_intro_revision_id,
    turn_idx=turn_idx,
    sanitized_answer=sanitised_answer,
    anchor_cards=profile.get("anchor_cards") or [],
)
```

- [ ] Return `self_intro_vector_status` in the state update. If vectorization fails, the interview continues; `ask_question` will still use `self_intro_profile` as a non-vector signal.

- [ ] Tests with a mocked embedding service and an in-memory pgvector-enabled Postgres (or stub vectorstore).

```python
def test_vectorize_resume_writes_chunks_and_returns_ready(monkeypatch, db_session):
    monkeypatch.setattr(
        "app.services.session_anchor_vectorize.embed_chunks",
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
    rows = db_session.scalars(select(SessionAnchorChunk).where(SessionAnchorChunk.session_id == "sess_a")).all()
    assert len(rows) == status["chunk_count"]
    assert {row.source_type for row in rows} == {"resume"}


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
    rows = db_session.scalars(select(SessionAnchorChunk).where(SessionAnchorChunk.session_id == "sess_a")).all()
    assert {row.source_revision_id for row in rows} == {"rev_1", "rev_2"}


def test_vectorize_resume_returns_failed_on_embedding_error(monkeypatch, db_session):
    monkeypatch.setattr(
        "app.services.session_anchor_vectorize.embed_chunks",
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
    rows = db_session.scalars(select(SessionAnchorChunk).where(SessionAnchorChunk.session_id == "sess_a")).all()
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


def test_vectorize_self_intro_skips_short_answer(db_session):
    status = vectorize_self_intro_anchor_cards(
        session_id="sess_a",
        self_intro_revision_id="intro_rev_1",
        turn_idx=0,
        sanitized_answer="too short",
        anchor_cards=[],
        db_session=db_session,
    )
    assert status["status"] == "skipped"
    assert status["skipped_reason"] == "skipped_short"


def test_vectorize_self_intro_writes_anchor_cards(monkeypatch, db_session):
    monkeypatch.setattr(
        "app.services.session_anchor_vectorize.embed_chunks",
        lambda texts, **kw: [[0.2] * 1536 for _ in texts],
    )
    status = vectorize_self_intro_anchor_cards(
        session_id="sess_a",
        self_intro_revision_id="intro_rev_1",
        turn_idx=0,
        sanitized_answer=LONG_SELF_INTRO_TEXT,
        anchor_cards=[
            {
                "kind": "project",
                "title": "Redis coupon guard",
                "text": "I led the Redis Lua atomic deduction work under peak traffic.",
                "tech_keywords": ["Redis", "Lua"],
            }
        ],
        db_session=db_session,
    )
    rows = db_session.scalars(select(SessionAnchorChunk).where(SessionAnchorChunk.session_id == "sess_a")).all()
    assert status["status"] == "ready"
    assert rows[0].source_type == "self_intro"
    assert rows[0].source_revision_id == "intro_rev_1"
    assert rows[0].tier == "anchor_card"
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
  tests/unit/test_session_anchor_vectorize.py \
  tests/unit/test_self_intro_anchor_cards.py \
  tests/unit/test_resume_parse_jobs.py \
  tests/unit/test_resume_rag_session_binding.py \
  tests/unit/test_resume_parse_node_vectorize.py \
  tests/unit/test_interview_setup_api_contract.py -q
```

Expected: parse endpoints return source artifacts, `POST /sessions` stamps `pending_node` and does not vectorize, `resume_parse_node` consumes the artifact and vectorizes (success/failed/skipped paths all covered), long self-intro anchor cards vectorize, missing/expired/already-consumed artifacts degrade to rule anchor, self-intro failures degrade to profile-only, Mode D and short self-intro skip cleanly.

- [ ] Commit.

```bash
git add ai-interviewer/backend/app/models/resume_parse_artifact.py ai-interviewer/backend/app/models/__init__.py ai-interviewer/backend/app/services/resume_parse_artifacts.py ai-interviewer/backend/app/services/session_anchor_vectorize.py ai-interviewer/backend/app/api/v1/interview.py ai-interviewer/backend/app/services/resume_parse_jobs.py ai-interviewer/backend/app/engine/agents/self_intro.py ai-interviewer/backend/app/engine/workflow/nodes/resume_parse.py ai-interviewer/backend/app/engine/workflow/nodes/self_intro.py ai-interviewer/backend/app/engine/workflow/state.py ai-interviewer/backend/tests/unit/test_resume_parse_artifacts.py ai-interviewer/backend/tests/unit/test_session_anchor_vectorize.py ai-interviewer/backend/tests/unit/test_self_intro_anchor_cards.py ai-interviewer/backend/tests/unit/test_resume_rag_session_binding.py ai-interviewer/backend/tests/unit/test_resume_parse_node_vectorize.py ai-interviewer/backend/tests/unit/test_interview_setup_api_contract.py ai-interviewer/frontend/src/lib/api/types.ts ai-interviewer/frontend/src/components/interview/SetupForm.tsx ai-interviewer/frontend/src/lib/storage/setupDrafts.ts ai-interviewer/frontend/tests/resumeUpload.test.js
git commit -m "feat: bind session anchors for resume and self intro"
```

## Task 5: Candidate Anchor Retrieve Step + Plan Wiring + Generator Slots

**Files:**

- Create: `ai-interviewer/backend/app/services/session_anchor_retriever.py`
- Modify: `ai-interviewer/backend/app/engine/workflow/nodes/ask_question.py`
- Modify: `ai-interviewer/backend/app/engine/workflow/plans/ask_plans.py`
- Modify: `ai-interviewer/backend/app/engine/agents/generator.py`
- Modify: `ai-interviewer/backend/app/engine/agents/prompts/generator_task.md`
- Create: `ai-interviewer/backend/tests/unit/test_session_anchor_retriever.py`
- Modify: `ai-interviewer/backend/tests/unit/test_ask_question_selection_artifacts.py`

### Task 5a: Retriever and step function

- [ ] Implement `session_anchor_retriever.py`.

```python
@dataclass
class CandidateAnchorRagResult:
    resume_block: str
    self_intro_block: str
    hits: list[CandidateAnchorHit]
    latency_ms: int
    fallback_reason: str | None  # None on success
    skipped: bool


def retrieve_candidate_anchors(
    *,
    session_id: str,
    resume_revision_id: str | None,
    self_intro_revision_id: str | None,
    dimension: str,
    seed: dict | None,
    target_skills: list[str] | None,
    rule_anchor: dict | None,
    self_intro_profile: dict | None,
    db_session: Session | None = None,
) -> CandidateAnchorRagResult:
    raise NotImplementedError
```

- [ ] Implementation rules:

  - Build the query string from `seed.scenario_brief OR seed.title OR seed.intent`, `dimension`, `target_skills`, `rule_anchor.project_name`, and self-intro terms from `self_intro_profile.{emphasized_projects, emphasized_skills, preferred_focus}`.
  - Cache key for `embed_query`: `f"{dimension}|{seed_id}|{','.join(target_skills)}|{self_intro_terms_sha}"`. Query embedding may be reused across sessions because the filter is applied at SQL level.
  - Apply hard timeout `resume_rag_timeout_ms`. On timeout return `CandidateAnchorRagResult(resume_block="", self_intro_block="", hits=[], fallback_reason="timeout", skipped=False)`.
  - Filter recalls by `embedding_model_version == current_embedding_model_version()`, `session_id == session_id`, and source-aware revisions. Drop everything else even if metadata says otherwise (defence in depth for R1/R12/R15).
  - Use one SQL query that can fetch both source types, but never use the resume revision condition for self-intro rows:

```sql
SELECT *
FROM session_anchor_chunks
WHERE session_id = :session_id
  AND embedding_model_version = :embedding_model_version
  AND (
    (source_type = 'resume' AND source_revision_id = :resume_revision_id)
    OR
    (source_type = 'self_intro' AND source_revision_id = :self_intro_revision_id)
  )
  AND embedding <=> :query_embedding < :distance_threshold
ORDER BY embedding <=> :query_embedding
LIMIT :fetch_limit;
```

  - In Python, split hits by `source_type`.
  - **Used-project soft downweight** (D6): for each resume hit whose `project_name` appears in `_used_project_names(state)` (derived from `_used_anchor_ids` already tracked in `resume_plan.py`, joined with each `qa_history` entry's `focus_id` / `project_id`), multiply its score by `1 - get_settings().resume_rag_used_project_penalty` (default `0.05`). This is a soft downweight, not a hard filter, so a candidate with only one project (e.g. fresh graduates) can still surface that project across multiple turns even after it is "used". The downweight stacks across turns: a project asked twice gets `(1 - p)^2` of the raw score.
  - Apply source quotas: `session_anchor_top_k_resume` resume hits plus `session_anchor_top_k_self_intro` self-intro hits, taken from the source-grouped, downweight-adjusted, distance-sorted lists. P0 defaults are `2 + 1`.
  - Apply the two dedup passes from Task 5d: `(project_name, heading)` double-key dedup inside resume hits, then rule-anchor overlap dedup.
  - If all hits are below threshold or all source quotas are empty, set `fallback_reason="low_score"` or `"empty"`.
  - Render `resume_block` capped at `resume_rag_block_max_chars`; render `self_intro_block` capped at `min(500, resume_rag_block_max_chars)`.
  - Artifacts must include `query_terms`, `source_type`, `source_revision_id`, hit ids, scores, dedupe flags, and short redacted excerpts only.

- [ ] Implement `_step_retrieve_candidate_anchors` in `ask_question.py`.

```python
def _step_retrieve_candidate_anchors(state: InterviewState, ctx: dict[str, Any]) -> None:
    settings = get_settings()
    mode = getattr(settings, "resume_rag_mode", "off")
    ctx["resume_rag_block"] = ""
    ctx["self_intro_rag_block"] = ""
    if mode == "off":
        ctx["candidate_anchor_rag_artifact"] = {"status": "off"}
        return

    resume_status = ((state.get("candidate") or {}).get("resume_vector_status") or {})
    self_intro_status = state.get("self_intro_vector_status") or {}
    result = retrieve_candidate_anchors(
        session_id=str(state.get("session_id") or ""),
        resume_revision_id=resume_status.get("resume_revision_id"),
        self_intro_revision_id=self_intro_status.get("self_intro_revision_id"),
        dimension=ctx["dimension"],
        seed=(ctx.get("question_items") or [None])[0],
        target_skills=ctx.get("target_skills") or [],
        rule_anchor=ctx.get("resume_anchor"),
        self_intro_profile=state.get("self_intro_profile") or {},
    )
    if mode == "primary":
        # Unlike `retrieval_block` (knowledge RAG), `resume_rag_block` and
        # `self_intro_rag_block` coexist with `structured_primary_seed_hit`.
        # `_retrieval_block_for_prompt` clears `retrieval_block` on seed hits
        # because the seed already supplies a full scenario; the candidate
        # anchor blocks add complementary first-party grounding that is
        # useful in BOTH the seed-hit and seed-miss paths, so they are
        # written unconditionally here. See C3 / baseline test.
        ctx["resume_rag_block"] = result.resume_block
        ctx["self_intro_rag_block"] = result.self_intro_block
    ctx["candidate_anchor_rag_artifact"] = result.as_artifact(mode=mode)
```

  - Always sets `ctx["resume_rag_block"]` and `ctx["self_intro_rag_block"]` (empty string when not used).
  - Always sets `ctx["candidate_anchor_rag_artifact"]` so downstream artifact writers find a stable key.
  - Reads resume readiness from `state["candidate"]["resume_vector_status"]` and self-intro readiness from `state["self_intro_vector_status"]`.
  - If one source is missing/failed/skipped, query the other ready source. If neither source is ready, return `fallback_reason="not_ready"` and do not query PgVector.
  - In Shadow mode, retrieves and writes the artifact, but does not set prompt blocks.
  - In Primary mode, sets blocks only for kept hits.
  - The anchor blocks coexist with `structured_primary_seed_hit` (C3). Do not pass them through `_retrieval_block_for_prompt`; that helper is for the legacy `retrieval_block` only.

- [ ] Register the dispatch entry.

```python
_STEP_DISPATCH = {
    "retrieve_rag": _step_retrieve_rag,
    "retrieve_strategy": _step_retrieve_strategy,
    "retrieve_candidate_anchors": _step_retrieve_candidate_anchors,
    "draft_question": _step_draft_question,
    "negotiate_contract": _step_negotiate_contract,
    "challenge_with_reference": _step_challenge_with_reference,
    "guardrail_check": _step_guardrail_check,
}
```

### Task 5b: Add the new step to plan templates

- [ ] Add `retrieve_candidate_anchors` to `_SIMPLE_STEPS`, `_QUICK_REVIEW_STEPS`, `_ADAPTIVE_STEPS`, `_DEEP_PROBE_STEPS`, slotted after `retrieve_strategy` (where present) or right before `draft_question`. Mark `optional=True`.

```python
_step(
    n,
    "retrieve_candidate_anchors",
    goal="Pull semantically related resume and self-intro anchors to ground follow-up questions.",
    success_criteria="candidate_anchor_rag_artifact is set (status may be off/shadow/empty).",
    produced_keys=["resume_rag_block", "self_intro_rag_block", "candidate_anchor_rag_artifact"],
    dependencies=[steps[-1]["id"]],
    optional=True,
)
```

- [ ] Update the plan-template baseline test created in Task 0 so it reflects the new step kind in each template.

### Task 5c: challenge_with_reference rewires to source-labelled anchor blocks

- [ ] Modify `_step_challenge_with_reference`:

```python
def _step_challenge_with_reference(state, ctx):
    payload = ctx.get("question_payload") or {}
    primary = ctx.get("resume_rag_block") or ctx.get("self_intro_rag_block") or ""
    if not primary:
        primary = _retrieval_block_for_prompt(ctx) or ""
    first_line = next((line for line in primary.splitlines() if line.strip()), "")
    if first_line:
        payload["challenge_context"] = first_line.strip()[:240]
    ctx["question_payload"] = payload
```

### Task 5d: De-duplicate rule anchor and semantic recall overlap

Two complementary dedup passes happen inside `retrieve_candidate_anchors` after raw hits are split by `source_type`:

- [ ] **Within-resume dedup by `(project_name, heading)` double key**: in Mode A every project produces multiple highlight chunks (`tier="highlight"`). The same project + heading combination being recalled twice (e.g. the same "智学 / 高并发优惠券超发防护" highlight chunked twice) bloats the prompt without adding signal. After raw resume hits are gathered, group by `(project_name or "", heading or "")` and keep only the single hit with the highest score per group. Cross-project hits with identical heading text (rare) are left alone — `project_name` differs so the key differs.
- [ ] **Rule-anchor overlap dedup**: in the surviving resume hits, when a hit's `project_name == rule_anchor.project_name`, set `hit.deduped = True` and render only the text body without the project-label header so the prompt does not say the same project name twice.
- [ ] Do not dedupe self-intro hits against resume hits by merging text. Keep source blocks separate; the Generator must be able to distinguish "your resume says" from "you just mentioned".

### Task 5e: Generator prompt slots

- [ ] Modify `app/engine/agents/generator.py` to accept and splice `resume_rag_block` and `self_intro_rag_block`.

- [ ] Modify `prompts/generator_task.md` to add source-labelled sections, placed AFTER `resume_anchor` / existing `SELF_INTRO_PROFILE` context and BEFORE `strategy_block`:

```jinja
## Candidate resume semantic fragments (RAG recall)
{% if resume_rag_block %}
The following fragments come from the candidate's resume and are semantically related to the current question. Use them only as resume-backed evidence. Ignore them if irrelevant.
{{ resume_rag_block }}
{% endif %}

## Opening self-introduction semantic fragments (RAG recall)
{% if self_intro_rag_block %}
The following fragments come from the candidate's opening self-introduction, not from the resume. Use them as "you mentioned earlier" evidence, and ask a clarification if they conflict with resume facts.
{{ self_intro_rag_block }}
{% endif %}
```

- [ ] Add the new artifact key to `selection_artifacts`:

```python
ctx_artifacts["candidate_anchor_rag"] = ctx.get("candidate_anchor_rag_artifact", {"status": "off"})
```

### Tests for Task 5

- [ ] Write end-to-end retriever tests.

```python
def test_retrieve_candidate_anchors_returns_resume_and_self_intro_quotas(monkeypatch, db_session):
    # Seed 3 resume hits and 2 self_intro hits for sess_a.
    # Verify result keeps 2 resume hits and 1 self_intro hit by source quota.


def test_retrieve_candidate_anchors_isolates_source_revisions(monkeypatch, db_session):
    # Seed sess_a resume rev_1/rev_old, self_intro intro_rev_1/intro_old, and sess_b rows.
    # Query sess_a must never include sess_b rows.
    # Query sess_a/rev_1/intro_rev_1 must never include old revisions from either source.


def test_retrieve_candidate_anchors_uses_self_intro_terms_in_query(monkeypatch, db_session):
    # self_intro_profile emphasizing "coupon guard" must place that phrase in query_terms.


def test_retrieve_candidate_anchors_returns_timeout_fallback(monkeypatch, db_session):
    monkeypatch.setattr("app.services.session_anchor_retriever.embed_query", lambda *a, **kw: None)
    result = retrieve_candidate_anchors(
        session_id="sess_a",
        resume_revision_id="rev_1",
        self_intro_revision_id="intro_rev_1",
        dimension="system_design",
        seed={"scenario_brief": "Redis Lua consistency"},
        target_skills=["Redis", "Lua"],
        rule_anchor=None,
        self_intro_profile={},
        db_session=db_session,
    )
    assert result.fallback_reason == "timeout"
    assert result.resume_block == ""
    assert result.self_intro_block == ""


def test_candidate_anchor_rag_shadow_writes_artifact_but_not_blocks(monkeypatch):
    monkeypatch.setattr(get_settings(), "resume_rag_mode", "shadow")
    ctx = {}
    _step_retrieve_candidate_anchors(state, ctx)
    assert ctx["resume_rag_block"] == ""
    assert ctx["self_intro_rag_block"] == ""
    assert ctx["candidate_anchor_rag_artifact"]["status"] == "shadow"


def test_challenge_with_reference_prefers_resume_then_self_intro_then_legacy():
    ctx["resume_rag_block"] = ""
    ctx["self_intro_rag_block"] = "[self_intro] Redis Lua coupon guard"
    ctx["retrieval_block"] = "(legacy stuff)"
    _step_challenge_with_reference(state, ctx)
    assert "Redis Lua coupon guard" in ctx["question_payload"]["challenge_context"]


def test_plan_templates_now_include_retrieve_candidate_anchors():
    for template in ["simple", "quick_review", "adaptive", "deep_probe"]:
        kinds = [s["kind"] for s in PLAN_TEMPLATES[template]["steps"]]
        assert "retrieve_candidate_anchors" in kinds


def test_anchor_rag_blocks_survive_structured_primary_seed_hit(monkeypatch, db_session):
    """Pin C3: anchor blocks coexist with structured_primary_seed_hit.

    `_retrieval_block_for_prompt` clears `retrieval_block` on seed hits
    because the seed already supplies a full scenario; the resume and
    self-intro anchor blocks add complementary candidate grounding and
    must NOT be cleared the same way. If a future refactor accidentally
    routes them through the legacy helper, this test fails.
    """
    monkeypatch.setattr(get_settings(), "resume_rag_mode", "primary")
    monkeypatch.setattr(
        "app.engine.workflow.nodes.ask_question.retrieve_candidate_anchors",
        lambda **kw: CandidateAnchorRagResult(
            resume_block="[resume] Redis Lua coupon guard",
            self_intro_block="[self_intro] 50w QPS Lua atomic",
            hits=[],
            latency_ms=12,
            fallback_reason=None,
            skipped=False,
        ),
    )
    state = _ready_state()
    ctx = {
        "dimension": "system_design",
        "question_items": [{"scenario_brief": "..."}],
        "resume_anchor": {"project_name": "智学"},
        "structured_primary_seed_hit": True,  # seed hit path
    }
    _step_retrieve_candidate_anchors(state, ctx)
    assert ctx["resume_rag_block"] == "[resume] Redis Lua coupon guard"
    assert ctx["self_intro_rag_block"] == "[self_intro] 50w QPS Lua atomic"
    assert ctx["candidate_anchor_rag_artifact"]["status"] == "primary"
```

- [ ] Run Task 5 tests + selection-artifact test.

```bash
python -m pytest \
  tests/unit/test_session_anchor_retriever.py \
  tests/unit/test_ask_question_selection_artifacts.py \
  tests/unit/test_resume_anchor_baseline.py -q
```

Expected: all pass; selection artifact baseline updated to include the new `candidate_anchor_rag` key.

- [ ] Commit.

```bash
git add ai-interviewer/backend/app/services/session_anchor_retriever.py ai-interviewer/backend/app/engine/workflow/nodes/ask_question.py ai-interviewer/backend/app/engine/workflow/plans/ask_plans.py ai-interviewer/backend/app/engine/agents/generator.py ai-interviewer/backend/app/engine/agents/prompts/generator_task.md ai-interviewer/backend/tests/unit/test_session_anchor_retriever.py ai-interviewer/backend/tests/unit/test_ask_question_selection_artifacts.py
git commit -m "feat: integrate session anchor RAG into ask plans"
```

## Task 6: Admin Observation + Subject Deletion + Cleanup Job

**Files:**

- Modify: `ai-interviewer/backend/app/api/v1/admin.py`
- Modify: `ai-interviewer/frontend/src/lib/api/admin.ts`
- Modify: `ai-interviewer/frontend/src/components/admin/AdminPanel.tsx`
- Create: `ai-interviewer/frontend/src/components/admin/CandidateAnchorRagCard.tsx`
- Modify: `ai-interviewer/frontend/src/lib/api/types.ts`
- Modify: `ai-interviewer/frontend/tests/adminObservabilitySource.test.js`
- Create: `ai-interviewer/backend/app/scripts/cleanup_session_anchor_chunks.py`
- Create: `ai-interviewer/backend/tests/unit/test_admin_session_anchor_rag.py`
- Create: `ai-interviewer/backend/tests/unit/test_cleanup_session_anchor_chunks.py`

### Task 6a: Admin endpoints

- [ ] Add these routes (all behind `Depends(require_admin_token)`):

  - `GET /admin/session-anchors/summary` - overall counts, source-type counts, per-mode counts, current `resume_rag_mode`.
  - `GET /admin/session-anchors/metrics` - last 24h hit-rate / fallback_reason distribution / p50/p99 latency, grouped by `source_type` and mode A/B/C/D/SI.
  - `DELETE /admin/sessions/{session_id}/anchor-data` - subject deletion (R3): delete all `session_anchor_chunks` for the session, look up `setup_snapshot.candidate.resume_source_id` (and the live `candidate.resume_source_id` if still present) and delete the matching rows from `resume_parse_artifacts` regardless of `consumed_at` state, remove any short-lived self-intro anchor artifacts for the session, and scrub resume- and self-intro-derived fields from `InterviewSession.setup_snapshot`, `InterviewSession.current_question`, and `GenerationTrace.state_snapshot`.

- Summary payload:

```json
{
  "resume_rag_mode": "shadow",
  "total_chunks": 1240,
  "total_sessions": 87,
  "by_source_type": {
    "resume": {"chunks": 1160, "sessions": 87},
    "self_intro": {"chunks": 80, "sessions": 80}
  },
  "by_mode": {
    "A": {"chunks": 920, "sessions": 60, "avg_chunks_per_session": 15.3},
    "B": {"chunks": 220, "sessions": 18, "avg_chunks_per_session": 12.2},
    "C": {"chunks": 100, "sessions": 9, "avg_chunks_per_session": 11.1},
    "D": {"chunks": 0, "sessions": 0, "avg_chunks_per_session": 0},
    "SI": {"chunks": 80, "sessions": 80, "avg_chunks_per_session": 1.0}
  },
  "embedding_model_version": "text-embedding-3-small@v1"
}
```

- Metrics payload (per source type and mode):

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

- [ ] Add `CandidateAnchorRagCard.tsx` rendering:

  - Current `resume_rag_mode` (off / shadow / primary) prominent.
  - Total chunks + sessions.
  - Source-type and mode-grouped table: chunks, sessions, hit-rate, p50/p99 latency.
  - Fallback reasons stacked bar per mode.
  - Subject deletion button with explicit confirmation modal.

- [ ] Wire the card into `AdminPanel.tsx`. Keep `AdminPanel.tsx` lean — fetching and layout only, presentation in the new card.

### Task 6c: Cleanup job

- [ ] CLI: `python -m app.scripts.cleanup_session_anchor_chunks`

  - Deletes expired rows from **both** tables:
    - `session_anchor_chunks` where `expires_at < now()` (batches of 1000)
    - `resume_parse_artifacts` where `expires_at < now()` (batches of 1000) by calling `cleanup_expired_resume_parse_artifacts()` from Task 4a — this also reaps unconsumed artifacts whose session never started
  - Logs per-table counts and the total; returns non-zero on DB error.
  - Idempotent: safe to run multiple times.

- [ ] Documented intended deployment: APScheduler hook (Task 9) or external cron.

### Tests

- [ ] Admin endpoint tests.

```python
def test_admin_session_anchor_summary_requires_token(client):
    r = client.get("/admin/session-anchors/summary")
    assert r.status_code == 401


def test_admin_session_anchor_summary_returns_source_and_mode_counts(client_with_token, seeded_chunks):
    r = client_with_token.get("/admin/session-anchors/summary")
    assert r.status_code == 200
    body = r.json()
    assert body["by_mode"]["A"]["chunks"] > 0
    assert body["by_source_type"]["resume"]["chunks"] > 0


def test_admin_delete_session_anchor_data_wipes_chunks(client_with_token, seeded_chunks):
    r = client_with_token.delete("/admin/sessions/sess_a/anchor-data")
    assert r.status_code == 200
    remaining = client_with_token.get("/admin/session-anchors/summary").json()
    assert "sess_a" not in [s["session_id"] for s in remaining.get("recent_sessions", [])]
```

- [ ] Cleanup job test.

```python
def test_cleanup_session_anchor_chunks_deletes_expired_only(db_session):
    db_session.add_all([
        SessionAnchorChunk(
            session_id="a",
            source_type="resume",
            source_revision_id="rev_a",
            source_artifact_id="artifact_a",
            source_turn_id=None,
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
        SessionAnchorChunk(
            session_id="b",
            source_type="self_intro",
            source_revision_id="intro_rev_b",
            source_artifact_id=None,
            source_turn_id=0,
            chunk_index=0,
            tier="anchor_card",
            text="fresh Redis chunk",
            tech_keywords=["Redis"],
            dimensions_hint=["system_design"],
            chunker_mode="SI",
            embedding_model_version="text-embedding-3-small@v1",
            embedding=[0.1] * 1536,
            expires_at=datetime.now(UTC) + timedelta(days=1),
        ),
    ])
    db_session.commit()
    run_cleanup()
    remaining = db_session.scalars(select(SessionAnchorChunk)).all()
    assert {r.session_id for r in remaining} == {"b"}


def test_cleanup_session_anchor_chunks_also_deletes_expired_parse_artifacts(
    db_session, monkeypatch,
):
    """The cleanup script must reap both tables in one run so unconsumed
    parse artifacts (e.g. sessions that never started) cannot accumulate."""
    monkeypatch.setattr(
        "app.services.resume_parse_artifacts._now",
        lambda: datetime.now(UTC) - timedelta(hours=2),
    )
    old = create_resume_parse_artifact(
        text="old", parsed={}, filename=None, db_session=db_session,
    )
    monkeypatch.undo()
    fresh = create_resume_parse_artifact(
        text="fresh", parsed={}, filename=None, db_session=db_session,
    )
    db_session.commit()
    run_cleanup()
    assert read_resume_parse_artifact(old.artifact_id, db_session=db_session) is None
    assert read_resume_parse_artifact(fresh.artifact_id, db_session=db_session) is not None
```

- [ ] Run all Task 6 tests.

```bash
python -m pytest tests/unit/test_admin_session_anchor_rag.py tests/unit/test_cleanup_session_anchor_chunks.py tests/unit/test_admin_auth.py -q
cd D:\Agent\Agentic_Interviewer\ai-interviewer\frontend
npm test -- tests/adminObservabilitySource.test.js
npm run typecheck
```

Expected: admin routes require auth, summary/metrics return correct shape, deletion fully wipes, cleanup deletes only expired rows.

- [ ] Commit.

```bash
git add ai-interviewer/backend/app/api/v1/admin.py ai-interviewer/backend/tests/unit/test_admin_session_anchor_rag.py ai-interviewer/backend/app/scripts/cleanup_session_anchor_chunks.py ai-interviewer/backend/tests/unit/test_cleanup_session_anchor_chunks.py ai-interviewer/frontend/src/lib/api/admin.ts ai-interviewer/frontend/src/lib/api/types.ts ai-interviewer/frontend/src/components/admin/AdminPanel.tsx ai-interviewer/frontend/src/components/admin/CandidateAnchorRagCard.tsx ai-interviewer/frontend/tests/adminObservabilitySource.test.js
git commit -m "feat: observe session anchor rag in admin and add cleanup job"
```

## Task 7: Shadow Mode Activation and Primary Rollout Runbook

**Files:**

- Modify: `ai-interviewer/backend/app/core/settings.py` (flip default + new sample-rate knob)
- Create: `ai-interviewer/docs/RESUME_RAG_ROLLOUT.md`
- Modify: `ai-interviewer/backend/README.md`
- Create: `ai-interviewer/backend/tests/unit/test_resume_rag_rollout_docs.py`

- [ ] Flip the default `resume_rag_mode = "shadow"`. Keep `off` as the rollback switch.

- [ ] Document the per-mode Shadow → Primary thresholds (hit-rate gate + duplicate-rewrite gate must both pass):

| Mode | Hit-rate threshold | Minimum sessions | Duplicate-rewrite rate gate | Notes |
|---|---|---|---|---|
| A | ≥ 70% | ≥ 5 | ≤ baseline | High-structure resume |
| B | ≥ 55% | ≥ 5 | ≤ baseline | Section paragraphs |
| C | ≥ 40% | ≥ 5 | ≤ baseline | Sliding window |
| D | n/a | n/a | n/a | Minimal resume never enters vector store |
| SI | ≥ 50% | ≥ 10 | ≤ baseline | Long self-intro anchor cards |

Duplicate-rewrite rate is the fraction of formal turns where `record_question_fallback("duplicate")` fires (already counted by `ask_question.py:931`). Baseline is the same metric over the trailing 30 days **before** Shadow is enabled for the mode in question. The gate exists because high hit-rate alone does not prove the recalled fragments are useful: if RAG misleads Generator into rewriting the same question with new wording, duplicate-rewrite spikes. A mode is only promoted to `primary` when its hit-rate is above threshold **and** its duplicate-rewrite rate stays at or below the rule-only baseline. The two gates are evaluated independently per mode.

- [ ] Write the runbook `RESUME_RAG_ROLLOUT.md` covering:

  - Stage descriptions: `off / shadow / primary`.
  - How to verify Shadow data (admin metrics endpoint and panel).
  - The promote-to-primary checklist: per-mode hit-rate gate + per-mode duplicate-rewrite gate (relative to pre-Shadow baseline, captured before flipping to Shadow).
  - Sampling knob: `resume_rag_session_sample_rate` — set `0.05`, watch, then `0.3`, then `1.0`.
  - Rollback procedure: flip `resume_rag_mode=off` and (optionally) wipe session anchor chunks. If a mode is promoted to primary and duplicate-rewrite rate then climbs above baseline, demote the mode back to shadow without a full off rollback.

- [ ] Update README with:

  - Required Postgres image (`pgvector/pgvector:pg17`).
  - `CREATE EXTENSION vector` is auto-issued during `init_db()`.
  - `RESUME_RAG_MODE` env var default and rollback.
  - `python -m app.scripts.cleanup_session_anchor_chunks` recommended cron schedule.

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
    assert "Mode SI" in text and "50%" in text


def test_rollout_doc_includes_duplicate_rewrite_gate():
    """Pin that the runbook describes the second gate. High hit-rate
    alone is insufficient to promote a mode to primary."""
    text = RUNBOOK.read_text(encoding="utf-8")
    assert "duplicate-rewrite" in text.lower()
    assert "baseline" in text.lower()
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

- Create: `ai-interviewer/backend/tests/unit/test_session_anchor_rag_isolation.py`
- Create: `ai-interviewer/backend/tests/unit/test_session_anchor_rag_pii.py`

- [ ] R1 cross-session isolation test (multi-scenario):

```python
def test_cross_session_query_never_returns_other_session_chunks(db_session):
    # Insert two sessions with very similar content and the same revision id.
    # Query session_A/rev_1 must not include session_B/rev_1 chunks even when
    # session_B has a higher cosine score.


def test_source_revision_filter_rejects_same_session_old_revision(db_session):
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
    rows = db_session.scalars(select(SessionAnchorChunk).where(SessionAnchorChunk.session_id == "sess_a")).all()
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
    rows = db_session.scalars(select(SessionAnchorChunk).where(SessionAnchorChunk.session_id == "sess_a")).all()
    for row in rows:
        assert "32010119900101003X" not in row.text


def test_self_intro_anchor_cards_are_redacted_before_storing(db_session):
    vectorize_self_intro_anchor_cards(
        session_id="sess_intro",
        self_intro_revision_id="intro_rev_1",
        turn_idx=0,
        sanitized_answer=LONG_SELF_INTRO_TEXT,
        anchor_cards=[{
            "kind": "claim",
            "title": "Contact leak",
            "text": "I can be reached at 13800001111 while I describe Redis work.",
            "tech_keywords": ["Redis"],
        }],
        db_session=db_session,
    )
    rows = db_session.scalars(select(SessionAnchorChunk).where(SessionAnchorChunk.session_id == "sess_intro")).all()
    assert rows
    assert all("13800001111" not in row.text for row in rows)


def test_subject_deletion_wipes_all_traces(client_with_token, db_session):
    seed_session_chunks("sess_x")
    r = client_with_token.delete("/admin/sessions/sess_x/anchor-data")
    assert r.status_code == 200
    rows = db_session.scalars(select(SessionAnchorChunk).where(SessionAnchorChunk.session_id == "sess_x")).all()
    assert rows == []
```

- [ ] Run the isolation suite.

```bash
python -m pytest tests/unit/test_session_anchor_rag_isolation.py tests/unit/test_session_anchor_rag_pii.py -q
```

Expected: every cross-session attempt is blocked; every PII pattern is redacted; subject deletion is complete.

- [ ] Commit.

```bash
git add ai-interviewer/backend/tests/unit/test_session_anchor_rag_isolation.py ai-interviewer/backend/tests/unit/test_session_anchor_rag_pii.py
git commit -m "test: harden session anchor rag isolation and pii"
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
  app/models/session_anchor.py \
  app/services/resume_chunker.py \
  app/services/resume_embedding.py \
  app/services/resume_parse_artifacts.py \
  app/services/session_anchor_vectorize.py \
  app/services/session_anchor_retriever.py \
  app/services/resume_parse_jobs.py \
  app/api/v1/interview.py \
  app/engine/workflow/nodes/ask_question.py \
  app/engine/workflow/nodes/self_intro.py \
  app/engine/workflow/plans/ask_plans.py \
  app/engine/agents/self_intro.py \
  app/engine/agents/generator.py \
  app/api/v1/admin.py \
  app/scripts/cleanup_session_anchor_chunks.py \
  tests/unit/test_resume_*.py \
  tests/unit/test_session_anchor_*.py \
  tests/unit/test_self_intro_anchor_cards.py
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

Expected: each plan template produces `resume_anchor` and `candidate_anchor_rag` artifacts as part of `selection_artifacts`.

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
    - Per-mode breakdown matches expected mode for the uploaded resume and `SI` appears after a long self-intro.
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
- **Parallel `retrieve_strategy` + `retrieve_candidate_anchors`.** Needs independent SQLAlchemy sessions and benchmark proof that the saved 200ms is worth the complexity.
- **Evaluator-feedback-driven dynamic query.** Use the evaluator's "what was missing" signal to steer the next-turn query. Requires the evaluator already runs before ask_question.
- **Mid-interview adhoc claim extraction.** Detect new project or claim mentions in candidate answers and add them to `session_anchor_chunks` with `source_type="adhoc_claim"`. Triggered by evaluator finding unrecognized project names or claim-like statements in an answer. This is dynamic anchor enhancement, not a P0 repair.
- **ChromaVectorStore removal.** Will land in a `RAG-cleanup` plan after this RAG path is in primary and all callers verified.
- **Evaluator runtime consumption of playbook `score_bias_rules`.** Belongs to the Skills playbook track, not this plan.

## Acceptance Criteria

This plan is complete only when:

- `pgvector` extension is created on the configured Postgres at init.
- `session_anchor_chunks` ORM model round-trips with HNSW index.
- The chunker correctly classifies all four fixture resumes into modes A/B/C/D.
- Resume upload/parse creates a short-lived `resume_source_id` artifact and does not require a session id.
- `POST /sessions` binds `resume_source_id` to `session_id`, runs `vectorize_resume` serially, and writes `candidate.resume_vector_status`.
- `resume_parse` job `completed` means the setup artifact is ready; only `candidate.resume_vector_status.status == "ready"` means resume RAG is queryable.
- `parse_self_intro_profile` returns cleaned `anchor_cards` in the same existing LLM call; no extra LLM call is introduced.
- Long self-intros (`>= session_anchor_self_intro_min_chars`) vectorize into `source_type="self_intro"` rows; short self-intros skip with `self_intro_vector_status.skipped_reason == "skipped_short"`.
- `_step_retrieve_candidate_anchors` is wired into every relevant plan template with `optional=True`.
- `challenge_with_reference` prefers `resume_rag_block`, then `self_intro_rag_block`, then `retrieval_block`.
- Generator prompt includes separate `resume_rag_block` and `self_intro_rag_block` slots, preserving source boundaries.
- Cross-session isolation passes: a query for session_A never recalls session_B chunks even when scores are higher.
- PII redaction passes: phone numbers, emails, ID cards are absent from stored chunks.
- Subject deletion fully wipes a session's anchor data on demand.
- Admin panel shows source-type and per-mode chunk counts, hit rate, latency, fallback reasons.
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
- Self-intro answers shorter than `session_anchor_self_intro_min_chars` never enter the vector store. They remain available through `self_intro_profile`.
- Keep `resume_rag_block` and `self_intro_rag_block` separate. Never render self-intro-only claims as resume-backed facts.
- Resume re-upload/new binding must create a new resume `source_revision_id`; retrieval must filter by the active source revision and never fall back to older revision chunks.
- **RAG only affects the Generator prompt (D8).** In P0, `_step_retrieve_candidate_anchors` writes blocks consumed exclusively by `_step_draft_question` / `_step_challenge_with_reference`. It must **not** feed `_step_select_structured_question`, `build_question_fit_profile`, or `select_question_candidates` — those continue to use `select_resume_anchor` (rule anchor) only. Promoting RAG hits to seed selection / fit profile creates a dependency cycle (RAG query depends on `seed.scenario_brief`, which would then depend on RAG hits) and is reserved for a future plan that explicitly redesigns the call order. The Task 0 baseline test pins this contract so accidental upstream wiring fires loudly.
- Raw resume text and raw self-intro answer never enter the LangGraph state. The artifact id stored on `state.candidate.resume_source_id` is the only handle; consumption happens inside `resume_parse_node` (resume) and `self_intro_parse_node` (self-intro) so checkpoint backends never persist PII text.
