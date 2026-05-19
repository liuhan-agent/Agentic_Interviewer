---
id: tech_security_compliance_probe
name: Security Compliance Probe
description: Probe security / compliance answers for asset inventory, control mapping, audit evidence, and one residual risk the team chose to accept.
status: active
priority: 7
direction_tags: [internet_tech]
role_tags: [sre, architect, java_backend]
dimensions: [system_design, communication, project_experience, problem_solving]
job_levels: [senior, staff, principal]
probe_intents: [risk_probe, contract_probe, evidence_probe]
failure_categories: [missing_risk_boundary, vague_process, weak_follow_up]
generator_moves:
  - "Ask which compliance regime applied (SOC 2, ISO 27001, PCI, HIPAA, GDPR, DPDP, China DSL / PIPL) and which asset class was in scope."
  - "Probe the control mapping: which technical control answered which audit requirement, and where the evidence lived (CI logs, audit trail, ticketing, change record)."
  - "Ask one residual risk the team explicitly chose to accept, with the sign-off owner and the monitoring signal that watches it."
watch_for:
  - "Distinguishes threat model (security_risk_boundary terrain) from compliance attestation (audit terrain) — does not collapse them."
  - "Names a specific audit finding the team had to remediate and how the fix was verified."
avoid:
  - "Accepting 'we are SOC 2 compliant' as the answer without naming a control, an evidence artifact, or an audit finding."
  - "Letting the answer treat compliance as a one-time certification rather than a continuous control discipline."
evaluator_rubric_hints:
  - "Credit regime + scope, control-to-requirement mapping, evidence location, residual risk owner, and continuous monitoring."
positive_signals:
  - "Mentions evidence collection automation, change-management policy, vendor risk assessment, data classification, or DPA renegotiation."
negative_signals:
  - "Treats compliance as paperwork and cannot name a single engineering practice that changed because of it."
score_bias_rules:
  - "Soft positive when the candidate names a control the team intentionally over-engineered because audit fatigue would have cost more later."
evaluator_visibility: true
---

Use when the candidate discusses regulated workloads, audit response,
security certifications, data residency, vendor risk, or any topic
that turns security concerns into a continuous control discipline.

- Anchor every claim in **regime + scope + asset class**: SOC 2 Type
  II is not "everything"; PCI is not "the whole product"; GDPR is
  not "the privacy policy". Strong answers name which asset class
  is in scope and which is intentionally out.
- Force a **control-to-requirement mapping**: which technical control
  answered which audit requirement, where the evidence lived (CI
  logs, immutable audit trail, ticketing system, change record), and
  who is the named owner.
- Probe **one residual risk** the team explicitly accepted. Compliance
  is never zero risk; the strongest answers name what they did not
  control and how they monitored the gap.
- Reject "we passed the audit" as a process answer. Insist on one
  engineering practice that changed because of the regime: code
  review gate, infrastructure-as-code policy, secret rotation
  cadence, vendor onboarding playbook.
- For staff+ candidates, probe **organisational reality**: how the
  control roadmap is sequenced against feature delivery, how the
  legal / security / engineering partnership works, how audit findings
  are escalated and remediated without freezing the team.
