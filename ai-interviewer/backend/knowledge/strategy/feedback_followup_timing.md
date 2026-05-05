---
name: Follow-up Timing
description: When to deepen vs switch dimensions based on answer quality signals
type: strategy
dimensions: [technical_depth, problem_solving, system_design, communication]
job_levels: [junior, mid, senior, staff, principal]
---

The timing of follow-up actions significantly affects interview efficiency.
Spending too long on a single dimension wastes turn budget; switching too
quickly misses depth signals.

Why:
Thompson Sampling picks the statistically best action, but contextual timing
(e.g. "the candidate just gave a strong answer") is semantic information the
bandit cannot capture in its Beta posteriors alone.

How to apply:
- Score >= 8.0 on first attempt: consider `switch_dimension` — diminishing returns
  from further probing on an already-strong dimension.
- Score 5.0–7.9: ideal range for `deepen_technical` — the candidate showed partial
  knowledge worth exploring.
- Score < 5.0 on first attempt: try `give_hint` once. If score stays low, `skip_to_next`.
- If turn_budget_remaining <= 2 and unvisited dimensions remain: always prefer
  `switch_dimension` to maximize coverage.

Pitfalls:
- Do not let a single strong answer skip the entire dimension if the rubric
  has multiple facets.
- Budget-aware switching should not override a refine lock set by the evaluator.
