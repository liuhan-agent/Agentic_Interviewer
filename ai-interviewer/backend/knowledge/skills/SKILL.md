# Interview Skills

Hand-authored business know-how for the Generator (and, in future,
Evaluator / Coach) agents. Each card captures a reusable interview
skill — a probe strategy, a rubric bias, or a candidate-profile tell
— so the agents do not have to re-derive it on every session.

Skills are sibling to `knowledge/strategy/`:

- **skills/** — hand-authored, static know-how, curated by humans.
- **strategy/** — reward-driven memory maintained autonomously by the
  `strategy_dream` agent.

Both layers use the same frontmatter shape and both get read by the
runtime via `app.memory.skill_store` / `app.memory.strategy_store`.
They appear in the Generator's prompt as two independent blocks
(`{skills}` and `{strategy}`) so the Generator can distinguish
"explicit human playbook" from "learned statistical preference".

## Available Skills

- [Senior Backend Ownership Probe](senior_backend_ownership_probe.md) —
  push for outcomes, ownership artefacts, and quantified impact
  rather than accepting buzzword-heavy storytelling.
- [System Design Scale Reasoning](system_design_scale_reasoning.md) —
  force at least one concrete failure mode and one quantified scale
  argument in every system-design answer.
