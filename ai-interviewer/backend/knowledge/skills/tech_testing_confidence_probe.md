---
id: tech_testing_confidence_probe
name: Testing Confidence Probe
description: Turn testing answers into risk coverage, failure examples, and release confidence.
display_name_zh: 测试信心追问卡
display_description_zh: 引导测试回答落到风险覆盖、失败样例和发布信心依据。
status: active
priority: 7
direction_tags: [internet_tech]
role_tags: [java_backend, frontend_web, sre, ai_fullstack, ai_agent, mobile, ai_algorithm, architect]
dimensions: [coding_quality, project_experience, problem_solving]
job_levels: [junior, mid, senior, staff, principal]
probe_intents: [evidence_probe, tradeoff_probe, rollout_probe]
failure_categories: [missing_evidence, vague_process, weak_risk_boundary]
generator_moves:
  - "Ask what defect class the test strategy was meant to catch."
  - "Probe why unit, integration, contract, e2e, canary, or manual review was the right layer."
  - "Ask what signal gave release confidence and what remained untested."
watch_for:
  - "Maps tests to concrete risks rather than listing test types."
  - "Explains residual risk and mitigation after tests pass."
avoid:
  - "Accepting high coverage numbers without defect class or confidence boundary."
  - "Letting the answer ignore flaky tests, test data, or environment mismatch."
evaluator_rubric_hints:
  - "Credit risk-based test selection, release gate, and residual-risk acknowledgement."
positive_signals:
  - "Names a regression that would have escaped without a specific test."
negative_signals:
  - "Treats test count or coverage percentage as the whole quality argument."
score_bias_rules:
  - "Soft positive when the candidate explains what they intentionally did not test and why."
evaluator_visibility: true
---

Use when the topic is code quality, release confidence, QA strategy, or
regression prevention.

- Ask for the risk first, then the test layer.
- Require one failure that the strategy would catch.
- Probe what remained risky after the gate passed.
