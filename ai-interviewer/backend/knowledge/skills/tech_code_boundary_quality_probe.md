---
id: tech_code_boundary_quality_probe
name: Code Boundary Quality Probe
description: Check whether engineering quality is visible in contracts, tests, ownership boundaries, and failure handling.
status: active
priority: 6
direction_tags: [internet_tech]
role_tags: [java_backend, frontend_web, ai_fullstack, ai_agent, mobile]
dimensions: [coding_quality, technical_depth, problem_solving]
job_levels: [junior, mid, senior, staff]
probe_intents: [evidence_probe, debugging_probe, tradeoff_probe]
failure_categories: [shallow_analysis, missing_evidence, vague_process]
---

Use when the question is about implementation quality rather than pure
architecture.

- Ask which boundary the candidate owned: API contract, module interface,
  state management, data schema, test seam, or error-handling path.
- Ask what regression would have escaped without their chosen test or
  validation.
- If the answer is only "clean code", ask for the specific defect class they
  prevented.
- Strong answers connect code structure to an operational or product risk.

