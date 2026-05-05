---
name: Control Plane And Runtime Boundaries
description: Use when the question is how to split control plane, agent runtime, session/state, and vertical workflow responsibilities.
type: reference
---

Retrieval question: How should control plane, agent runtime, session/state, and vertical workflow responsibilities be split?

## Summary
- This is a parent topic page.
- Gateway/control plane, runtime, session subsystem, and business workflow are not the same layer.
- OpenClaw is the main reference for control-plane and session boundaries.
- Claude Code is the main reference for main-loop and runtime boundaries.
- ACO provides the cleanest `tool loop / workflow loop / node-local loop` mental model.

## Reusable Patterns
- Treat the control plane as access, auth, dispatch, and broadcast infrastructure.
- Treat session as a state and routing anchor, not as the prompt itself.
- Treat context management as a policy slot, not as transcript storage.
- Treat vertical workflow as a business layer above the substrate.
- Split broad follow-up questions into `gateway-control-plane`, `session-state`, and `agent-loop-runtime`.

## When To Load
- Load this card when the core issue is responsibility boundaries.
- Split or switch to `session-state` if the discussion becomes mostly about session persistence and transcript structure.
- Split or switch to `agent-loop-runtime` if the discussion becomes mostly about main-loop execution detail.

## Source Map
- [OpenClaw Phase 2](../open-claw/phase2_%20Gateway%20%E4%B8%8E%E6%8E%A7%E5%88%B6%E5%B9%B3%E9%9D%A2.md) - Gateway as control plane and dispatch center.
- [OpenClaw Phase 3](../open-claw/phase3_%20Agent%20%E8%BF%90%E8%A1%8C%E6%97%B6%E4%B8%8E%E4%BC%9A%E8%AF%9D%E7%BC%96%E6%8E%92.md) - Runtime assembly, tools, skills, and embedded agent flow.
- [OpenClaw Phase 7](../open-claw/phase7_%20Session%20%E4%B8%8E%E7%8A%B6%E6%80%81%E7%AE%A1%E7%90%86.md) - Session, SessionEntry, Transcript, and active working set.
- [OpenClaw Phase 9](../open-claw/phase9_%20Context%20Engine.md) - Context management as a separate lifecycle surface.
- [Claude Code Agent Loop](../claude-code/agent-loop.md) - Main loop boundaries.
- [ACO Three Loop Boundaries](../Agentic-Content-Optimizer/%E6%B7%B7%E5%90%88%E6%9E%B6%E6%9E%84%E4%B8%AD%E7%9A%84%E5%BA%95%E5%BA%A7%E4%B8%8E%E4%B8%89%E5%B1%82Loop%E8%BE%B9%E7%95%8C.md) - Tool loop, workflow loop, and node-local loop.
