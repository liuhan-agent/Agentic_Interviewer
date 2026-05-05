---
name: Topic Name
description: Say in one sentence when this card should be loaded.
type: reference
---

Retrieval question: What is the one question this card answers?

## Summary
- Write the shortest useful answer first.
- Focus on patterns, boundaries, and tradeoffs.

## Reusable Patterns
- Extract only the parts that can transfer into another system.
- Call out what belongs in the substrate versus the vertical workflow.

## When To Load
- State when this card is the right entrypoint.
- Typical questions should need only 1-3 cards.
- If this card starts answering multiple retrieval questions, split it.
- Parent pages define scope and route to child pages.
- Child pages hold the detailed pattern extraction and source map.
- First split candidates for broad pages are `agent-loop-runtime`, `session-state`, and `gateway-control-plane`.

## Source Map
- [Raw doc A](../path/to/raw-doc.md) - What to read there.
- [Raw doc B](../path/to/raw-doc.md) - Why this raw doc matters.

## Maintenance Check
- Does this card still answer one retrieval question?
- Can the user still reach this card from `reference/MEMORY.md` within 3 clicks?
- Should this remain a top-level card, or should it split into parent and child pages?
