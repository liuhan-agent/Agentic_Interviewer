# Remaining Architecture Risks Roadmap

## Summary

The recent architecture hardening work addressed the risks that were small,
bounded, and testable in one implementation pass:

- scoring credibility and evidence traceability
- LangGraph topology drift
- question polling response shaping in `interview.py`

The remaining risks are real, but should stay as roadmap items until their
production triggers appear. They need explicit product/runtime decisions more
than immediate code movement.

## 1. Experience Extractor Write Boundary

### Current Risk

`experience_extractor` can turn runtime interview experience into strategy
files. That is useful for a learning system, but production needs a clear
boundary between generated proposals and canonical strategy knowledge.

### Default Direction

Runtime extraction should produce draft/proposal artifacts only. Canonical
strategy files should require an explicit review or promotion step.

### Trigger

Revisit before enabling production strategy writes, scheduled background
extraction, or shared strategy updates across users.

### Future Acceptance Criteria

- Draft output location is separate from canonical strategy files.
- Each draft includes provenance: session id, trace id, source turn ids, model
  version, and generation time.
- Production direct-write is blocked by default through configuration.
- Promotion is explicit through an admin/review action.
- Tests cover blocked production writes and successful draft generation.

## 2. Thompson Bandit Multi-Process State

### Current Risk

The Thompson Bandit strategy is currently suitable for a single-worker MVP:
state is process-local with database rehydrate support. In a multi-worker
deployment, policy state can diverge between workers unless updates are moved
behind a shared consistency boundary.

### Default Direction

Keep the single-worker assumption documented for now. Do not introduce Redis,
database locking, or a policy service until horizontal scaling is a concrete
deployment requirement.

### Trigger

Revisit before running more than one backend worker, enabling autoscaling, or
using shared strategy learning in production traffic.

### Future Options

- Database transaction-backed posterior updates.
- Redis or another shared low-latency policy state store.
- Dedicated policy module/service with idempotent reward application.

### Future Acceptance Criteria

- Reward updates are idempotent across retries.
- Multiple workers observe a consistent posterior after updates.
- Rehydration has a clear source of truth.
- Admin observability can explain policy state, sample counts, and recent
  reward effects.

## 3. Frontend State Management Evolution

### Current Risk

The frontend is intentionally business-thin today, but several components are
large. Account identity, multi-device history, subscriptions, and longer-lived
training flows will add pressure to local component state and ad hoc data
passing.

### Default Direction

Do not add a global state framework yet. Prefer extracting route-level data
hooks, typed view models, and smaller workflow components first.

### Trigger

Revisit when the product adds account identity plus at least one of:

- multi-device session history
- subscription or entitlement state
- resumable training plans across sessions
- cross-route candidate progress dashboards

### Future Acceptance Criteria

- Route-level data hooks own fetch/cache/error behavior.
- Components receive typed view models instead of raw API payloads where the
  view has meaningful derivation logic.
- Session history and entitlement state have explicit invalidation rules.
- Tests cover the main authenticated history and resume flows.

## Tracking

Keep these as roadmap risks until the triggers above occur. When one trigger
becomes active, promote that section into a focused ADR or implementation issue
with a concrete acceptance test plan.
