---
name: Closed Loop Learning
description: Use when the question is how execution results should be turned into reusable knowledge that affects future runs.
type: reference
---

Retrieval question: How should execution results be turned into reusable knowledge that affects future runs?

## Summary
- Hermes is the main reference for runtime learning.
- Its loop is about experience capture, not online model training.
- ACO adds a business-side learning loop through `trace -> outcome -> delayed reward`.
- Claude Code contributes the editable long-term memory pattern that makes reuse stable.

## Reusable Patterns
- Separate skill, memory, and outcome artifacts by role.
- Support both active save paths and review save paths.
- Keep learned artifacts human-readable and patchable.
- Keep delayed reward outside the main generation path.

## When To Load
- Load this card for questions about post-execution learning and knowledge reuse.
- Switch to `memory-and-retrieval` if the real question is the static KB shape.
- Switch to `workflow-orchestration` if the real question is the business loop itself.

## Source Map
- [Hermes Closed Loop Learning Analysis](../hermes-agent/hermes-closed-loop-learning-analysis.md) - Active save path, review path, and skill maintenance loop.
- [ACO LangGraph Workflow Business Loop](../Agentic-Content-Optimizer/LANGGRAPH_WORKFLOW_BUSINESS_LOOP.md) - Trace, outcome, and delayed reward loop.
- [Claude Code Memory System](../claude-code/memory-system.md) - Editable long-term memory that can be recalled later.
