---
name: ai-interviewer-retrospective
description: "Use only when the user explicitly asks to review, record, capture, or organize a development/debugging retrospective for the AI interviewer project, especially logic bugs, boundary issues, LLM runaway behavior, prompt/tool failures, or debugging lessons. Do not use for ordinary implementation, general debugging, production runtime behavior, automatic learning, or automatic changes to prompts, state-machine guards, eval cases, other skills, memory, runtime knowledge, or documents outside docs/learning-cases."
---

# AI Interviewer Retrospective

## Purpose

Capture a visible, human-reviewable Markdown retrospective for AI interviewer development and debugging issues.

This skill records and structures what happened. It does not upgrade lessons into runtime behavior, prompts, guards, evals, memory, or other skills.

## Workflow

1. Confirm the request is an explicit retrospective request.
2. Gather the smallest useful context from the user and repo.
3. If key facts are missing, ask 1-3 focused questions before drafting.
4. Draft the retrospective in Chinese by default.
5. Separate confirmed facts, inferences, and unconfirmed assumptions.
6. Propose a target path under `docs/learning-cases/`.
7. Show a concise draft summary and the target path before writing.
8. Write the Markdown file only after the user confirms.

## Information To Capture

Prefer concrete evidence over broad interpretation:

- What the user expected.
- What actually happened.
- Inputs, logs, traces, screenshots, files, prompts, or commands that reveal the issue.
- The suspected or confirmed root cause.
- The debugging path and false starts.
- The final fix or current workaround, if any.
- How the result was verified.
- What lesson is useful for future debugging.
- What remains unknown.

When evidence is thin, keep the conclusion tentative and mark missing facts clearly.

## Output File

Use this path pattern:

`docs/learning-cases/YYYY-MM-DD-kebab-title.md`

Rules:

- Use the current local date for `YYYY-MM-DD`.
- Generate a short lowercase kebab-case slug from the problem title.
- If the title is unclear, use a problem-type slug such as `llm-followup-runaway`, `boundary-state-bug`, or `evaluation-drift`.
- If the target file already exists, append `-2`, then `-3`, and so on.
- Never overwrite an existing case.
- Do not create an index, tag database, or summary rollup in v1.

## Draft Before Writing

Before creating the file, show:

- Proposed file path.
- One-sentence conclusion.
- Key root-cause hypothesis.
- Open questions or missing evidence.

Then ask for confirmation. Do not write the file until the user explicitly approves.

## Boundaries

Do not:

- Modify AI interviewer prompts.
- Modify state-machine guards or workflow logic.
- Add or update eval cases.
- Update runtime knowledge under `ai-interviewer/backend/knowledge/`.
- Update other skills.
- Create automated review, learning, promotion, or background jobs.
- Treat one incident as a durable project rule unless the user separately asks for that work.

## Template

Load `references/case-template.md` when drafting a case.
