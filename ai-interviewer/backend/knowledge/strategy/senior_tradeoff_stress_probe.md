---
name: Senior Trade-off Stress Probe
description: Stress senior answers by changing one constraint and asking what they would sacrifice.
display_name_zh: 高阶取舍压力追问
display_description_zh: 通过改变约束检验高阶候选人的技术取舍能力。
type: strategy
dimensions: [system_design, technical_depth, problem_solving]
job_levels: [senior, staff, principal]
memory_key: seed:senior_plus:tradeoff_stress_probe
---

Senior candidates should be able to defend design choices under changing
constraints. A strong follow-up modifies one constraint and asks for the trade-off.

How to apply:
- Change exactly one constraint: latency, cost, consistency, team size, blast radius, or time-to-ship.
- Ask what they would sacrifice and why.
- Require a concrete operational signal that would prove the choice is working.
- If the answer is strong, ask for the rollback or migration path.

Pitfalls:
- Do not ask multiple constraint changes in one turn.
- Avoid textbook "pros and cons"; require a decision and a consequence.
