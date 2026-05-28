---
id: business_data_analyst_insight_probe
name: Data Analyst Insight Probe
description: Force data-analyst answers toward the decision changed, a ruled-out confounder, and the stakeholder who acted on the insight.
display_name_zh: 数据分析洞察追问卡
display_description_zh: 引导数据分析回答说明改变了什么决策、排除了什么混杂因素，以及哪个干系人据此行动。
status: active
priority: 7
direction_tags: [business]
role_tags: [data_analyst]
dimensions: [data_analysis, metrics_thinking, problem_solving, communication]
job_levels: [junior, mid, senior, staff]
probe_intents: [evidence_probe, metric_probe, experiment_probe]
failure_categories: [weak_attribution, missing_evidence, shallow_analysis]
generator_moves:
  - "Ask which business question their analysis answered, what decision changed, and who acted on it."
  - "Probe one confounding variable they ruled out and how (segment cut, control group, placebo metric, holdout, instrument)."
  - "Ask how they communicated the result: which audience, which artifact (Looker / Tableau / memo / readout), and which next step they recommended."
watch_for:
  - "Distinguishes correlation, causation, and Simpson's paradox in their own words."
  - "Names the stakeholder who actually moved a budget, headcount, roadmap, or campaign because of the analysis."
avoid:
  - "Accepting 'we built a dashboard' without naming the decision it drove or the audience that consumed it."
  - "Letting the answer treat SQL fluency as the entire skill — without hypothesis, decision, or stakeholder."
evaluator_rubric_hints:
  - "Credit decision changed, named confounder ruled out, communication artifact, and stakeholder action."
positive_signals:
  - "Mentions hypothesis, baseline, segmentation, lift over control, statistical or domain caveat surfaced to the audience."
negative_signals:
  - "Reports a metric movement without saying what alternative explanation they considered or what the org did next."
score_bias_rules:
  - "Soft positive when the candidate names an analysis they ran that explicitly recommended **not** to ship something."
evaluator_visibility: true
---

Use when the candidate is an analyst, BI / insights, marketing or
growth analyst, finance analyst, or any role whose deliverable is a
report, dashboard, or readout consumed by business decision-makers.

- Anchor the answer in the **business question**: what decision was
  hanging on the analysis, who owned the decision, what timeline.
  Analysis without a downstream decision is treated as a SQL exercise.
- Force one **ruled-out confounder** to surface: seasonality, campaign
  overlap, audience shift, instrumentation change, Simpson's paradox.
  Strong analysts name the alternative explanation **before** they name
  the recommendation.
- Probe the **communication artifact**: was it a Looker dashboard, a
  written memo, a stand-up readout, an exec one-pager? Different audience
  → different artifact → different bar for caveats.
- Require the **stakeholder action**: who moved budget, paused a
  campaign, killed a feature, expanded a cohort. If nobody acted, ask
  why the analysis did not change anyone's mind.
- For senior analysts, probe one **analysis that said "no"**: a result
  that explicitly recommended against shipping or against scaling. The
  strongest analysts are remembered for the bets they prevented, not
  only the ones they validated.
