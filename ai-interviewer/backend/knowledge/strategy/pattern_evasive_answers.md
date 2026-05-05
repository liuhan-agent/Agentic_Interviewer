---
name: Evasive Answer Patterns
description: How to handle candidates who give vague or rehearsed answers
type: strategy
dimensions: [technical_depth, problem_solving, communication]
job_levels: [junior, mid, senior]
---

Some candidates respond with overly general or rehearsed answers that lack specifics.
These answers score low on depth but may mask genuine knowledge behind poor communication.

Why:
Vague answers are ambiguous signals. A candidate might genuinely lack depth, or they might
be nervous, unsure what level of detail is expected, or defaulting to interview-prep scripts.
The interviewer must disambiguate before scoring.

How to apply:
- When an answer lacks specifics, use `give_hint` with a concrete anchor:
  "Could you walk through a specific project where you applied this?"
- If the hint produces a detailed response, raise the score and note the candidate
  may need calibration time.
- If two consecutive hints fail to elicit specifics, the answer likely reflects
  genuine depth gaps — move on with `skip_to_next`.
- Never use `deepen_technical` on a vague answer without first trying `give_hint`.

Pitfalls:
- Do not assume evasion is intentional; cultural and linguistic factors matter.
- Avoid stacking more than two hint rounds on the same question.
