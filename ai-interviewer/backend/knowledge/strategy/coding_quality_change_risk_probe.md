---
name: Coding Quality Change Risk Probe
description: Evaluate coding quality by asking how the candidate safely changes a live code path.
display_name_zh: 代码质量变更风险追问
display_description_zh: 通过线上代码变更过程观察代码质量与风险控制。
type: strategy
dimensions: [coding_quality, technical_depth, problem_solving]
job_levels: [junior, mid, senior, staff, principal]
memory_key: seed:all_levels:coding_change_risk
---

Coding quality is clearest when a candidate explains how they change production
code without breaking behavior.

How to apply:
- Ask for a recent risky change and the smallest safe migration step.
- Require test strategy, rollout control, and rollback trigger.
- If the candidate mentions refactoring, ask how they preserved observable behavior.
- If they mention performance, ask how they measured before and after.

Pitfalls:
- Do not reduce coding quality to naming or formatting.
- Avoid asking for full code unless the interview mode explicitly supports it.
