---
id: business_stakeholder_alignment_probe
name: Stakeholder Alignment Probe
description: Test how the candidate handles conflicting goals, decision rights, and communication cadence.
status: active
priority: 6
direction_tags: [business]
role_tags: [product_manager, operations, marketing_brand, general_management]
dimensions: [stakeholder_management, prioritization, communication, team_leadership, decision_making, goal_setting]
job_levels: [mid, senior, staff]
probe_intents: [stakeholder_pushback_probe, prioritization_probe, process_design_probe]
failure_categories: [weak_stakeholder_alignment, poor_communication, weak_prioritization]
generator_moves:
  - "Ask who owned the decision, who could block it, and what each stakeholder needed."
  - "Probe the communication cadence after the initial agreement."
watch_for:
  - "Separates alignment, decision authority, execution ownership, and follow-up."
avoid:
  - "Accepting 'we aligned everyone' without decision rights or tradeoff evidence."
evaluator_rubric_hints:
  - "Credit explicit stakeholder map, decision owner, objection handling, and follow-up cadence."
positive_signals:
  - "Names the blocking concern and how the plan changed."
negative_signals:
  - "Treats communication as a meeting rather than an ongoing operating rhythm."
score_bias_rules:
  - "Soft positive when the answer includes a concrete post-decision check-in mechanism."
evaluator_visibility: true
---

Use when a business or management answer depends on cross-team agreement.

- Ask who owned the final decision and who could block execution.
- Ask what each stakeholder cared about and how the candidate changed the
  proposal.
- Ask what communication rhythm kept alignment after the meeting.
- Strong answers separate alignment, decision, execution, and follow-up.
