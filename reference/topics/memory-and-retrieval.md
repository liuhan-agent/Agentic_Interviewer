---
name: Memory And Retrieval
description: Use when the question is how long-term memory, retrieval, transcript history, and working memory should cooperate.
type: reference
---

Retrieval question: How should long-term memory, retrieval, transcript history, and working memory cooperate?

## Summary
- The most stable pattern is file-first long-term knowledge plus selective retrieval.
- Claude Code uses `MEMORY.md + topic files + relevant memory recall`.
- Hermes splits knowledge into procedural, declarative, and episodic layers.
- OpenClaw keeps transcript, memory flush, and compaction summary as parallel chains.
- A good memory system answers what to keep, what to recall, and what to compact away.

## Reusable Patterns
- Keep long-term knowledge human-readable.
- Separate procedural knowledge from declarative facts and episodic history.
- Treat transcript and compaction summary as session-side material, not the whole knowledge base.
- Retrieve the smallest relevant unit instead of loading full documents.

## When To Load
- Load this card for KB shape, recall policy, and `MEMORY.md` design questions.
- Switch to `tools-skills-and-mcp` if the real question is skill discovery and maintenance.
- Switch to `closed-loop-learning` if the real question is how execution updates knowledge.

## Source Map
- [Claude Code Memory System](../claude-code/memory-system.md) - `MEMORY.md`, topic files, relevant recall, and scope memory.
- [Hermes Closed Loop Learning Analysis](../hermes-agent/hermes-closed-loop-learning-analysis.md) - Procedural, declarative, and episodic knowledge layers.
- [OpenClaw Phase 8](../open-claw/phase8_%20%E8%AE%B0%E5%BF%86%E3%80%81%E5%A4%9A%E6%A8%A1%E6%80%81%E4%B8%8E%E8%83%BD%E5%8A%9B%E6%9C%8D%E5%8A%A1.md) - File-first memory and tool-first recall.
- [OpenClaw Phase 7](../open-claw/phase7_%20Session%20%E4%B8%8E%E7%8A%B6%E6%80%81%E7%AE%A1%E7%90%86.md) - Transcript, SessionEntry, and active working set boundaries.
