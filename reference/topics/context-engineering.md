---
name: Context Engineering
description: Use when the question is how to assemble layered context instead of treating context as one giant prompt blob.
type: reference
---

Retrieval question: How should context be layered and assembled instead of being stuffed into one prompt?

## Summary
- Context engineering is a runtime assembly problem, not a wording problem.
- Claude Code shows the clearest split between static system context, dynamic system context, and message-side runtime facts.
- OpenClaw turns context management into a pluggable slot.
- Hermes shows that skills guidance and skills index also belong to the context layer.
- Progressive disclosure beats preload-everything.

## Reusable Patterns
- Split stable rules from dynamic turn-by-turn context.
- Treat index files and cards as a navigation layer, not as the raw knowledge itself.
- Keep context assembly as a replaceable policy surface.
- Load the minimum useful card set before loading raw docs.

## When To Load
- Load this card for prompt layering, memory injection timing, and context-rot questions.
- Switch to `memory-and-retrieval` if the real question is about long-term memory structure.
- Switch to `workflow-orchestration` if the real question is about a business state machine.

## Source Map
- [Claude Code Context Engineering](../claude-code/context-engineering.md) - Three-layer context design and cache boundaries.
- [Claude Code Agent Loop](../claude-code/agent-loop.md) - Where context gets recomputed and rewritten in the main loop.
- [Claude Code Memory System](../claude-code/memory-system.md) - How relevant memories and attachments enter a turn.
- [OpenClaw Phase 9](../open-claw/phase9_%20Context%20Engine.md) - Context management as a pluggable strategy slot.
- [Hermes Closed Loop Learning Analysis](../hermes-agent/hermes-closed-loop-learning-analysis.md) - Skills guidance and on-demand skill loading in the active context.
