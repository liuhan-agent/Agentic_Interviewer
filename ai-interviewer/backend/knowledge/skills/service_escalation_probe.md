---
id: service_escalation_probe
name: Service Escalation Probe
description: Probe service, HR, and management cases for severity, owner, cadence, and closure standard.
status: active
priority: 6
direction_tags: [business]
role_tags: [customer_success, hr_function, general_management, operations]
dimensions: [customer_empathy, issue_diagnosis, escalation_management, service_orientation, employee_relations, execution_management]
job_levels: [junior, mid, senior]
probe_intents: [escalation_probe, roleplay_probe, process_design_probe]
failure_categories: [poor_communication, missing_risk_boundary, weak_follow_up]
generator_moves:
  - "Ask how severity was classified and what condition triggered escalation."
  - "Probe owner, next update time, empathy boundary, and closure criteria."
watch_for:
  - "Balances empathy with realistic commitment and recurrence prevention."
avoid:
  - "Accepting a service attitude answer without owner, cadence, or closure standard."
evaluator_rubric_hints:
  - "Credit severity logic, escalation trigger, stakeholder cadence, and closure criteria."
positive_signals:
  - "States what would be escalated, to whom, and by when."
negative_signals:
  - "Promises resolution without checking authority, SLA, or root cause."
score_bias_rules:
  - "Soft positive when the answer includes recurrence prevention, not only case closure."
evaluator_visibility: true
---

Use when the scenario involves customer complaint, internal service request,
people conflict, or delivery escalation.

- Ask how the candidate classified severity and what would trigger escalation.
- Ask who owned the next action and when the next update would happen.
- Ask how they kept empathy without promising an impossible outcome.
- Strong answers include closure criteria and recurrence prevention.
