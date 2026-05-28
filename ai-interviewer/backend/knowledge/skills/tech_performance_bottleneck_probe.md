---
id: tech_performance_bottleneck_probe
name: Performance Bottleneck Probe
description: Push performance answers toward baseline, bottleneck evidence, and tradeoff-aware optimization.
display_name_zh: 性能瓶颈追问卡
display_description_zh: 引导性能回答覆盖基线、瓶颈证据和带有取舍意识的优化方案。
status: active
priority: 8
direction_tags: [internet_tech]
role_tags: [java_backend, frontend_web, sre, ai_fullstack, ai_agent, mobile, ai_algorithm, architect]
dimensions: [technical_depth, system_design, problem_solving]
job_levels: [junior, mid, senior, staff, principal]
probe_intents: [performance_probe, tradeoff_probe, evidence_probe]
failure_categories: [missing_scale_reasoning, shallow_analysis, weak_attribution]
generator_moves:
  - "Ask for baseline, target, measurement window, and p95 or p99 impact."
  - "Probe the bottleneck evidence: CPU, IO, network, lock, memory, rendering, model latency, or queueing."
  - "Ask what tradeoff the optimization introduced."
watch_for:
  - "Uses measurement before optimization and explains why the bottleneck was binding."
  - "Connects local improvement to user-visible or system-level impact."
avoid:
  - "Accepting generic cache/index/async answers without measured bottleneck evidence."
  - "Letting averages replace tail latency or worst-case experience when the scenario needs it."
evaluator_rubric_hints:
  - "Credit baseline, bottleneck isolation, before-after measurement, and explicit tradeoff."
positive_signals:
  - "Mentions profiler, trace, query plan, flame graph, RUM, load test, or model benchmark."
negative_signals:
  - "Optimizes a component without showing it was on the critical path."
score_bias_rules:
  - "Soft negative when the answer cannot connect optimization to a user or reliability outcome."
evaluator_visibility: true
---

Use when the candidate discusses latency, throughput, resource use, rendering,
model serving, or capacity.

- Require a baseline and the observation method.
- Ask what broke after the optimization or what cost increased.
- Keep the answer tied to the critical path.
