# Evaluation Baseline Hook

> Status: deferred hook. This project already has trace, replay, credibility,
> reviewed acceptance checks, and human-annotation entry points. It does not yet
> claim real-interviewer scoring accuracy because the human-labeled benchmark set
> has not been built.

## 1. Goal

This hook keeps the evaluation layer aligned with the principle:

> Do not let the model grade its own magic. Compare it against a human baseline.

For the current portfolio milestone, Agentic_Interviewer can show a structured
evaluation path, but should not advertise claims such as "99% accurate" or
"senior interviewer level" without a blind-test sample set.

## 2. Existing Project Anchors

The later baseline system should reuse these existing assets instead of creating
a separate evaluator:

- reviewed acceptance checks in the question seed YAML files: the source of
  reviewed judging clauses for each structured question variant.
- locked question contracts at runtime: the LLM can judge candidate answers, but
  cannot redefine the core criteria for the question.
- generation/evaluation traces and replay metadata: each decision should be
  explainable after the session.
- scoring credibility metrics: fallback rate, evidence quality, contract miss
  rate, and verifier pressure are computed signals, not LLM self-praise.
- trace annotations, training-set export, and outcome reward plumbing: these are
  the entry points for human labels and delayed outcome feedback.

## 3. Future Benchmark Shape

When this layer is implemented, prepare 20-50 human-reviewed samples first:

- `sample_id`
- question seed / variant id
- locked core contract and reviewed acceptance checks
- candidate resume/JD/self-introduction context digest
- answer transcript
- senior interviewer label, score band, confidence label, and notes
- optional third-expert adjudication for disagreements

The benchmark should compare at least two systems:

- a simple baseline prompt evaluator
- the current contract-governed evaluator/verifier path

Useful metrics:

- agreement rate with the senior-interviewer label
- score-band drift against the baseline evaluator
- low-confidence calibration and abstain rate
- evidence-span miss rate
- contract coverage and `no` / missing acceptance rates
- verifier override / forced-refine rate

## 4. Reporting Rule

Do not report absolute model quality without the sample count and baseline.

Acceptable claim style:

> On 50 blind-test samples, the contract-governed evaluator improved agreement
> with senior-interviewer labels from X% to Y% compared with the baseline prompt,
> while reducing score drift by Z%.

Not acceptable:

> The AI interviewer scoring is 99% accurate.

## 5. Non-Goals For Now

- No runtime behavior change in Phase 3.0.
- No synthetic LLM labels as the gold standard.
- No public accuracy claim before real human-labeled samples exist.
- No production gate based on this layer until the sample set and report are
  repeatable.
