---
name: Weak Answer Concrete Hint
description: Recover weak answers with one concrete anchor before concluding the candidate lacks the skill.
display_name_zh: 弱回答具体提示
display_description_zh: 对弱回答先给一次具体锚点提示，再判断是否确实缺口明显。
type: strategy
dimensions: [technical_depth, system_design, problem_solving, coding_quality, project_experience, communication, product_thinking]
job_levels: [junior, mid, senior, staff, principal]
memory_key: seed:all_levels:weak_answer_concrete_hint
---

Weak answers can come from missing knowledge, unclear question framing, or lack
of a concrete anchor. Use one concrete hint to disambiguate.

How to apply:
- Name the missing evidence type: metric, failure path, implementation step, or user impact.
- Provide one small anchor from the question or resume.
- Ask the candidate to continue without giving away the full solution.
- If the answer remains vague, move on and preserve the weak signal.

Pitfalls:
- Do not keep hinting until the answer becomes interviewer-authored.
- Avoid vague hints such as "be more specific"; name the missing evidence.
