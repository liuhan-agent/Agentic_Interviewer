---
id: tech_ai_algorithm_training_probe
name: AI Algorithm Training Probe
description: Probe algorithm answers for training data lineage, label discipline, model selection rationale, and the data flywheel that improves the model over time.
status: active
priority: 8
direction_tags: [internet_tech]
role_tags: [ai_algorithm]
dimensions: [technical_depth, problem_solving, project_experience, data_analysis]
job_levels: [senior, staff, principal]
probe_intents: [evidence_probe, evaluation_probe, tradeoff_probe]
failure_categories: [weak_attribution, missing_evidence, missing_scale_reasoning]
generator_moves:
  - "Ask where the training data came from, who labelled it, the inter-annotator agreement, and which slice was held out for evaluation."
  - "Probe the model selection: which architecture was rejected, why, and what compute / latency / cost budget bounded the choice."
  - "Ask about the data flywheel: how production behaviour fed back into the next training round, and how data poisoning or distribution shift was monitored."
watch_for:
  - "Separates training loss, validation metric, online business metric, and human-review acceptance — does not collapse them."
  - "Names a failure slice that drove a specific retraining or fine-tuning decision."
avoid:
  - "Accepting 'we trained on a large dataset' without provenance, label process, or eval split definition."
  - "Letting the answer hide behind a benchmark score (MMLU, HumanEval) without task-specific evaluation."
evaluator_rubric_hints:
  - "Credit data provenance, labelling discipline, model-selection tradeoff, and a data flywheel with monitoring."
positive_signals:
  - "Mentions golden set adjudication, active learning loop, label smoothing rationale, distribution-shift alert, or compute / quality tradeoff."
negative_signals:
  - "Treats model choice as a fashion decision without naming the failure mode the architecture controls."
score_bias_rules:
  - "Soft positive when the candidate names a metric the team was tempted to optimise for and intentionally rejected."
evaluator_visibility: true
---

Use when the candidate works on training, fine-tuning, evaluation, or
deployment of ML / LLM models — especially algorithm engineers,
research engineers, or applied scientists owning a production model
lifecycle.

- Anchor every claim in **data lineage**: source, license, dedup
  policy, leakage prevention between train and eval splits. "We have
  a million examples" without provenance is treated as a marketing
  number.
- Force a **labelling discipline** answer: who labels, how disagreements
  are resolved, what inter-annotator agreement looks like, what the
  team rejected as ambiguous and why.
- Probe **model selection** as a tradeoff exercise: which architecture
  / size / training recipe was rejected, what compute / latency / cost
  budget bounded the choice, what the candidate would change if budget
  doubled or halved.
- Require a **data flywheel** loop: production behaviour → eval slice
  → retraining trigger → next release. Strong candidates can name the
  monitor that catches distribution shift before user complaints do.
- For staff+ candidates, probe organisational reality: how labelling
  ops is staffed, how legal / privacy reviews gate the pipeline, how
  research and production teams negotiate retraining cadence.
