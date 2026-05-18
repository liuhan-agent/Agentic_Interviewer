---
id: universal_concrete_evidence_probe
name: Concrete Evidence Probe
description: Push any answer from opinion into a real example, decision, and result.
status: active
priority: 5
probe_intents: [evidence_probe, case_study_probe, reference_check_probe]
failure_categories: [missing_evidence, generic_storytelling, vague_process]
generator_moves:
  - "Ask for one named project, customer, launch, incident, or decision."
  - "Require before state, personal action, and observable after state."
watch_for:
  - "Separates personal ownership from team context."
avoid:
  - "Accepting principles, slogans, or borrowed team stories as evidence."
evaluator_rubric_hints:
  - "Credit concrete example, candidate action, and observable result."
positive_signals:
  - "Names time window, artifact, stakeholder, or measured outcome."
negative_signals:
  - "Cannot say what they personally did."
score_bias_rules:
  - "Soft negative when an answer remains generic after an evidence probe."
evaluator_visibility: true
---

Use when the candidate answers with principles, slogans, or generic best
practice.

- Ask for one named project, customer, launch, incident, or decision.
- Require the before state, the candidate's action, and the observable after
  state.
- If they keep speaking generally, narrow the next probe to "what did you
  personally do in that week?" or "what changed after your decision?".
- Watch for borrowed team stories: strong answers can separate personal
  ownership from team context.
