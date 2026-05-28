---
name: Senior Failure Mode Probe
description: Test senior candidates by forcing their design through realistic failure modes.
display_name_zh: 高阶故障模式追问
display_description_zh: 用真实故障路径检验高阶候选人的设计鲁棒性。
type: strategy
dimensions: [system_design, problem_solving, project_experience]
job_levels: [senior, staff, principal]
memory_key: seed:senior_plus:failure_mode_probe
---

For senior candidates, failure handling often separates real experience from
diagram-level knowledge. Probe one failure path end to end.

How to apply:
- Pick one failure from the candidate's own design: duplicate message, stale cache, partial deploy, queue backlog, or downstream outage.
- Ask how the system detects, contains, and recovers from that failure.
- Require one customer impact and one operational metric.
- Ask what they changed after the incident or what they would change before launch.

Pitfalls:
- Do not accept "retry" as a complete recovery plan.
- Avoid hypothetical chaos testing unless it ties back to their concrete project.
