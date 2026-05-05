---
name: Multi Agent And Delegation
description: Use when the question is how a main agent, subagents, and review paths should cooperate without losing boundaries.
type: reference
---

Retrieval question: How should a main agent, subagents, and review paths cooperate without losing clear boundaries?

## Summary
- Claude Code and OpenClaw both start from one main loop, not swarm-by-default.
- Hermes shows a valuable review-agent pattern for learning after execution.
- Multi-agent value comes from clear lifecycle and context boundaries, not from agent count.

## Reusable Patterns
- Keep one main loop as the default execution form.
- Spawn subagents only for isolation, delegation, or structured review.
- Define explicit input/output contracts for subagents.
- Keep post-task review separate from the main task loop.

## When To Load
- Load this card for delegation structure and review-agent questions.
- Switch to `harness-engineering` if the issue is really the main runtime loop.
- Switch to `closed-loop-learning` if the issue is really how review updates knowledge.

## Source Map
- [Claude Code Multi-Agent Architecture](../claude-code/multi-agent-architecture.md) - Forked agent, subagent, and teammate layers.
- [Claude Code Agent Loop](../claude-code/agent-loop.md) - The main loop that delegation hangs off of.
- [OpenClaw Phase 3](../open-claw/phase3_%20Agent%20%E8%BF%90%E8%A1%8C%E6%97%B6%E4%B8%8E%E4%BC%9A%E8%AF%9D%E7%BC%96%E6%8E%92.md) - Subagent-native runtime structure.
- [Hermes Closed Loop Learning Analysis](../hermes-agent/hermes-closed-loop-learning-analysis.md) - Review-agent path for post-task learning.
