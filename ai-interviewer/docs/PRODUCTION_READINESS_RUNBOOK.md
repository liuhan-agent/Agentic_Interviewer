# Production Readiness Runbook & Smoke Drill

> Scope: Phase 2.6 is a production-readiness pass for the current control plane.
> It does not add payment, membership plans, email verification flows, invite
> codes, password reset, or a broader role system.

## 1. Launch Posture

Agentic_Interviewer is now a platform-hosted interview product with optional
BYOK:

- Platform-hosted mode uses the operator's backend LLM key and consumes user
  interview credits.
- BYOK mode uses the user's personal API key from the setup UI and does not
  consume platform credits.
- Account-owned interview records are isolated by `owner_user_id`.
- Admin access is personal-account based (`role=admin`). `API_TOKEN` remains a
  bootstrap / emergency fallback, not the normal human admin login path.

Recommended production topology:

- FastAPI backend on HTTPS.
- Next.js frontend on HTTPS.
- Postgres for application state and durable HITL checkpoints.
- Redis for shared rate limits, resume parse cache, and voice tickets.
- Chroma reachable when non-stub embeddings / RAG are enabled.

Production should not use SQLite, memory checkpoints, memory rate limits, open
admin, or stub LLM defaults.

## 2. Environment Checklist

### Required for production

Set these in the backend runtime environment or secret manager:

| Variable | Production value | Why it matters |
| --- | --- | --- |
| `APP_ENV` | `prod` | Enables hard production preflight and secure auth cookies. |
| `DATABASE_URL` | Postgres DSN | Stores users, sessions, credits, admin state, traces, and checkpoints. |
| `CHECKPOINT_BACKEND` | `postgres` | Keeps interrupted interviews recoverable after restarts. |
| `REDIS_URL` | Redis DSN | Shared backing store for production rate limits and voice tickets. |
| `RATE_LIMIT_BACKEND` | `redis` | Prevents per-worker limit multiplication. |
| `RESUME_PARSE_CACHE_BACKEND` | `redis` | Avoids process-local cache divergence. |
| `VOICE_TICKET_BACKEND` | `redis` | Lets voice tickets survive load balancing across workers. |
| `API_TOKEN` | High-entropy secret | Emergency admin fallback and deployment-level gate. |
| `ALLOW_OPEN_ADMIN` | `false` | Prevents admin surfaces from opening without credentials. |
| `LLM_PROVIDER` | Non-`stub` provider | Enables real platform-hosted interviews. |
| Provider API key | e.g. `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `DEEPSEEK_API_KEY`, or provider-compatible key | Backend platform-hosted LLM credential. Never expose it as `NEXT_PUBLIC_*`. |
| `EMBEDDING_PROVIDER` | usually `openai` | Non-stub embeddings require Chroma reachability in prod. |

Frontend production settings:

| Variable | Production value | Notes |
| --- | --- | --- |
| `NEXT_PUBLIC_API_BASE` | Backend HTTPS origin, or empty for same-origin reverse proxy | If set to a different origin, CORS and cookies must be configured carefully. |
| `NEXT_PUBLIC_ADMIN_NAV_ENABLED` | `true` only for admin deployments | `false` hides and redirects `/admin`; backend auth still remains the real gate. |

### Recommended

| Variable | Suggested value | Notes |
| --- | --- | --- |
| `AUTH_SESSION_TTL_DAYS` | `14` or shorter | Account login cookie lifetime. |
| `AUTH_REGISTER_RATE_LIMIT_PER_MINUTE` | Small public value | Register endpoint IP limit. |
| `AUTH_LOGIN_RATE_LIMIT_PER_MINUTE` | Small public value | Login endpoint IP limit. |
| `ANONYMOUS_SESSION_START_RATE_LIMIT_PER_MINUTE` | Conservative value | Anonymous BYOK / dev start protection. |
| `ENABLE_PRIVACY_CLEANUP` | `true` after retention policy is approved | Hard-deletes old data. Dry run first if available. |
| `SESSION_RETENTION_DAYS` | Business-approved retention | Applies when privacy cleanup is enabled. |
| `TRACE_RETENTION_DAYS` | Business-approved retention | Admin observability data retention. |
| `LANGSMITH_TRACING` | Optional | Use env-suffixed projects to avoid mixing prod and dev traces. |
| `CORS_ORIGINS` | Exact frontend origins | Include scheme and host, no wildcard in production. |

### Registration and free-credit safety

Current safe production choices are:

- `AUTH_REGISTRATION_MODE=closed`, or
- `FREE_CREDITS_REQUIRE_EMAIL_VERIFIED=true`, or
- `FREE_INTERVIEW_CREDITS=0`.

If `APP_ENV=prod`, `AUTH_REGISTRATION_MODE=open`, `FREE_INTERVIEW_CREDITS>0`,
and `FREE_CREDITS_REQUIRE_EMAIL_VERIFIED=false`, startup preflight must fail.
This intentionally prevents public signup from creating unlimited free-credit
abuse before a real email verification or invite system exists.

### Dangerous defaults

Do not launch with these unless the deployment is intentionally local/demo:

- `APP_ENV=dev`
- `CHECKPOINT_BACKEND=memory`
- `RATE_LIMIT_BACKEND=memory`
- `VOICE_TICKET_BACKEND=memory`
- `RESUME_PARSE_CACHE_BACKEND=memory`
- `ALLOW_OPEN_ADMIN=true`
- empty `API_TOKEN`
- `LLM_PROVIDER=stub` or missing provider API key that makes `use_stub_llm=true`
- `EMBEDDING_PROVIDER=stub` without an explicit emergency exception
- frontend built with `NEXT_PUBLIC_API_BASE=http://localhost:8000`
- production backend served over plain HTTP while `APP_ENV=prod` auth cookies
  are marked `Secure`

## 3. Preflight Rules

Backend startup calls `run_preflight(settings)` from `app/main.py`. In `dev` and
`test`, unsafe settings log warnings. In `prod`, unsafe settings raise
`PreflightError` and block startup.

The same checks can be run manually:

```powershell
cd D:\Agent\Agentic_Interviewer\ai-interviewer\backend
python -m app.scripts.production_smoke
```

Run dependency probes before launch:

```powershell
cd D:\Agent\Agentic_Interviewer\ai-interviewer\backend
python -m app.scripts.production_smoke --check-deps
```

If the package entry points are installed, the equivalent command is:

```powershell
interviewer-prod-smoke --check-deps
```

The smoke CLI prints only sanitized booleans, enums, host/port metadata, and
probe status. It must not print raw secrets, database passwords, Redis
passwords, or API tokens.

Current production hard failures include:

- `CHECKPOINT_BACKEND=memory`
- empty `API_TOKEN`
- stub LLM mode
- `EMBEDDING_PROVIDER=stub` unless explicitly allowed
- `RESUME_PARSE_CACHE_BACKEND=memory`
- `RATE_LIMIT_BACKEND=memory`
- `VOICE_TICKET_BACKEND=memory`
- open registration + free credits + no email verification requirement
- Chroma unreachable when non-stub embeddings are enabled

## 4. Database Preparation

Production should use Postgres. The SQLite fallback is only for dev/demo and is
refused when `APP_ENV=prod`.

Startup runs `init_db()`:

- imports all model modules,
- runs `Base.metadata.create_all`,
- creates auth, credit, and credit-request tables,
- applies additive schema upgrades for existing SQLite/Postgres tables,
- creates pgvector-related indexes when available.

Schema upgrades are intentionally additive (`ADD COLUMN` / `ADD COLUMN IF NOT
EXISTS`) and idempotent. They do not drop columns or backfill data. On Postgres,
`ADD COLUMN` still takes a short table lock, so for large production tables:

1. Back up the DB before first production boot after schema changes.
2. Prefer starting one backend instance first and watching startup logs.
3. Run the smoke CLI with `--check-deps` before putting traffic on the app.
4. If using multiple backend workers, avoid simultaneous first boot during a
   schema-changing release.

Before the first content-backed production run, also import structured content
as needed:

```powershell
cd D:\Agent\Agentic_Interviewer\ai-interviewer\backend
python -m app.scripts.import_question_seeds --archive-missing
python -m app.scripts.import_skill_playbooks --archive-missing
python -m app.scripts.seed_kb
```

## 5. Admin Bootstrap

There is no default administrator account.

Bootstrap sequence:

1. Configure safe production registration posture. For the first controlled
   bootstrap window, either temporarily allow registration with
   `FREE_INTERVIEW_CREDITS=0`, or keep registration closed and create the user
   through an internal DB seed/manual process.
2. Register the intended admin email as a normal account.
3. Promote that existing account:

```powershell
cd D:\Agent\Agentic_Interviewer\ai-interviewer\backend
python -m app.scripts.promote_admin --email admin@example.com
```

4. Restart or continue the backend with normal production env.
5. Log in through the frontend using that account.
6. Open `/admin`. The backend authorizes by active `role=admin` cookie. The
   `API_TOKEN` bearer path remains available for emergency/operator scripts.

Safety notes:

- Do not expose `ALLOW_OPEN_ADMIN=true` in production.
- Do not distribute `API_TOKEN` as a routine shared human login credential.
- Admin role changes are intentionally not exposed in the admin UI; promotion is
  an operator script action.

## 6. Platform LLM Key and BYOK

Platform-hosted interviews:

- use backend provider env vars such as `OPENAI_API_KEY` or
  `ANTHROPIC_API_KEY`,
- require login in production,
- debit one interview credit at session start,
- return `billing_mode=platform_credits`, `credit_delta=-1`, and the remaining
  `credit_balance`.

BYOK interviews:

- are detected when setup includes a personal API key in `llm_config` or
  role-specific overrides,
- return `billing_mode=byok`,
- do not debit platform credits,
- may still consume the user's own model-provider quota,
- can remain available for anonymous advanced/debug flows.

Do not put the platform LLM key in frontend env vars. Any `NEXT_PUBLIC_*` value
is browser-visible.

## 7. Pre-launch Smoke Drill

Run this checklist in staging or a locked production preview before public
traffic.

### Backend

```powershell
cd D:\Agent\Agentic_Interviewer\ai-interviewer\backend
python -m app.scripts.production_smoke --check-deps
python -m pytest tests/unit/test_deployment_preflight.py tests/unit/test_sqlite_schema_upgrade.py tests/unit/test_user_auth_api.py tests/unit/test_admin_auth.py -q
```

Expected:

- preflight prints sanitized configuration and exits 0,
- Postgres, Redis, and Chroma probes are OK for prod,
- targeted tests pass.

### Frontend build

```powershell
cd D:\Agent\Agentic_Interviewer\ai-interviewer\frontend
node --test tests/authControlPlaneSource.test.js tests/appShellNavigationSource.test.js tests/adminObservabilitySource.test.js tests/setupFormSource.test.js
npm run typecheck
npm run build
```

Expected:

- source checks verify auth credentials, admin gate, and setup credit UI,
- typecheck passes,
- production build succeeds.

### Browser flow

Use HTTPS production-like URLs.

1. Open the frontend and verify `/health` reaches the backend.
2. Register or log in as a normal user.
3. Refresh the page. Account state should remain logged in.
4. Open the account/credits panel. It should show balance, recent ledger, and
   credit request controls.
5. Start a platform-hosted interview without BYOK. It should require login,
   create an owned session, and debit one credit.
6. Refresh and open "My Interviews". The new interview should appear as an
   account record.
7. Configure a personal API key and start a BYOK interview. It should not debit
   platform credits.
8. Submit a credit request as a normal user.
9. Log in as admin and open `/admin`.
10. Verify account management, user credits, credit request approval/rejection,
    admin interview history, and trace pages.
11. Approve a credit request and confirm the user's ledger/balance changes.
12. Disable a test normal user, then verify that user's existing cookie no
    longer authenticates.

## 8. Troubleshooting

### `401 Unauthorized`

Likely causes:

- user is not logged in,
- auth cookie is missing, expired, or revoked,
- backend sees `APP_ENV=prod` and sets a `Secure` cookie, but the site is served
  over HTTP,
- frontend and backend are on different origins and cookies are not being sent,
- `NEXT_PUBLIC_API_BASE` points at a different host than the browser origin
  expects.

Checks:

- Browser devtools -> Application -> Cookies: look for `ai_interviewer_auth`.
- Network tab: auth/account requests should include credentials.
- Backend CORS must allow the exact frontend origin and credentials.
- For local testing, prefer the same host spelling (`localhost` vs
  `127.0.0.1`) for frontend and backend.

### `403 Forbidden`

Likely causes:

- logged-in account is `role=user`, not `role=admin`,
- admin fallback token is wrong,
- registration-created account was never promoted,
- user status is `disabled`.

Checks:

```powershell
cd D:\Agent\Agentic_Interviewer\ai-interviewer\backend
python -m app.scripts.promote_admin --email admin@example.com
```

Then log out and log in again.

### `402 platform_credits_exhausted`

The user has no platform interview credits. This is expected when balance is 0.

Options:

- use BYOK,
- approve a credit request,
- use admin credit adjustment,
- verify whether `FREE_CREDITS_REQUIRE_EMAIL_VERIFIED=true` is preventing the
  initial free grant for an unverified email.

### Login disappears after refresh

Most common causes:

- `APP_ENV=prod` on an HTTP backend, so the secure cookie is not stored/sent,
- frontend built with the wrong `NEXT_PUBLIC_API_BASE`,
- cross-origin deployment without matching `CORS_ORIGINS`,
- switching between `localhost` and `127.0.0.1`,
- proxy strips `Set-Cookie`.

Prefer same-origin deployment or a reverse proxy that serves frontend and API
under one HTTPS site. If split-origin, confirm CORS credentials and cookie
behavior in the browser, not only with curl.

### Admin page inaccessible

Checks:

- `NEXT_PUBLIC_ADMIN_NAV_ENABLED=true` for the frontend build/runtime if admin UI
  should be visible.
- Backend account is active and `role=admin`.
- `API_TOKEN` is configured for emergency fallback.
- `ALLOW_OPEN_ADMIN=false` in production.
- Middleware redirects `/admin` when the public admin nav switch is disabled.

### Production preflight fails

Read the full `PreflightError` message. The fix is normally one env var:

- set `CHECKPOINT_BACKEND=postgres`,
- configure `API_TOKEN`,
- configure a real LLM provider key,
- set Redis-backed shared stores,
- make Chroma reachable,
- close registration or require verified email before granting free credits.

Do not bypass preflight by changing `APP_ENV` to `dev` for a public deployment.

### LLM key missing or wrong

`settings.use_stub_llm` becomes true when the selected provider key is empty or
looks like a placeholder. In production this blocks startup. Confirm:

- `LLM_PROVIDER`,
- provider key env var,
- model name,
- provider-specific base URL for compatible providers,
- no platform key is present in frontend env.

For a user-specific failure, confirm whether the session was BYOK and whether
their personal provider key is valid.

### DB / Redis / Chroma problems

Use:

```powershell
cd D:\Agent\Agentic_Interviewer\ai-interviewer\backend
python -m app.scripts.production_smoke --check-deps
```

Common fixes:

- wrong `DATABASE_URL` credentials or host,
- Postgres missing pgvector extension support,
- Redis URL unreachable from the backend runtime,
- Chroma host/port not reachable from the backend runtime,
- multiple backend workers started before schema upgrade completed.

## 9. Rollback and Emergency Actions

Low-risk toggles:

- close new registration: `AUTH_REGISTRATION_MODE=closed`,
- disable free grants: `FREE_INTERVIEW_CREDITS=0`,
- require verified email for free grants:
  `FREE_CREDITS_REQUIRE_EMAIL_VERIFIED=true`,
- hide admin UI entry: `NEXT_PUBLIC_ADMIN_NAV_ENABLED=false`,
- force users to BYOK temporarily by not running platform-hosted starts until
  backend LLM/provider quota is healthy,
- disable open admin: `ALLOW_OPEN_ADMIN=false`,
- rotate `API_TOKEN` after any suspected exposure.

Operational rollback:

1. Stop new deploy traffic.
2. Restore the previous backend/frontend release.
3. Restore DB from backup only if the release corrupted data; avoid restoring DB
   just to roll back UI.
4. Run production smoke with dependency probes.
5. Verify login, credit balance, platform start, and admin access before
   reopening traffic.

Credit-specific compensation:

- If a session failed before the start response, the backend attempts a
  best-effort refund.
- If the interview started successfully and later failed, use admin manual credit
  adjustment or approve a credit request. Phase 2.6 does not implement automatic
  post-start refunds.

## 10. Deferred Phase 3 Items

These are intentionally out of scope for Phase 2.6:

- real email verification and email delivery,
- invite-code registration,
- captcha / bot protection,
- payment and membership plans,
- admin role delegation UI,
- full audit log for admin actions,
- multi-tenant org/workspace isolation,
- automated post-start credit refund policy.

Do not weaken the current production preflight to compensate for these missing
systems. Use the safe registration/free-credit posture instead.
