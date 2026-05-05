---
name: OpenClaw
description: Best for platform runtime structure: gateway/control plane, session-first orchestration, plugin system, and context engine slots.
type: reference
---

## Project Focus
Use this project when the question is about a platform-grade agent runtime. OpenClaw is the best reference here for control plane boundaries, session/state architecture, plugin-driven extensibility, and pluggable context management.

## Read Order
1. [Overall Architecture](../open-claw/openclaw-overall-architecture.md)
2. [Phase 2 Gateway And Control Plane](../open-claw/phase2_%20Gateway%20%E4%B8%8E%E6%8E%A7%E5%88%B6%E5%B9%B3%E9%9D%A2.md)
3. [Phase 3 Agent Runtime And Session Orchestration](../open-claw/phase3_%20Agent%20%E8%BF%90%E8%A1%8C%E6%97%B6%E4%B8%8E%E4%BC%9A%E8%AF%9D%E7%BC%96%E6%8E%92.md)
4. [Phase 4 Plugins Skills And Tool Extension](../open-claw/phase4_%20Plugins%E3%80%81Skills%20%E4%B8%8E%E5%B7%A5%E5%85%B7%E6%89%A9%E5%B1%95%E6%9C%BA%E5%88%B6.md)
5. [Phase 7 Session And State Management](../open-claw/phase7_%20Session%20%E4%B8%8E%E7%8A%B6%E6%80%81%E7%AE%A1%E7%90%86.md)
6. [Phase 8 Memory Architecture](../open-claw/phase8_%20%E8%AE%B0%E5%BF%86%E3%80%81%E5%A4%9A%E6%A8%A1%E6%80%81%E4%B8%8E%E8%83%BD%E5%8A%9B%E6%9C%8D%E5%8A%A1.md)
7. [Phase 9 Context Engine](../open-claw/phase9_%20Context%20Engine.md)
8. [Phase 6 Config And Secrets](../open-claw/phase6_%20%E9%85%8D%E7%BD%AE%E4%B8%8E%E5%AF%86%E9%92%A5%E4%BD%93%E7%B3%BB.md)

## Best Topic Matches
- `control-plane-and-runtime-boundaries` - Gateway, runtime, session, and context boundaries.
- `tools-skills-and-mcp` - The clearest platform split between Plugins, Skills, Tools, and MCP.
- `memory-and-retrieval` - File-first memory plus transcript, flush, and compaction chains.
- `context-engineering` - Context management as a pluggable slot.
- `safety-and-constraints` - More about config, secret, and auth surfaces than permission chains.

## Return To Raw Docs When
- You need exact gateway duties versus downstream business modules.
- You need the exact split between Session, SessionEntry, Transcript, and `activeSession.messages`.
- You need to see how plugins register channels, providers, tools, services, or context engines.
