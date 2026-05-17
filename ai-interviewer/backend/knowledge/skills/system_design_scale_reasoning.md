---
id: tech_system_design_scale_reasoning
name: System Design Scale Reasoning
description: Force one concrete failure mode + one quantified scale argument per answer.
status: active
priority: 8
direction_tags: [internet_tech]
role_tags: [java_backend, frontend_web, sre, ai_fullstack, ai_agent, mobile, ai_algorithm, architect]
dimensions: [system_design, architecture]
job_levels: [mid, senior, staff, principal]
probe_intents: [architecture_challenge, performance_probe, tradeoff_probe]
failure_categories: [missing_scale_reasoning, vague_architecture, missing_failure_mode]
---

Every system-design question must, by the time the candidate is done,
surface **two artefacts**:

1. **One concrete failure mode**: network partition, clock skew,
   cache poisoning, thundering herd, cold start, split brain, tail
   latency amplification, etc. Generic "handle errors" or "use
   retries" does NOT count. Insist on a scenario the system
   misbehaves in, and the mitigating mechanism.

2. **One quantified scale argument**: a number that bounds the
   design's viability. Examples:
   - "Each node handles 10k RPS because a single hot key saturates
     the Redis eviction queue above that."
   - "We shard by tenant\_id because p99 tenant size is 2M rows and
     a single Postgres primary tops out around 50M rows before
     autovacuum starvation."

Good probes to elicit these when the candidate skates over:

- "What breaks first as you 10× the load?"
- "Which component owns the failure mode at partition time — the
  CAP trade-off should be on ONE side, not hand-waved."
- "If the primary node dies, what's the blast radius in seconds?"

Evaluator grading bias: an answer that hits both artefacts is at
least a "partial" even when other acceptance checks falter; an
answer missing both should be "partial at best" regardless of
eloquence elsewhere.
