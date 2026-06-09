# Phase 3.0 产品与上线决策

> Date: 2026-06-03
>
> Purpose: close the project as a portfolio-ready engineering artifact, not
> continue expanding it into a full commercial SaaS.

## 1. Stage Decision

Phase 3.0 is the project close-out phase.

The project has already moved beyond a local demo:

- the agentic interview workflow can complete the main loop,
- interview records have account ownership,
- platform-hosted LLM usage is controlled by credits,
- BYOK remains available for advanced users and local/debug usage,
- admin role, user management, credit adjustment, and credit requests exist,
- production preflight and a launch runbook exist.

The next obvious product systems would be email verification, invite codes,
payments, subscriptions, formal audit logs, and production operations. Those are
valid product work, but they are no longer needed to prove the core engineering
story of this project.

Decision: stop after Phase 3.0, then organize the project for README, demo, and
resume presentation.

## 2. Product Positioning

Agentic_Interviewer is not a model playground for people who want to test API
keys. It is an agentic workflow product for completing a high-quality mock
interview and receiving actionable feedback.

The product should be described as:

- an AI mock interview system,
- backed by a multi-agent workflow,
- with session recovery and interview record ownership,
- with a SaaS-style control plane for accounts, credits, and admin operations,
- hardened enough to reason about production launch risks.

The user value is:

- practice a realistic interview,
- receive structured multi-dimensional feedback,
- review weak areas,
- replay training paths,
- keep records tied to an account when desired.

The project should avoid recruitment-decision positioning. It is a training and
feedback tool, not a hiring decision engine.

## 3. Launch Mode

Recommended launch mode for this project state:

1. Portfolio demo.
2. Private beta / small internal trial.
3. Optional non-profit / public-interest community trial with operator-managed
   access.

Not recommended yet:

- fully open public launch,
- paid self-serve launch,
- unlimited free public signup,
- broad production deployment without email verification or invite control.

Reason:

The workflow and control plane are credible, but public self-serve launch would
immediately require abuse prevention, payment operations, support process,
provider quota monitoring, privacy policy, and account recovery. Those are
important, but they would turn the project into an operations-heavy product
rather than a focused engineering portfolio artifact.

## 4. Business Model Decision

Default model remains:

- platform-hosted LLM Key,
- users consume interview credits,
- one interview currently costs one credit,
- BYOK remains as an advanced mode.

Why this fits:

- The target user wants a mock interview result, not an API playground.
- Credits are easier to understand than token billing.
- A unified "one interview = one credit" rule is simple enough for early users.
- BYOK keeps demos, debugging, and power-user usage flexible without consuming
  platform quota.

Deferred:

- payment checkout,
- membership plans,
- subscription tiers,
- depth-based pricing,
- automatic refunds after post-start failures,
- invoice/order ledger.

Decision: do not implement payment or membership in this project close-out. Keep
the credit system as a demonstrated control-plane capability.

## 5. Registration and Abuse Control

Current state:

- local/dev registration can remain open,
- production preflight blocks the dangerous combination:
  `APP_ENV=prod` + open registration + free credits + no email verification
  requirement,
- free credits can be gated by future email verification,
- registration can be closed for controlled deployments.

Recommended project-close posture:

- local/demo: registration open is acceptable,
- portfolio demo: use test accounts or controlled registration,
- private beta: close registration after creating invited accounts,
- public launch: require email verification or invite codes before free credits.

Decision:

Do not build full email verification or invite-code backend in Phase 3.0. Keep
the anti-abuse hooks and production preflight as evidence that the risk is
understood and controlled at launch time.

## 6. Admin and Operations Control Plane

Current admin scope is enough for demo/private beta:

- admin role login,
- admin bootstrap via `promote_admin`,
- user list and detail,
- enable/disable normal users,
- credit balances and ledgers,
- credit request approval/rejection,
- interview history and observability surfaces,
- production runbook and smoke drill.

Important boundary:

- admin role changes are not exposed in the UI,
- normal users cannot become admin through frontend flows,
- `API_TOKEN` remains an emergency/bootstrap fallback,
- `ALLOW_OPEN_ADMIN=true` is local/demo only.

Decision:

Do not expand into a full SaaS operations suite. The current admin panel should
be presented as a focused control plane that closes the ownership, credits, and
observability loop.

## 7. Deployment Decision

Production-ready posture is documented, but this project does not need a full
public production deployment before resume packaging.

Minimum deployable posture:

- HTTPS frontend and backend,
- Postgres for DB and checkpointing,
- Redis for production rate limiting and voice tickets,
- Chroma reachable when non-stub embeddings are enabled,
- platform LLM key stored only in backend secrets,
- `APP_ENV=prod` preflight passes,
- admin account bootstrapped through normal account + promote script,
- smoke drill from `PRODUCTION_READINESS_RUNBOOK.md` passes.

Decision:

Use the runbook as the production readiness artifact. A live public deployment
is optional; a controlled demo recording or local/staging walkthrough is enough
for portfolio presentation.

## 8. What To Showcase

The project should be packaged around the following engineering story:

1. Main workflow:
   Multi-agent interview loop, scoring, feedback, replay, recovery.

2. Control plane:
   Login/register, account-owned records, session claim, admin role, user
   management.

3. Usage governance:
   Platform-hosted credits, BYOK boundary, credit ledger, credit requests.

4. Production readiness:
   Preflight, DB upgrade safety, cookie/auth caveats, runbook, smoke drill.

5. Product restraint:
   Clear non-goals around payment, email verification, invite codes, and full
   SaaS operations.

6. Evaluation restraint:
   The project has reviewed acceptance checks, replayable traces, and computed
   credibility signals, but human-labeled baseline evaluation is explicitly
   deferred until real interviewer samples exist.

This is stronger than presenting only screenshots. The valuable claim is that
the project connects workflow runtime and ownership/control-plane concerns
instead of stopping at a single chat-like demo.

## 9. Resume Framing

Suggested resume project title:

> Agentic AI Interviewer: Multi-Agent Mock Interview Workflow with SaaS Control
> Plane

Suggested bullets:

- Built a LangGraph-based multi-agent mock interview workflow covering session
  setup, adaptive questioning, scoring, final reports, replay, and recovery.
- Designed an account ownership layer for interview records, including
  anonymous-to-account claim flow and HttpOnly cookie authentication.
- Implemented a platform usage control plane with credits, append-only ledger,
  BYOK separation, admin adjustments, and user credit requests.
- Added admin role operations for user management, account status control,
  credit oversight, interview history, and workflow observability.
- Hardened launch readiness with production preflight checks, schema upgrade
  safeguards, deployment runbook, and smoke drill checklist.

Shorter version:

> Built a production-aware agentic mock interview system with multi-agent
> workflow orchestration, account-owned interview records, credit-based platform
> usage control, BYOK separation, admin operations, and launch-readiness
> preflight/runbook.

## 10. Final Backlog

These items are intentionally deferred, not forgotten.

### Public launch backlog

- email verification,
- invite-code or whitelist registration,
- captcha / bot protection,
- password reset and account recovery,
- privacy policy and user-facing data deletion policy,
- provider quota monitoring and alerting.

### Commercialization backlog

- payment checkout,
- order ledger,
- membership or package tiers,
- automatic credit top-up,
- refund policy,
- invoice/receipt handling.

### Admin hardening backlog

- admin action audit log,
- admin invite flow,
- admin session revocation,
- role change approval workflow,
- safer first-admin bootstrap script or seed process.

### Platform operations backlog

- staging/prod deployment automation,
- structured monitoring dashboard,
- backup/restore drill,
- load testing,
- provider failover policy,
- security review.

### Evaluation baseline backlog

- collect 20-50 human-reviewed interview samples,
- label each sample with senior-interviewer score bands, confidence, and notes,
- compare a simple prompt evaluator against the contract-governed evaluator,
- report agreement rate, confidence calibration, evidence misses, and score
  drift relative to the baseline,
- avoid public accuracy claims until the benchmark report is repeatable.

Decision:

These belong after the portfolio/resume milestone. They should be listed as
future work to show product judgment, not implemented now.

## 11. Phase 3.0 Done Definition

Phase 3.0 is complete when:

- this product/launch decision document exists,
- README can summarize the project in a portfolio-friendly way,
- an architecture one-pager can explain workflow + control plane + credits,
- demo path is documented,
- resume bullets are extracted,
- remaining Phase 3.x work is clearly marked as future scope.

Suggested next close-out tasks:

1. Update the project README with a concise product summary and demo path.
2. Add an architecture one-pager.
3. Prepare resume bullets and a short project narrative.
4. Optionally record a local demo walkthrough.

After those, stop feature work.
