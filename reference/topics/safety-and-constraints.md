---
name: Safety And Constraints
description: Use when the question is where permissions, safety checks, and automation guardrails belong in the substrate.
type: reference
---

Retrieval question: Where should permissions, safety checks, and automation guardrails live in the substrate?

## Summary
- Safety is not just a prompt instruction.
- It is a layered runtime chain.
- Claude Code is the strongest reference for permission decisions, bypass-immune paths, auto-mode restrictions, and sandbox mapping.
- OpenClaw is the strongest reference for config, secret, and auth surfaces as runtime prerequisites.
- ACO is the reminder that business workflow nodes should not own substrate safety policy.

## Reusable Patterns
- Build defense in depth across prompt, runtime, tool, and sandbox layers.
- Keep some high-risk paths immune to bypass.
- Tighten safety as automation increases.
- Separate config, secret references, and runtime snapshots.
- Keep concurrency and side-effect protection in the substrate.

## When To Load
- Load this card for permission-chain and guardrail questions.
- Switch to `control-plane-and-runtime-boundaries` if the real question is gateway or session duties.
- Switch to `workflow-orchestration` if the real question is a business quality gate.

## Source Map
- [Claude Code Safety And Constraints](../claude-code/safety-and-constraints.md) - Permission chain, bypass-immune checks, auto mode, and sandbox adapter.
- [OpenClaw Phase 6](../open-claw/phase6_%20%E9%85%8D%E7%BD%AE%E4%B8%8E%E5%AF%86%E9%92%A5%E4%BD%93%E7%B3%BB.md) - Config layers, secret refs, runtime snapshots, and auth surfaces.
- [OpenClaw Phase 2](../open-claw/phase2_%20Gateway%20%E4%B8%8E%E6%8E%A7%E5%88%B6%E5%B9%B3%E9%9D%A2.md) - Entry, auth, and dispatch duties in the control plane.
- [ACO Three Loop Boundaries](../Agentic-Content-Optimizer/%E6%B7%B7%E5%90%88%E6%9E%B6%E6%9E%84%E4%B8%AD%E7%9A%84%E5%BA%95%E5%BA%A7%E4%B8%8E%E4%B8%89%E5%B1%82Loop%E8%BE%B9%E7%95%8C.md) - Why substrate safety should stay out of business-loop nodes.
