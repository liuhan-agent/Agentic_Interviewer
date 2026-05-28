---
name: Junior System Design Component Trace
description: Evaluate junior system design by tracing one component interaction instead of asking for a full architecture.
display_name_zh: 初级系统设计组件链路
display_description_zh: 用单个组件交互链路评估初级候选人的系统设计基础。
type: strategy
dimensions: [system_design, technical_depth, project_experience]
job_levels: [junior, mid]
memory_key: seed:junior_mid:system_design_component_trace
---

Junior system design questions should start with one understandable component
interaction before expanding to full architecture.

How to apply:
- Ask the candidate to trace one request, message, or scheduled job through the system.
- Require one storage choice and one boundary between components.
- Ask what happens when that boundary fails or slows down.
- If the trace is solid, ask how they would scale or simplify only that part.

Pitfalls:
- Do not ask for complete large-scale architecture first.
- Avoid senior-level trade-off pressure until the candidate has described the basic flow.
