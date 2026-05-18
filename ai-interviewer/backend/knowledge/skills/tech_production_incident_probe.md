---
id: tech_production_incident_probe
name: Production Incident Probe
description: Drive incident answers toward root cause, blast radius, mitigation, and prevention.
status: active
priority: 7
direction_tags: [internet_tech]
role_tags: [java_backend, frontend_web, sre, ai_fullstack, ai_agent, mobile, ai_algorithm, architect]
dimensions: [problem_solving, technical_depth, project_experience, communication]
job_levels: [mid, senior, staff, principal]
probe_intents: [debugging_probe, escalation_probe, performance_probe]
failure_categories: [root_cause_missing, missing_risk_boundary, poor_communication]
generator_moves:
  - "Ask for detection signal, first mitigation, blast radius, root cause, and prevention."
  - "If they jump to solution, ask how they knew that was the cause."
watch_for:
  - "Distinguishes mitigation from root-cause fix and includes communication or rollback."
avoid:
  - "Accepting code-only incident answers that ignore monitoring, rollout, or customer impact."
evaluator_rubric_hints:
  - "Credit clear sequence: detect, mitigate, scope, diagnose, prevent."
positive_signals:
  - "Names concrete alert, metric, affected population, and permanent guardrail."
negative_signals:
  - "Skips blast radius or cannot separate symptom from cause."
score_bias_rules:
  - "Soft positive when prevention includes both technical guardrail and operating process."
evaluator_visibility: true
---

Use when a technical question touches outage, latency, error rate, failed
release, degraded model behavior, or customer-visible instability.

- Ask for detection signal, first mitigation, blast radius, root cause, and
  permanent prevention.
- If they jump to solution, pull back to "how did you know this was the
  cause?".
- If they only mention code, ask about rollout, monitoring, communication,
  and rollback.
- Strong answers distinguish mitigation from root-cause fix.
