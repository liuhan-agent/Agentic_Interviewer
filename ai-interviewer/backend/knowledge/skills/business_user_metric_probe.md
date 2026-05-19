---
id: business_user_metric_probe
name: Business User Metric Probe
description: Tie business answers to user segment, behavior change, metric definition, and attribution.
status: active
priority: 7
direction_tags: [business]
role_tags: [product_manager, operations, marketing_brand]
dimensions: [user_insight, metrics_thinking, user_growth, data_analysis, market_insight, campaign_execution]
job_levels: [junior, mid, senior]
probe_intents: [metric_probe, experiment_probe, prioritization_probe]
failure_categories: [vague_user, weak_attribution, missing_evidence]
generator_moves:
  - "Ask for the user segment, expected behavior change, and metric definition."
  - "Probe one competing explanation that could distort the metric."
watch_for:
  - "Connects user evidence, action, metric movement, and next iteration."
avoid:
  - "Accepting vanity metrics without baseline, attribution, or user behavior."
evaluator_rubric_hints:
  - "Credit answers that define the metric and explain why it is a useful proxy."
positive_signals:
  - "Uses both behavior evidence and business metric evidence."
negative_signals:
  - "Claims growth without explaining baseline or measurement window."
score_bias_rules:
  - "Soft negative when the answer cannot separate signal from campaign or seasonality noise."
evaluator_visibility: true
---

Use when product, operation, or marketing answers talk about users, growth, or
campaign performance.

- Ask which user segment was affected and what behavior they expected to
  change.
- Ask how the metric was defined and why it was the right proxy.
- Ask what competing explanation could make the metric look better or worse.
- Strong answers connect user evidence, action, metric, and next iteration.
