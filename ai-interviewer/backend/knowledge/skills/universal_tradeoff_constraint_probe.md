---
id: universal_tradeoff_constraint_probe
name: Tradeoff Constraint Probe
description: Make the candidate name constraints, rejected options, and the cost of the chosen path.
display_name_zh: 取舍与约束追问卡
display_description_zh: 引导候选人说明约束条件、被放弃的选项，以及选择当前路径的代价。
status: active
priority: 4
probe_intents: [tradeoff_probe, prioritization_probe, stakeholder_pushback_probe]
failure_categories: [missing_tradeoff, weak_prioritization, vague_goal]
generator_moves:
  - "Ask which options were rejected and why."
  - "Probe the constraint that mattered most and the risk they knowingly accepted."
watch_for:
  - "Names cost of the chosen path, not only benefits."
avoid:
  - "Accepting an answer where the best option sounds obvious and cost-free."
evaluator_rubric_hints:
  - "Credit explicit rejected option, constraint, accepted risk, and monitoring plan."
positive_signals:
  - "States a real tradeoff across time, cost, reliability, user impact, compliance, or staffing."
negative_signals:
  - "Lists pros without saying what was sacrificed."
score_bias_rules:
  - "Soft positive when the accepted risk has an owner and check-in signal."
evaluator_visibility: true
---

Use when the answer sounds like there was an obvious best option.

- Ask which options were rejected and why.
- Ask what constraint mattered most: time, cost, reliability, user impact,
  compliance, staffing, or stakeholder pressure.
- Ask what risk they knowingly accepted and how they monitored it.
- Strong answers should include the cost of the chosen plan, not only its
  benefits.
