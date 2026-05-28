---
name: Junior System Design Data Consistency
description: Probe junior system design through a small consistency scenario with clear state changes.
display_name_zh: 初级系统设计一致性追问
display_description_zh: 通过小范围状态变化观察初级候选人的一致性意识。
type: strategy
dimensions: [system_design, problem_solving, coding_quality]
job_levels: [junior, mid]
memory_key: seed:junior_mid:system_design_data_consistency
---

For junior and mid-level candidates, data consistency is easier to evaluate when
the question is framed around one small state transition.

How to apply:
- Pick one scenario such as duplicate submission, stale cache, partial update, or delayed message.
- Ask what state changes and where the source of truth lives.
- Require one idempotency, transaction, or reconciliation mechanism.
- If the answer is incomplete, provide one concrete failure and ask how they would detect it.

Pitfalls:
- Do not require distributed-systems vocabulary if the candidate can explain the state flow.
- Avoid mixing multiple consistency problems in the same question.
