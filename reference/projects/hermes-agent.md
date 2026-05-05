---
name: Hermes Agent
description: Best for understanding closed-loop learning, skill maintenance, and how runtime experience becomes reusable knowledge.
type: reference
---

## Project Focus
Use this project when the question is about how a runtime should learn from execution. Hermes is the strongest reference here for skill creation, review, patching, and experience replay.

## Read Order
1. [Hermes Closed Loop Learning Analysis](../hermes-agent/hermes-closed-loop-learning-analysis.md)

## Best Topic Matches
- `closed-loop-learning` - The main reference for active save paths and background review paths.
- `memory-and-retrieval` - Procedural, declarative, and episodic knowledge layers.
- `tools-skills-and-mcp` - `skill_manage`, `skills_list`, and `skill_view` as a procedural knowledge surface.
- `multi-agent-and-delegation` - The review-agent pattern for post-task learning.

## Return To Raw Docs When
- You need the exact trigger path for active skill save versus review save.
- You need the action boundaries for `create`, `patch`, `edit`, `delete`, `write_file`, or `remove_file`.
- You need to see how skills guidance, memory guidance, and session search affect the main loop.
