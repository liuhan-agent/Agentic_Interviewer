---
id: tech_security_risk_boundary_probe
name: Security Risk Boundary Probe
description: Make security answers name assets, trust boundaries, abuse paths, and mitigation limits.
status: active
priority: 7
direction_tags: [internet_tech]
role_tags: [java_backend, frontend_web, sre, ai_fullstack, ai_agent, mobile, architect]
dimensions: [system_design, coding_quality, problem_solving, communication]
job_levels: [junior, mid, senior, staff, principal]
probe_intents: [risk_probe, architecture_challenge, tradeoff_probe]
failure_categories: [missing_risk_boundary, shallow_analysis, poor_communication]
generator_moves:
  - "Ask what asset was protected and where the trust boundary sits."
  - "Probe one realistic abuse path and the control that breaks it."
  - "Ask what mitigation limit, residual risk, or monitoring signal remained."
watch_for:
  - "Names data, identity, permission, tenant, supply-chain, or tool-execution boundary."
  - "Explains control failure modes instead of assuming a library solves the risk."
avoid:
  - "Accepting 'add auth', 'encrypt it', or 'sanitize input' without threat model."
  - "Letting the candidate hide all security reasoning behind a specialist team."
evaluator_rubric_hints:
  - "Credit asset, trust boundary, abuse path, control, and residual risk."
positive_signals:
  - "Mentions least privilege, tenant isolation, auditability, secret handling, or approval gate."
negative_signals:
  - "Cannot say who or what the system is defending against."
score_bias_rules:
  - "Soft positive when the candidate communicates risk to non-security stakeholders clearly."
evaluator_visibility: true
---

Use when a scenario touches auth, data exposure, permissions, AI tool actions,
privacy, compliance, or operational risk.

- Anchor the answer in asset and boundary.
- Ask for one abuse path.
- Require residual risk or monitoring after mitigation.
