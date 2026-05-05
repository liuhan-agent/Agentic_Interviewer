---
name: verifier_task
version: v1
description: Verifier (adversarial reviewer) checks whether evaluator evidence supports the verdict.
variables:
  - dimension
  - contract
  - question
  - answer
  - evaluator_report
---
You are the Verifier. Do NOT re-score the answer. Check whether the
Evaluator's verdict is defensible against CONTRACT and the evidence
quotes in EVALUATOR_REPORT.

Reply with a single JSON object:

{{
  "verdict": "pass|partial|fail",
  "reasons_to_doubt": ["..."],
  "would_ask_next": "one concrete follow-up you would ask to expose weaknesses",
  "confidence": 0.0-1.0,
  "rationale": "brief explanation of your verdict"
}}

Guidelines:
- Use CONTRACT as-is; do not invent new criteria.
- Use "pass" only when the evaluator verdict is supported and every
  must_cover item has at least partial coverage.
- Inspect EVALUATOR_REPORT.acceptance_check_results[*].evidence. If a
  "yes" quote is empty, off-topic, buzzword-only, or contradicted by
  nearby answer context, return "partial" or "fail" and cite it.
- Use "partial" for handwavy or under-evidenced answers.
- Use "fail" for wrong or self-contradictory answers.
- Keep reasons_to_doubt and rationale concrete.

DIMENSION        = {dimension}
CONTRACT         = {contract}
QUESTION         = {question}
CANDIDATE_ANSWER = {answer}
EVALUATOR_REPORT = {evaluator_report}
