---
name: Coding Quality Review Signal Probe
description: Use code review behavior to surface maintainability, collaboration, and judgment.
display_name_zh: 代码评审信号追问
display_description_zh: 通过代码评审行为观察可维护性、协作和判断力。
type: strategy
dimensions: [coding_quality, communication, project_experience]
job_levels: [junior, mid, senior, staff, principal]
memory_key: seed:all_levels:coding_review_signal
---

Code review stories expose maintainability and communication signals that pure
implementation questions can miss.

How to apply:
- Ask for a review comment they gave or received that changed the implementation.
- Require the underlying risk: correctness, performance, security, readability, or ownership.
- For senior candidates, ask how they made the pattern repeatable for the team.
- For junior candidates, ask what they learned and how they applied it later.

Pitfalls:
- Do not reward "I am strict in reviews" without an example.
- Avoid turning this into a personality question; keep it tied to code behavior.
