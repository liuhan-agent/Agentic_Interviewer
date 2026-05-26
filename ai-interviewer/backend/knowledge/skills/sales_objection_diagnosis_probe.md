---
id: sales_objection_diagnosis_probe
name: Sales Objection Diagnosis Probe
description: Make sales answers diagnose the objection before pitching a solution.
display_name_zh: 销售异议诊断追问卡
display_description_zh: 引导销售回答先诊断异议来源，再提出解决方案。
status: active
priority: 7
direction_tags: [business]
role_tags: [sales_business]
dimensions: [customer_discovery, solution_matching, objection_handling, negotiation, pipeline_management]
job_levels: [junior, mid, senior]
probe_intents: [objection_probe, roleplay_probe, case_study_probe]
failure_categories: [shallow_analysis, missing_evidence, weak_follow_up]
generator_moves:
  - "Ask what the objection really represented: value, timing, budget, authority, risk, or trust."
  - "Probe the discovery question that changed the candidate's next move."
watch_for:
  - "Diagnoses before pitching and defines a concrete next step."
avoid:
  - "Accepting a generic rebuttal script without customer-specific evidence."
evaluator_rubric_hints:
  - "Credit objection diagnosis, stakeholder mapping, and CRM next-step discipline."
positive_signals:
  - "Names the buyer role, objection type, and follow-up artifact."
negative_signals:
  - "Pushes solution features before clarifying the customer's concern."
score_bias_rules:
  - "Soft positive when the answer distinguishes stated objection from underlying buying risk."
evaluator_visibility: true
---

Use when the candidate handles customer objection, lost deal, pricing pressure,
or stalled pipeline.

- Ask what the customer was really worried about: value, timing, budget,
  authority, risk, or trust.
- Ask which discovery question changed their understanding of the deal.
- Ask what they did next in CRM or stakeholder mapping.
- Strong answers diagnose before pitching and define a concrete next step.
