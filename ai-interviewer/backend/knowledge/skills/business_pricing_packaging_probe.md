---
id: business_pricing_packaging_probe
name: Pricing and Packaging Probe
description: Probe pricing / packaging answers for willingness-to-pay evidence, unit-economics math, and one packaging move that traded short-term revenue for long-term position.
status: active
priority: 7
direction_tags: [business]
role_tags: [product_manager, sales_business]
dimensions: [user_insight, metrics_thinking, decision_making, market_insight]
job_levels: [senior, staff, principal]
probe_intents: [evidence_probe, tradeoff_probe, experiment_probe]
failure_categories: [weak_attribution, missing_evidence, weak_prioritization]
generator_moves:
  - "Ask which willingness-to-pay evidence (van Westendorp, conjoint, A/B test, sales-recorded deal blockers, churn reason) informed the price."
  - "Probe the unit economics: CAC, payback period, gross margin, expansion revenue, and the threshold that made the package shippable."
  - "Ask one packaging move that traded short-term revenue for long-term position (feature gating, tier consolidation, grandfathering policy, free tier expansion or removal)."
watch_for:
  - "Separates price (the number), packaging (which features land in which tier), and discounting (sales discretion) — does not collapse them."
  - "Names the customer segment the move was optimised for, and the segment that explicitly paid for the change."
avoid:
  - "Accepting 'we raised price' without churn impact, expansion impact, or a deal-velocity reading."
  - "Letting the answer treat pricing as a marketing slogan rather than as a continuously monitored economic contract."
evaluator_rubric_hints:
  - "Credit willingness-to-pay evidence, unit-economics math, packaging tradeoff, and post-change monitoring."
positive_signals:
  - "Mentions cohort churn delta, downgrade rate, ARR mix shift, deal slip rate, or grandfathering rollout plan."
negative_signals:
  - "Treats price changes as a one-off decision rather than as an experiment with a measurable post-period."
score_bias_rules:
  - "Soft positive when the candidate names a pricing experiment they killed because the long-term cohort signal was worse than the short-term revenue lift."
evaluator_visibility: true
---

Use when the candidate is interviewing for a pricing strategy role,
monetisation product manager, GTM lead, or any senior PM / sales
leader expected to own packaging and price as a continuous discipline.

- Anchor every claim in **willingness-to-pay evidence**: van
  Westendorp survey, conjoint, A/B test on price page, sales-call
  blockers, churn reason coding, deal-velocity comparison. Strong
  answers name the method and its limitation (sample bias, social
  desirability, recall error).
- Force a **unit-economics number** to surface: CAC, payback period,
  gross margin, ARR retention, expansion rate, free-to-paid
  conversion. The package is shippable only when this number clears
  a threshold the candidate can defend.
- Probe **one packaging move** that traded short-term revenue for
  long-term position: a tier consolidation, a feature shifted to a
  higher tier, a free tier expanded, a grandfathering policy. Strong
  answers name what they would do differently with the same data
  today.
- Reject "we raised price 10%" as a strategy answer. Insist on the
  cohort churn delta in the next two quarters, the deal slip rate
  during the announce window, and the renewal renegotiation pattern
  six months later.
- For staff+ candidates, probe **organisational reality**: how
  pricing decisions are governed (pricing committee, exec sign-off),
  how sales discretion is bounded, how finance and legal are
  partnered in for international pricing.
