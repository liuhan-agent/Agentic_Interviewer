# Deployment-Level Hardening Audit (2026-Q2)

This audit examines three hardening items raised in the input/session
hardening review. None of them are real correctness bugs in single-process
deployments, but each becomes load-bearing as the topology grows. The
audit picks a position for the current shape of the project and lists
the trigger that should flip the decision.

## Scope

The companion code-level hardening commits (P0-A, P0-B, P0-C, P1-D,
P1-E, P1-G, P2-H) closed every item that fired in single-process tests
plus the auth bypass on `/retry-question` and `/feedback`. The three
items below were intentionally **deferred**:

- F1. Voice-ticket Redis-backed store
- F2. `/resume/parse` per-provider rate limiting
- F3. Cache key per-tenant salt

Each entry below states the current state, the failure mode that the
proposal protects against, the decision, and the explicit trigger that
flips the decision.

---

## F1. Voice-ticket Redis-backed store

### Current state

`app/core/voice_ticket.py` keeps issued tickets in a process-local
`dict[str, tuple[str, float]]` guarded by `threading.Lock()`. Tickets
are one-time and short-lived (`voice_ticket_ttl_seconds`, default
30 s). `consume_voice_ticket` pops on first read so replay always
fails — the existing `tests/unit/test_ws_voice_empty_transcript.py`
already exercises that path.

### Failure mode under multiple workers

When the backend is horizontally scaled to ≥ 2 uvicorn workers behind
a non-sticky load balancer:

1. Worker A handles `POST /voice-ticket`, writes to its in-memory dict.
2. The browser opens `wss://.../ws/voice/{id}` and the load balancer
   routes the upgrade to worker B.
3. Worker B's `_tickets` is empty for this token, so `consume_voice_ticket`
   returns `False` and the WebSocket closes with `auth_failed`.

### Decision

**Defer until the deployment topology actually moves to ≥ 2 workers.**

Rationale:
- The current happy path is single-worker uvicorn (development, demo,
  and the documented production deploy in `PLAN_PRODUCTION_DEPLOY.md`).
- Sticky sessions (cookie-based or IP hash) keep the dict valid even
  with multiple workers, so this is a "when we lift sticky sessions"
  problem, not a "we already broke" problem.
- Redis is already in the dependency tree (resume_parse_cache uses
  it), so a follow-up swap is structurally low-risk.

### Trigger to revisit

- A deployment moves to ≥ 2 backend workers without sticky sessions.
- Or a session reports `voice ticket consumed by wrong worker` in logs
  more than once per day.

### Suggested follow-up

- Extract a `VoiceTicketStore` Protocol from `voice_ticket.py` exposing
  `issue` / `consume` / `clear`. Keep `InMemoryVoiceTicketStore` as the
  default; add `RedisVoiceTicketStore` behind a `VOICE_TICKET_BACKEND`
  setting. Reuse the existing `redis_url` setting.

---

## F2. `/resume/parse` per-provider rate limiting

### Current state

`_enforce_setup_rate_limit` (in `app/api/v1/interview.py`) keys rate
limit buckets by `endpoint:host`, where `host` is the client IP. The
limits live in `settings.resume_parse_rate_limit_per_minute` and
`settings.jd_parse_rate_limit_per_minute`. Per-provider concurrency
control sits inside `app/engine/agents/llm_client.py` (timeout, retry,
circuit breaker) on every `call_chat` invocation.

### Failure mode

The client of `/resume/parse` brings their own LLM key (BYOK):

- A user with a misconfigured Anthropic key generates a steady stream
  of provider-side 429s. `llm_client.py` retries with backoff, the
  `parse_resume` LLM refinement times out, and the parser falls back
  to the heuristic path — the user sees their own bad result.
- Other users on different keys are unaffected; this is the intended
  isolation property of BYOK.

The proposed per-provider rate limit only matters when:
- the request hits the **shared** `settings.openai_api_key` /
  `settings.deepseek_api_key` server-side fallback path,
- or the operator runs a billing-pooled deployment where every user
  shares one provider quota.

### Decision

**Defer.** The current configuration favours BYOK; per-IP rate limit
already prevents one bad client from monopolising the shared API.
`llm_client.py`'s timeout + retry + breaker stops a bad upstream
provider from cascading into a thread starvation problem.

### Trigger to revisit

- A shared LLM key deployment is planned (e.g. enterprise plan).
- Observability shows shared-key 429 events per minute exceeding the
  documented headroom in `settings.llm_test_rate_limit_per_minute`.

### Suggested follow-up

- Add a `provider:host` rate limit bucket alongside the existing
  `endpoint:host` bucket; key the new bucket by the LLM provider
  resolved by `effective_llm_fingerprint`. Reuse the existing
  `RateLimitExceededError` envelope.
- Wire the breaker counter in `llm_client.py` into the rate-limit
  metric so a breaker-open state visibly tightens the bucket.

---

## F3. Cache-key per-tenant salt for `/resume/parse`

### Current state

`app/services/resume_parse_cache.py::resume_parse_cache_key` derives
the key from:

- `parser_version` (`PARSER_VERSION` constant; bump invalidates).
- `text_sha256(text)` (resume body content).
- `filename_sha256(filename)`.
- `effective_llm_fingerprint(llm_override)` (provider, model, base_url,
  temperature, stub flag).

The cache backend is in-memory (default) or Redis (when configured),
shared across **all** clients of the process / Redis instance.

### Failure mode

The cache **contents** are parser output (candidate_name, skills,
projects, focus_areas, …) — every value derived from the input text.
Therefore:

- Two different clients can only produce the same `cache_key` when they
  upload the **same body** (matching `text_sha256`) and configure the
  **same LLM fingerprint**.
- The only secret a cache hit reveals is "this exact resume body was
  parsed before". A cache hit does **not** leak data the second client
  did not already have, because they uploaded the matching body
  themselves.
- The remaining risk is **existence inference**: if an attacker who
  knows a candidate's resume text uploads it, a 200-with-cache hit
  proves the candidate ran an interview. This is a low-impact
  side-channel and would also leak via login enumeration.

### Decision

**Defer.** Adding an org/tenant salt has no user-visible benefit while
the deployment is single-tenant and BYOK already isolates LLM accounts.

### Trigger to revisit

- The product introduces a multi-tenant org concept (workspace, team,
  enterprise plan).
- Compliance review explicitly forbids existence-inference side
  channels (e.g. SOC2 control mapping).

### Suggested follow-up

- Extend `resume_parse_cache_key` to fold an `org_id` (or
  `tenant_salt`) into the `material` dict so caches are keyed by
  `(parser_version, text, filename, llm, org_id)`. Source `org_id`
  from the same request context that gates session ownership.
- Consider a separate Redis key prefix per org so eviction policies
  (e.g. GDPR delete) can scope to a tenant.

---

## Roll-up

| Item | State today | Defer? | Trigger to revisit |
|------|-------------|--------|--------------------|
| F1. Voice-ticket Redis store | In-memory dict, single worker | Yes | ≥ 2 workers without sticky sessions |
| F2. Per-provider rate limit | IP+endpoint only | Yes | Shared LLM key deployment |
| F3. Cache tenant salt | Single-tenant cache | Yes | Multi-tenant org concept lands |

None of the three items is a current correctness or security defect.
Each becomes mandatory once the listed trigger fires; the suggested
follow-up sections describe a minimal, non-disruptive path.
