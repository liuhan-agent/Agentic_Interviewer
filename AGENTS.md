# Repository Guidelines

## Project Scope
- Treat `ai-interviewer/` as the runnable product source: Next.js frontend, FastAPI backend, LangGraph-style workflow, account/control-plane modules, and project documentation.
- Local-only research notes, agent planning traces, demo raw files, and private reference material are intentionally ignored and should not be required to build, test, review, or understand the public project.
- Prefer tracked docs under `ai-interviewer/docs/` for architecture, runbooks, and retrospective material.

## Development Notes
- Keep product changes connected to the interview workflow and ownership/control-plane boundaries.
- Do not introduce dependencies on ignored local knowledge bases or machine-specific paths.
- When documenting design provenance, summarize the pattern in the public doc instead of linking to private workspace notes.
