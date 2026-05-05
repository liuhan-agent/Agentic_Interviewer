# Repository Guidelines

## Reference KB
- Start with `reference/MEMORY.md`. It is the only root entrypoint into the curated knowledge base.
- Use this KB for repo-scoped pattern borrowing, reading paths, and cross-project comparisons across Claude Code, Hermes Agent, OpenClaw, and Agentic-Content-Optimizer.
- Concept, comparison, and pattern questions inside this repo scope should enter through `reference/topics/*`.
- Project trace, source provenance, and "how does project X do it" questions inside this repo scope should enter through `reference/projects/*`.
- Do not use this KB as the primary source for official definitions, latest viewpoints, or explicit web-search questions; prefer official or web sources first and only compare back to the repo when needed.
- The expected output from this knowledge layer is `navigation + pattern extraction + source map`, not a direct business solution.

## Skills
- `agentic-workflow-reference`: Use when the task is repo-scoped pattern borrowing, reading-path guidance, or cross-project comparison across Claude Code, Hermes Agent, OpenClaw, and Agentic-Content-Optimizer in this repository. Do not treat it as the primary source for official or web-first questions. File: `.agents/skills/agentic-workflow-reference/SKILL.md`
