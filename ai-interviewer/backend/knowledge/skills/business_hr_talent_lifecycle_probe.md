---
id: business_hr_talent_lifecycle_probe
name: HR Talent Lifecycle Probe
description: Probe HR answers for sourcing funnel evidence, retention loop, and one talent decision that changed because of a measurable signal.
status: active
priority: 6
direction_tags: [business]
role_tags: [hr_function]
dimensions: [stakeholder_management, problem_solving, data_analysis, communication, decision_making]
job_levels: [mid, senior, staff]
probe_intents: [evidence_probe, process_design_probe, stakeholder_pushback_probe]
failure_categories: [missing_evidence, weak_attribution, weak_follow_up]
generator_moves:
  - "Ask which stage of the talent lifecycle (sourcing, screening, onboarding, performance, retention, offboarding) the candidate owned end-to-end."
  - "Probe the funnel: top-of-funnel pool, conversion rates, time-to-fill, attrition window, and which segment they intentionally chose to over- or under-invest in."
  - "Ask one talent decision (hire / promote / restructure / let go) that changed because of a measurable signal, and how they communicated it to the affected team."
watch_for:
  - "Connects HR metric to a business outcome (delivery velocity, customer attrition, leadership bench, regrettable attrition rate)."
  - "Separates structural drivers (compensation band, career ladder, manager quality) from individual incidents."
avoid:
  - "Accepting 'we ran a culture survey' without a follow-up action or measurable change."
  - "Letting the answer treat HR as administration rather than as a partner to business performance."
evaluator_rubric_hints:
  - "Credit funnel evidence, retention loop, structural driver analysis, and a decision changed by data."
positive_signals:
  - "Mentions regrettable vs non-regrettable attrition, 9-box calibration, leveling discipline, manager 1:1 cadence, or candidate scorecard."
negative_signals:
  - "Treats employee satisfaction score as an outcome rather than as one input."
score_bias_rules:
  - "Soft positive when the candidate names an HR initiative they killed because the data said it was not moving the metric."
evaluator_visibility: true
---

Use when the candidate is interviewing for an HR business partner,
talent acquisition lead, organisational development, or any role that
owns a stage of the employee lifecycle and reports to a business
sponsor.

- Anchor every claim in a **funnel metric**: top-of-funnel pool,
  conversion rate at each gate, time-to-fill, time-to-productivity,
  regrettable attrition, internal mobility rate. "We hired great
  people" without a funnel is treated as a recruiting brag.
- Force a **retention loop**: leading indicators (engagement,
  manager satisfaction, comp-ratio drift), lagging indicators (90-day
  attrition, year-one regrettable attrition), and the structural
  driver they changed because of the loop.
- Probe **one talent decision**: a hire who did not work, a promotion
  the team disagreed with, a layoff sequence, a leveling correction.
  Strong HR partners can name the data, the stakeholder negotiation,
  and the communication plan.
- Reject culture-survey theatre: a survey that did not change a
  policy or a manager is a data dashboard, not an HR outcome.
- For staff candidates, probe **organisational reality**: how the
  comp band was defended against market pressure, how leadership
  bench was developed, how the people analytics function negotiated
  privacy with information access.
