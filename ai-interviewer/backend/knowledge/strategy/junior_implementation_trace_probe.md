---
name: Junior Implementation Trace Probe
description: Ask junior candidates to reconstruct one concrete implementation path before abstract trade-offs.
display_name_zh: 初级实现链路追问
display_description_zh: 先让初级候选人复盘具体实现链路，再进入取舍讨论。
type: strategy
dimensions: [technical_depth, coding_quality, project_experience, problem_solving]
job_levels: [junior, mid]
memory_key: seed:junior_mid:implementation_trace_probe
---

Junior and mid-level candidates often give broad technology lists before showing
whether they understand the implementation path. Prefer a concrete trace first.

How to apply:
- Ask for the exact request/data flow through the feature they mentioned.
- Require one real component boundary, one data structure or table, and one failure point.
- If the candidate stays generic, provide a small anchor and ask them to continue from there.
- Move to trade-offs only after they can reconstruct the baseline path.

Pitfalls:
- Do not over-index on architecture vocabulary for junior candidates.
- Avoid asking for system-wide redesign before the candidate has described what they built.
