# Internet Role Starter Question Bank

Use these notes as local retrieval seeds. Resume projects stay the primary
source of questions; these cards provide fundamentals and follow-up probes.

## Java backend
- For a Spring Boot service mentioned in the resume, ask how the candidate
  split domain logic, transaction boundaries, and retry/idempotency handling.
- When Redis appears, probe cache penetration, hot keys, stale reads, and
  invalidation ownership.
- When Kafka or RocketMQ appears, probe delivery semantics, consumer lag,
  duplicate consumption, dead-letter handling, and event schema evolution.

## Frontend
- For React/Vue projects, probe component boundaries, state ownership,
  rendering performance, error boundaries, and accessibility trade-offs.
- For engineering work, ask about build speed, dependency management,
  monitoring front-end errors, and safe rollout of UI changes.

## AI full stack
- Probe the handoff between product workflow, backend orchestration, model
  calls, streaming UI, cost control, and evaluation.
- Ask how the candidate detects prompt regressions, hallucination, latency
  spikes, and bad tool results in production.

## Mobile
- Probe startup performance, memory pressure, offline cache, crash diagnosis,
  release rollout, and cross-platform trade-offs.
- Ask for one concrete production incident and how telemetry narrowed it down.

## AI Agent
- Probe tool calling contracts, planner/executor boundaries, memory retrieval,
  evals, guardrails, permissions, and human handoff.
- Ask what breaks when an agent loops, calls the wrong tool, or trusts stale
  memory, and how the system detects and recovers.

## SRE
- Probe observability signals, incident response, capacity planning, SLOs,
  change management, rollback, and postmortem quality.
- Ask the candidate to quantify blast radius, detection time, and recovery
  time for one resume incident.

## AI algorithm
- Probe dataset construction, offline/online metrics, ablation design,
  inference cost, model drift, and error analysis.
- Ask how the candidate validated that a model improvement helped the product
  rather than only the leaderboard.

## Architect or technical expert
- Probe architecture decision records, migration sequencing, dependency
  governance, technical debt budgets, and cross-team alignment.
- Ask for one trade-off where the candidate rejected a popular technology and
  what evidence justified the decision.

## Algorithms and fundamentals
- For backend-heavy resumes, prefer applied algorithm questions: rate limiting,
  top-k, deduplication, scheduling, graph traversal, consistent hashing.
- For frontend-heavy resumes, prefer data structure questions tied to UI state,
  virtual lists, diffing, undo/redo, and dependency graphs.
- For AI resumes, prefer retrieval ranking, batching, caching, vector search
  trade-offs, and evaluation statistics.
