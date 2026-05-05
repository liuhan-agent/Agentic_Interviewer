---
name: Senior System Design Strategy
description: Deep follow-ups outperform surface-level questions for senior candidates in system design
type: strategy
dimensions: [system_design]
job_levels: [senior, staff, principal]
---

Senior candidates in system design benefit most from `deepen_technical` actions that
push into concrete trade-off analysis rather than asking them to enumerate components.

Why:
Senior engineers can easily produce textbook component lists. The differentiating signal
comes from probing *why* they chose one approach over another, what they would change
under different constraints, and how they handle failure modes.

How to apply:
- After the first system-design question, prefer `deepen_technical` over `switch_dimension`.
- Ask about trade-offs: "What would you sacrifice if latency requirements doubled?"
- Probe failure modes: "How does your design handle a datacenter failover?"
- If the candidate gives a strong initial answer, increase difficulty to hard.

Pitfalls:
- Avoid asking the same trade-off question pattern twice in a row.
- If the candidate struggles after one deepening round, switch to `give_hint` before trying again.
