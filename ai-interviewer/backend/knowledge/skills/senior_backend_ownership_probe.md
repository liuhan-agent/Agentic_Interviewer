---
id: senior_backend_ownership_probe
name: Senior Backend Ownership Probe
description: Force ownership and quantified impact in senior backend answers.
display_name_zh: 高级后端 Ownership 追问卡
display_description_zh: 引导高级后端回答明确个人 ownership 和可量化影响。
status: active
priority: 7
direction_tags: [internet_tech]
role_tags: [java_backend, architect]
dimensions: [leadership, system_design, problem_solving]
job_levels: [senior, staff, principal]
probe_intents: [evidence_probe, case_study_probe, stakeholder_pushback_probe]
failure_categories: [generic_storytelling, missing_evidence, weak_ownership]
generator_moves:
  - "Ask what artifact, decision, rollout step, or on-call risk the candidate personally owned."
  - "Probe quantified impact and the boundary where ownership moved to another person or team."
watch_for:
  - "Separates personal ownership from team context without over-claiming."
avoid:
  - "Accepting first-person-plural storytelling as senior ownership evidence."
evaluator_rubric_hints:
  - "Credit quantified impact plus a clear ownership boundary across design, delivery, and rollout."
positive_signals:
  - "Names a concrete artifact such as RFC, migration plan, pager alert, or rollout gate."
negative_signals:
  - "Claims design, implementation, rollout, and operations without naming handoffs."
score_bias_rules:
  - "Soft negative when senior-level answers stay qualitative after a metrics probe."
evaluator_visibility: true
---

When interviewing senior / staff / principal backend candidates:

- Probe for **what the candidate personally owned**, not what "the team"
  did. If the answer stays in first-person plural, the next probe
  should name a concrete artefact ("who wrote the RFC?", "whose
  on-call burned?", "which pager alert did you specifically silence?").
- Reject **buzzword-heavy storytelling** that does not quantify
  impact. A valid senior-level answer includes at least one number:
  latency saved, incidents prevented, cost reduced, headcount
  unblocked. If the candidate keeps speaking in qualitative terms,
  the follow-up question is always "by how much, over what window?".
- **Ownership asymmetry**: a candidate taking credit for design AND
  implementation AND rollout AND on-call is usually a solo
  contributor in an engineering team. Probe one layer deeper on each
  claim to surface true ownership boundaries — the strongest
  signals come from the parts they explicitly hand off.
- When the candidate mentions a **migration** or **decommission**,
  the follow-up is always: "what did you leave running in
  compatibility mode, and for how long?". Clean answers rarely
  come from senior ICs who did real migrations.
