---
name: Junior Recovery Hint Strategy
description: Use a bounded hint to recover signal when junior answers are vague or nervous.
display_name_zh: 初级回答恢复提示
display_description_zh: 初级候选人回答发散或紧张时，用有边界的提示恢复信号。
type: strategy
dimensions: [communication, technical_depth, problem_solving, coding_quality]
job_levels: [junior, mid]
memory_key: seed:junior_mid:recovery_hint
---

When a junior candidate gives a vague answer, the first failure may be calibration
rather than lack of knowledge. Use one bounded hint before escalating difficulty.

How to apply:
- Restate the expected answer shape in one sentence.
- Give one concrete anchor such as a queue, cache key, table, API boundary, or error log.
- Ask the candidate to explain the next two steps in their own words.
- If the hint works, continue with a small follow-up; if not, switch to a simpler evidence question.

Pitfalls:
- Do not stack multiple hints that effectively answer the question.
- Do not treat the recovered answer as equivalent to an unaided strong answer.
