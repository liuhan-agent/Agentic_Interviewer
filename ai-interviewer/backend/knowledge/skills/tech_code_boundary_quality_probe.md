---
id: tech_code_boundary_quality_probe
name: Code Boundary Quality Probe
description: Check whether engineering quality is visible in contracts, tests, ownership boundaries, and failure handling.
display_name_zh: 代码边界质量追问卡
display_description_zh: 检查工程质量是否体现在契约、测试、责任边界和故障处理里。
status: active
priority: 6
direction_tags: [internet_tech]
role_tags: [java_backend, frontend_web, ai_fullstack, ai_agent, mobile]
dimensions: [coding_quality, technical_depth, problem_solving]
job_levels: [junior, mid, senior, staff]
probe_intents: [evidence_probe, debugging_probe, tradeoff_probe]
failure_categories: [shallow_analysis, missing_evidence, vague_process]
generator_moves:
  - "Ask which boundary the candidate owned: API, module, state, schema, test, or error path."
  - "Probe the defect class that their design or test prevented."
watch_for:
  - "Connects code structure to product, operational, or collaboration risk."
avoid:
  - "Accepting 'clean code' or framework preference without a prevented failure."
evaluator_rubric_hints:
  - "Credit concrete boundary ownership, regression risk, and verification method."
positive_signals:
  - "Explains why a boundary reduced change cost or escaped defects."
negative_signals:
  - "Describes style cleanup without test or runtime consequence."
score_bias_rules:
  - "Soft positive when the answer names the exact regression that would have escaped."
evaluator_visibility: true
---

Use when the question is about implementation quality rather than pure
architecture.

- Ask which boundary the candidate owned: API contract, module interface,
  state management, data schema, test seam, or error-handling path.
- Ask what regression would have escaped without their chosen test or
  validation.
- If the answer is only "clean code", ask for the specific defect class they
  prevented.
- Strong answers connect code structure to an operational or product risk.
