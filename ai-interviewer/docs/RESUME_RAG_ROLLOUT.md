# Session Anchor RAG Rollout Runbook

Session Anchor RAG stores candidate-scoped resume and self-introduction anchors in
Postgres/PgVector. It is isolated by `session_id` and source revision, and it
ships behind `RESUME_RAG_MODE`.

## Modes

| Mode | Behavior | Prompt impact |
| --- | --- | --- |
| `off` | Do not retrieve session anchors. | No candidate-anchor prompt slots. |
| `shadow` | Retrieve anchors and write artifacts/metrics. | Generator still uses the rule-based resume anchor path. |
| `primary` | Retrieve anchors and write artifacts/metrics. | Generator receives the resume and self-intro anchor slots. |

Default rollout state is `RESUME_RAG_MODE=shadow`. Emergency rollback is
`RESUME_RAG_MODE=off`.

## Sampling Ramp

Use `resume_rag_session_sample_rate` to ramp shadow traffic before promoting any
mode:

| Stage | Value | Hold time | Check |
| --- | --- | --- | --- |
| Smoke | `0.05` | 1 day or 20 sessions | No errors, p99 retrieval latency acceptable. |
| Partial | `0.3` | 2-3 days | Hit-rate and fallback reasons are stable. |
| Full shadow | `1.0` | 7 days | Promotion gates can be evaluated per mode. |

The sampler is session-stable, so a session stays either in or out of shadow.

## Shadow Metrics

Verify shadow data in the Admin "Candidate Anchor RAG" card and through:

- `GET /admin/session-anchors/summary`
- `GET /admin/session-anchors/metrics`

Track source type, chunk counts, hit-rate by mode/source, p50/p99 latency,
fallback reasons, and subject deletion actions.

## Embedding BYOK

Session Anchor RAG can use the browser-supplied LLM configuration for
embeddings. In the LLM settings dialog, the "Candidate Anchor Retrieval" route
defaults to Qwen `text-embedding-v4` at 1536 dimensions with base URL
`https://dashscope.aliyuncs.com/compatible-mode/v1`.

If the default chat provider is Qwen and a default Qwen API key is present, the
embedding route inherits that key without requiring a second key entry. If the
embedding route is configured separately, its key is sent only with the session
request and is stripped from persisted `llm_config_meta` like the chat and voice
keys.

The dimension is intentionally fixed at 1536 because `session_anchor_chunks`
uses a `vector(1536)` column. Qwen `text-embedding-v4` must therefore be called
with `dimensions=1536`; changing dimensions requires a database/schema rollout,
not only a UI config edit.

Without a browser-supplied embedding key, the backend falls back to the
server-side `resume_rag_embedding_*` settings.

## Resume Anchor Vector Cache

Resume anchors use a global copy-on-bind cache. The first session for a resume
still chunks and embeds normally; when the same redacted resume text, parsed
chunk-affecting fields, chunker version, and embedding model version appear
again, the backend copies cached rows into the new session's
`session_anchor_chunks` with a fresh `resume_revision_id`.

This keeps retrieval session-scoped while avoiding repeated remote embedding
calls. A cache hit is reported as `resume_vector_status.cache_hit=true`; a miss
reports `cache_hit=false` and stores the generated vectors for later sessions.
The default cache retention is 7 days (`resume_anchor_cache_ttl_hours=168`).

Subject deletion remains strict: `DELETE /admin/sessions/{session_id}/anchor-data`
deletes the session rows and also purges any global resume cache rows referenced
by that session's `source_cache_key`.

## Primary Promotion Gates

Both gates must pass independently per mode. High hit-rate alone is not enough.

| Mode | Hit-rate threshold | Minimum sessions | Duplicate-rewrite gate | Notes |
| --- | --- | --- | --- | --- |
| Mode A | >= 70% | >= 5 | <= baseline | High-structure resume. |
| Mode B | >= 55% | >= 5 | <= baseline | Section paragraphs. |
| Mode C | >= 40% | >= 5 | <= baseline | Sliding window. |
| Mode D | n/a | n/a | n/a | Minimal resume never enters the vector store. |
| Mode SI | >= 50% | >= 10 | <= baseline | Long self-intro anchor cards. |

The duplicate-rewrite rate is the fraction of formal turns where
`record_question_fallback("duplicate")` fires. Capture the baseline over the
trailing 30 days before enabling shadow for the mode. Promote a mode only when
its hit-rate is above threshold and its duplicate-rewrite rate stays at or below
the rule-only baseline.

## Rollback

1. Set `RESUME_RAG_MODE=off`.
2. Restart the backend.
3. If bad data was written, run:

```powershell
python -m app.scripts.cleanup_session_anchor_chunks
```

If a promoted mode later exceeds the duplicate-rewrite baseline, demote that
mode back to shadow without forcing a full `off` rollback.

## Cleanup And Privacy

The regular privacy cleanup APScheduler tick also runs session-anchor cleanup.
For external cron environments, run this command daily:

```powershell
python -m app.scripts.cleanup_session_anchor_chunks
```

Subject deletion is handled by:

```text
DELETE /admin/sessions/{session_id}/anchor-data
```

It removes session anchor chunks, parse artifacts, and trace payload references
for the session. If the session used cached resume anchors, the same request
also removes the corresponding global resume anchor cache rows.

Interrupted or still-running interviews keep session anchor rows for about eight
days by default (`resume_rag_session_ttl_hours=168`, plus the existing 24h grace
window) so browser recovery can continue to use resume/self-intro RAG. Once an
interview completes, the backend deletes that session's `session_anchor_chunks`
immediately. This completion cleanup does not purge the global resume vector
cache; the cache remains available for later sessions until its 7-day TTL or an
explicit subject deletion.

## Local Postgres Parity Check

Use the `pgvector/pgvector:pg16` image locally to match the current compose
major version, or any Postgres image with the vector extension installed.
`init_db()` issues `CREATE EXTENSION vector` during startup when the database
supports it.

Before declaring rollout ready:

1. Start the backend with `RESUME_RAG_MODE=shadow`.
2. Upload a resume, create a session, complete self-introduction, and run one
   formal `ask_question` turn.
3. Open Admin and confirm total chunks > 0, hit-rate rows exist, fallback reasons
   are not dominated by `timeout` or `error`, and the subject deletion button
   clears the session's anchor rows.
