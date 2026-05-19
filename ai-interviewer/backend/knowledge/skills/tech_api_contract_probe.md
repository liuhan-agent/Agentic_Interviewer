---
id: tech_api_contract_probe
name: API Contract Probe
description: Probe API and integration answers for compatibility, error semantics, idempotency, and ownership.
status: active
priority: 7
direction_tags: [internet_tech]
role_tags: [java_backend, frontend_web, mobile, ai_fullstack, ai_agent, architect]
dimensions: [coding_quality, system_design, communication, technical_depth]
job_levels: [junior, mid, senior, staff, principal]
probe_intents: [contract_probe, tradeoff_probe, stakeholder_pushback_probe]
failure_categories: [vague_process, missing_risk_boundary, poor_communication]
generator_moves:
  - "Ask what request, response, error, versioning, or idempotency contract had to remain stable."
  - "Probe how caller and provider teams detected contract regression."
  - "Ask how backward compatibility or migration was communicated."
watch_for:
  - "Explains both technical contract and collaboration contract."
  - "Names concrete failure semantics, retry behavior, or version boundary."
avoid:
  - "Accepting 'we documented the API' without compatibility or regression mechanism."
  - "Ignoring mobile, frontend, partner, or AI tool caller constraints."
evaluator_rubric_hints:
  - "Credit contract surface, compatibility strategy, failure semantics, and owner communication."
positive_signals:
  - "Mentions schema validation, contract test, version gate, idempotency key, or error taxonomy."
negative_signals:
  - "Breaks callers silently or treats integration as only backend implementation."
score_bias_rules:
  - "Soft positive when the candidate can explain how a caller would safely retry or recover."
evaluator_visibility: true
---

Use when the answer involves APIs, event contracts, tool schemas, SDKs, mobile
clients, frontend-backend collaboration, or partner integrations.

- Ask for the stable surface and failure semantics.
- Probe compatibility and communication.
- Require a regression detection path.
