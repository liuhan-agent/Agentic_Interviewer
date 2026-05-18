---
id: universal_metric_baseline_probe
name: Metric And Baseline Probe
description: Require baseline, metric movement, and attribution instead of vague improvement claims.
status: active
priority: 5
dimensions: [metrics_thinking, data_analysis, product_thinking, problem_solving, project_experience]
probe_intents: [metric_probe, experiment_probe]
failure_categories: [missing_evidence, weak_attribution, vague_goal]
generator_moves:
  - "Ask for baseline number, target number, and measurement window."
  - "Probe what else changed and how the candidate separated signal from noise."
watch_for:
  - "Defines metric, baseline, attribution risk, and decision use."
avoid:
  - "Accepting 'improved a lot' without units, time window, or counterfactual."
evaluator_rubric_hints:
  - "Credit measurable baseline and an attribution explanation."
positive_signals:
  - "Pairs outcome metric with process, system, user, or revenue metric."
negative_signals:
  - "Uses a metric name without definition or source."
score_bias_rules:
  - "Soft positive when the answer includes a competing explanation for the metric movement."
evaluator_visibility: true
---

Use when the candidate claims improvement, optimization, growth, quality, or
efficiency.

- Ask for the baseline number, the target number, and the measurement window.
- Ask what else changed at the same time and how they separated signal from
  noise.
- For business roles, insist on one user or revenue metric and one process
  metric.
- For technical roles, insist on one system or delivery metric and the
  measurement method.
