---
name: Workflow Orchestration
description: Use when the question is how to structure a multi-step business workflow with shared state, quality gates, and refinement loops.
type: reference
---

Retrieval question: How should a multi-step business workflow be structured as a state machine with quality gates and refinement loops?

## Summary
- This is a parent topic page.
- ACO is the primary reference for business workflow orchestration.
- `workflow loop`, `tool loop`, and `node-local loop` are different layers.
- The API layer should translate requests into workflow inputs, not perform the workflow itself.
- Platform runtimes like Claude Code and OpenClaw provide substrate support, but the business loop lives above that substrate.

## Reusable Patterns
- Drive the workflow around one explicit shared state object.
- Make routes, node order, and exit conditions reviewable.
- Put `quality threshold`, `max iterations`, and mode switches in the workflow shell.
- Keep `trace -> outcome -> reward` as a side-channel rather than mixing it into the generation path.

## When To Load
- Load this card for business-loop design questions.
- Switch to `control-plane-and-runtime-boundaries` if the real question is about runtime or gateway layers.
- If runtime main-loop detail starts to dominate, split out `agent-loop-runtime`.

## Source Map
- [ACO LangGraph Workflow Business Loop](../Agentic-Content-Optimizer/LANGGRAPH_WORKFLOW_BUSINESS_LOOP.md) - Main business loop, shared state, refinement, and delayed reward.
- [ACO Three Loop Boundaries](../Agentic-Content-Optimizer/%E6%B7%B7%E5%90%88%E6%9E%B6%E6%9E%84%E4%B8%AD%E7%9A%84%E5%BA%95%E5%BA%A7%E4%B8%8E%E4%B8%89%E5%B1%82Loop%E8%BE%B9%E7%95%8C.md) - The split between tool, workflow, and node-local loops.
- [OpenClaw Phase 3](../open-claw/phase3_%20Agent%20%E8%BF%90%E8%A1%8C%E6%97%B6%E4%B8%8E%E4%BC%9A%E8%AF%9D%E7%BC%96%E6%8E%92.md) - Useful contrast with runtime orchestration.
- [Claude Code Agent Loop](../claude-code/agent-loop.md) - Useful contrast with a main runtime loop.
