---
id: tech_sre_slo_capacity_probe
name: SRE SLO and Capacity Probe
description: Drive SRE answers toward defined SLO / SLI, error budget governance, and one capacity bound the candidate personally signed off on.
status: active
priority: 7
direction_tags: [internet_tech]
role_tags: [sre, architect]
dimensions: [system_design, technical_depth, problem_solving, project_experience]
job_levels: [senior, staff, principal]
probe_intents: [performance_probe, tradeoff_probe, risk_probe]
failure_categories: [missing_scale_reasoning, missing_risk_boundary, weak_attribution]
generator_moves:
  - "Ask for the SLI definition, SLO target, and the error-budget policy that decided whether to ship or freeze."
  - "Probe the capacity model: headroom factor, saturation signal, queueing or storage knee they planned around, and the load test that justified it."
  - "Ask one incident where the error budget actually changed a team's decision (release freeze, rollback, scope cut, headcount ask)."
watch_for:
  - "Separates SLI (measured), SLO (committed target), and SLA (contractual penalty) without merging them into 'uptime'."
  - "Names the capacity bound with a saturation point, not only an average utilization number."
avoid:
  - "Accepting 'we run on Kubernetes / cloud autoscaler' as the capacity answer without a saturation signal or queueing model."
  - "Letting error budget become a vanity dashboard with no decision attached."
evaluator_rubric_hints:
  - "Credit explicit SLI / SLO / error-budget policy, a defended capacity bound, and one decision the budget actually drove."
positive_signals:
  - "Mentions burn rate alerting, multi-window SLO burn, queueing model, headroom factor, or load test with named failure mode."
negative_signals:
  - "Quotes 99.9% uptime without saying which user journey, measurement window, or attribution rule it covers."
score_bias_rules:
  - "Soft positive when the candidate names an SLO they intentionally relaxed and what they bought with the relaxation."
evaluator_visibility: true
---

Use when the candidate discusses reliability engineering, on-call,
incident response patterns, capacity planning, autoscaling, queueing
behavior, or platform reliability for staff+ infrastructure roles.

- Anchor every reliability claim in **three named artefacts**: the SLI
  (what is measured), the SLO (what is committed), and the error-budget
  policy (what happens when it is spent). "99.9% uptime" without these
  three is treated as a marketing slide.
- Force a **defended capacity bound**: a saturation point on CPU /
  memory / IOPS / connection pool / queue depth / storage size, plus
  the load test or production trace that justified the number. Generic
  "we autoscale" is not a capacity answer; it is a deferral.
- Probe one **error-budget decision**: a release freeze, a feature
  rollback, a roadmap reordering, or an explicit choice to spend the
  remaining budget on a risky launch. If the budget never changed
  anyone's behavior, it is not an SLO — it is a dashboard.
- For staff+ candidates, probe **organisational reality**: how the SLO
  is negotiated with product owners, how on-call burden is balanced
  against feature velocity, and how reliability investment shows up in
  the next quarter's planning.
- Reject "we follow the SRE book" as a process answer. Insist on one
  practice they intentionally **did not** adopt, and why their team's
  constraints made the canonical pattern wrong.
