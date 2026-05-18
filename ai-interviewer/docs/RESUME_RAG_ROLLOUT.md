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
for the session.

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
