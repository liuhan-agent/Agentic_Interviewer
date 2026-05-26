---
id: tech_rollout_migration_probe
name: Rollout And Migration Probe
description: Probe staged rollout, compatibility, rollback, and ownership in technical delivery stories.
display_name_zh: 发布与迁移追问卡
display_description_zh: 引导技术交付故事覆盖分阶段发布、兼容性、回滚路径和责任归属。
status: active
priority: 6
direction_tags: [internet_tech]
role_tags: [java_backend, frontend_web, sre, ai_fullstack, ai_agent, mobile, architect]
dimensions: [project_experience, system_design, problem_solving, communication]
job_levels: [junior, mid, senior, staff, principal]
probe_intents: [case_study_probe, escalation_probe, stakeholder_pushback_probe]
failure_categories: [missing_risk_boundary, weak_communication, weak_follow_up]
generator_moves:
  - "Ask what stayed compatible during rollout and what signal would stop the release."
  - "Probe stakeholder approval, objection, rollback owner, and monitoring window."
watch_for:
  - "Includes staged rollout, fallback, observability, and handoff."
avoid:
  - "Accepting a migration story that has no coexistence period or rollback trigger."
evaluator_rubric_hints:
  - "Credit compatibility plan, rollback gate, rollout owner, and post-launch observation."
positive_signals:
  - "Names a stop condition and who had authority to trigger it."
negative_signals:
  - "Frames migration as a code merge rather than a controlled operational change."
score_bias_rules:
  - "Soft positive when the candidate explains what remained in compatibility mode."
evaluator_visibility: true
---

Use when the candidate discusses migration, refactor, release, platform change,
AI feature launch, or infra rollout.

- Ask what stayed compatible during the rollout and for how long.
- Ask what signal would have stopped or rolled back the release.
- Ask who had to agree before broad rollout and what objection they raised.
- Strong answers include a staged plan, fallback, observability, and owner
  handoff.
