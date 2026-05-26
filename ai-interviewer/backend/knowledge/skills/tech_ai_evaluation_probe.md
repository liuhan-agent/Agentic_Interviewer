---
id: tech_ai_evaluation_probe
name: AI Evaluation Probe
description: Keep AI-system answers grounded in eval data, failure slices, feedback loops, and product risk.
display_name_zh: AI 评估追问卡
display_description_zh: 引导 AI 系统回答锚定评估数据、失败切片、反馈闭环和产品风险。
status: active
priority: 8
direction_tags: [internet_tech]
role_tags: [ai_agent, ai_fullstack, ai_algorithm, architect]
dimensions: [technical_depth, problem_solving, product_thinking, project_experience]
job_levels: [junior, mid, senior, staff, principal]
probe_intents: [evaluation_probe, metric_probe, failure_analysis_probe]
failure_categories: [weak_attribution, missing_evidence, shallow_analysis]
generator_moves:
  - "Ask what dataset, prompt set, or traffic slice represented quality."
  - "Probe the metric, human review rule, and failure category that drove iteration."
  - "Ask how offline evaluation connected to online user or business feedback."
watch_for:
  - "Separates model capability, product UX, retrieval quality, tool reliability, and safety risk."
  - "Names a failure slice rather than only aggregate score."
avoid:
  - "Accepting 'we tested with users' without sample, metric, or failure taxonomy."
  - "Letting model benchmark claims replace task-specific evaluation."
evaluator_rubric_hints:
  - "Credit task-specific eval set, failure taxonomy, metric definition, and online feedback loop."
positive_signals:
  - "Mentions golden set, adjudication, slice analysis, regression gate, or human-in-the-loop review."
negative_signals:
  - "Cannot explain what a bad answer looks like for the product use case."
score_bias_rules:
  - "Soft positive when the candidate shows how eval findings changed prompt, retrieval, tool, or UX design."
evaluator_visibility: true
---

Use when the scenario involves LLM apps, RAG, agents, model evaluation,
recommendations, ML delivery, or AI product quality.

- Ask what quality means for the task.
- Require a failure taxonomy or slice.
- Tie offline eval to online behavior or business risk.
