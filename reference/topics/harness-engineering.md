---
name: Harness Engineering
description: Use when the question is which runtime patterns matter most for an Agentic Workflow control substrate.
type: reference
---

Retrieval question: Which runtime patterns matter most when building an Agentic Workflow control substrate?

## Summary
- Harness engineering is about the runtime around the model, not just the prompt.
- Claude Code is the strongest reference for a mature coding-agent harness.
- OpenClaw is the strongest reference for a platform runtime with gateway, session, plugins, and context slots.
- Hermes shows how learning can become a runtime capability.
- ACO is the clearest reminder that substrate loops and business workflow loops should stay separate.

## Reusable Patterns
- Separate model reasoning from runtime orchestration.
- Make the main loop explicit.
- Treat tools, skills, memory, and safety as first-class runtime surfaces.
- Keep long-term knowledge human-readable and patchable.
- Define substrate boundaries before adding a vertical workflow.

## When To Load
- Load this card for control-substrate questions.
- Switch to `Projects` if the question becomes source-trace specific.
- If this card grows too implementation-heavy, split out `agent-loop-runtime`.

## Source Map
- [Claude Code README](../claude-code/README.md) - Module map and reading order.
- [Claude Code Agent Loop](../claude-code/agent-loop.md) - Main loop, tool loop, and recovery flow.
- [Claude Code Context Engineering](../claude-code/context-engineering.md) - Layered context assembly.
- [OpenClaw Overall Architecture](../open-claw/openclaw-overall-architecture.md) - Platform runtime structure.
- [OpenClaw Phase 3](../open-claw/phase3_%20Agent%20%E8%BF%90%E8%A1%8C%E6%97%B6%E4%B8%8E%E4%BC%9A%E8%AF%9D%E7%BC%96%E6%8E%92.md) - Session-first runtime and embedded agent flow.
- [Hermes Closed Loop Learning Analysis](../hermes-agent/hermes-closed-loop-learning-analysis.md) - Learning as runtime capability.
- [ACO Three Loop Boundaries](../Agentic-Content-Optimizer/%E6%B7%B7%E5%90%88%E6%9E%B6%E6%9E%84%E4%B8%AD%E7%9A%84%E5%BA%95%E5%BA%A7%E4%B8%8E%E4%B8%89%E5%B1%82Loop%E8%BE%B9%E7%95%8C.md) - Substrate versus workflow boundaries.
