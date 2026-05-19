---
id: tech_qa_test_strategy_probe
name: QA Test Strategy Probe
description: Probe QA / test engineering answers for test pyramid choice, environment / data realism, and defect-class coverage versus residual risk.
status: active
priority: 7
direction_tags: [internet_tech]
role_tags: [qa_engineer]
dimensions: [coding_quality, problem_solving, project_experience, technical_depth]
job_levels: [junior, mid, senior, staff]
probe_intents: [evidence_probe, tradeoff_probe, rollout_probe]
failure_categories: [missing_evidence, vague_process, weak_risk_boundary]
generator_moves:
  - "Ask which defect classes the test strategy was meant to catch, and which layer (unit / integration / contract / e2e / canary / manual) owned each one."
  - "Probe environment realism: test data freshness, anonymisation, third-party stub fidelity, and what broke when the test env diverged from prod."
  - "Ask one regression that escaped despite the strategy and what gate the team added afterwards."
watch_for:
  - "Distinguishes flaky test from real defect signal, and explains how flakes were triaged before being suppressed."
  - "Maps test investment to risk class, not to a coverage percentage."
avoid:
  - "Accepting 'we have 80% coverage' as the strategy answer without naming a single bug class it caught."
  - "Treating QA as a gating step rather than an ongoing partnership with developers and SRE."
evaluator_rubric_hints:
  - "Credit risk-based layer selection, environment / data realism plan, flake governance, and one escaped regression with the resulting gate."
positive_signals:
  - "Mentions contract test, mutation test, shadow traffic, canary diff, data masking, or quarantine policy."
negative_signals:
  - "Quotes coverage numbers without naming the defect class they bought."
score_bias_rules:
  - "Soft positive when the candidate explains what they intentionally did not test and why the risk was acceptable."
evaluator_visibility: true
---

Use when the candidate is interviewing for QA / test engineering, SDET,
or any role responsible for release confidence beyond raw developer
unit tests.

- Anchor the answer in **defect classes**, not test types. Push past
  "we did unit / integration / e2e" toward "the missing-null-check
  class caught by mutation testing on the payment service".
- Probe **environment realism**: how test data was generated, refreshed,
  anonymised; how third-party dependencies were stubbed and how stub
  drift was detected; what blew up the first time a holiday surge
  hit the test env.
- Force one **escaped regression** to surface. Strong QA leaders can
  name a bug the strategy missed and the gate that was added afterward
  (canary diff, contract test, dark launch).
- Reject coverage numbers as evidence. A 95% coverage line that does
  not catch one named defect class is a vanity metric.
- For staff+ candidates, probe **organisational reality**: how the QA
  budget is negotiated, how flake triage is staffed, how release
  velocity is balanced against confidence.
