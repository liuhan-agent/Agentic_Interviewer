---
name: Tools Skills And Mcp
description: Use when the question is how to separate Tools, Skills, MCP, and Plugins without collapsing them into one layer.
type: reference
---

Retrieval question: How should Tools, Skills, MCP, and Plugins be separated without collapsing them into one layer?

## Summary
- The stable split is simple.
- Tool means execution interface.
- Skill means reusable know-how.
- MCP means external tool-service access.
- Plugin means install, discovery, and registration packaging.
- Claude Code is best for the unified capability plane.
- OpenClaw is best for platform extension boundaries.
- Hermes is best for skill maintenance as procedural memory.

## Reusable Patterns
- Give all executable abilities one runtime-facing tool protocol.
- Keep skill metadata lean and load the body on demand.
- Use plugin systems to package and register capability sources, not to redefine every concept.
- Give skill maintenance actions explicit boundaries, like Hermes does.

## When To Load
- Load this card for capability-surface questions and skill design questions.
- Switch to `memory-and-retrieval` if the real issue is KB structure.
- Switch to `control-plane-and-runtime-boundaries` if the real issue is runtime responsibility.

## Source Map
- [Claude Code Tools Skills MCP](../claude-code/tools-skills-mcp.md) - Unified capability plane and tool protocol.
- [OpenClaw Phase 4](../open-claw/phase4_%20Plugins%E3%80%81Skills%20%E4%B8%8E%E5%B7%A5%E5%85%B7%E6%89%A9%E5%B1%95%E6%9C%BA%E5%88%B6.md) - Plugin, Skill, Tool, and MCP boundaries.
- [Hermes Closed Loop Learning Analysis](../hermes-agent/hermes-closed-loop-learning-analysis.md) - `skill_manage`, `skills_list`, and `skill_view`.
