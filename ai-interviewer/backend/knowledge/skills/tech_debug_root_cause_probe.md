---
id: tech_debug_root_cause_probe
name: Debug Root Cause Probe
description: Keep debugging answers anchored in evidence, hypothesis ordering, and verified root cause.
status: active
priority: 8
direction_tags: [internet_tech]
role_tags: [java_backend, frontend_web, sre, ai_fullstack, ai_agent, mobile, ai_algorithm, architect]
dimensions: [problem_solving, technical_depth, project_experience]
job_levels: [junior, mid, senior, staff, principal]
probe_intents: [debugging_probe, evidence_probe, incident_probe]
failure_categories: [root_cause_missing, shallow_analysis, missing_evidence]
generator_moves:
  - "Ask what signal first proved the issue existed and what hypothesis they tested first."
  - "Probe how they ruled out adjacent causes before declaring root cause."
  - "Ask what verification proved the fix worked and would stay fixed."
watch_for:
  - "Orders hypotheses by evidence, blast radius, and reversibility."
  - "Separates symptom, trigger, root cause, mitigation, and prevention."
avoid:
  - "Accepting a lucky fix as root-cause analysis."
  - "Letting the answer skip how they falsified wrong hypotheses."
evaluator_rubric_hints:
  - "Credit evidence-driven diagnosis, ruled-out hypotheses, and verification signal."
positive_signals:
  - "Names logs, traces, metrics, reproduction steps, or experiment evidence."
negative_signals:
  - "Jumps from symptom directly to solution without diagnostic path."
score_bias_rules:
  - "Soft positive when the candidate identifies a wrong hypothesis and why it was eliminated."
evaluator_visibility: true
---

Use when a technical answer claims a problem was debugged, fixed, or diagnosed.

- Keep the candidate on the sequence from signal to hypothesis to validation.
- Ask for a specific wrong branch they ruled out.
- Require a verification signal after the fix, not only the fix itself.
