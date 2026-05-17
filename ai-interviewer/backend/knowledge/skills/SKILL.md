# Interview Skills

Hand-authored interviewer playbook cards for the Generator. These cards do
not decide what question to ask; structured question seeds own that. Skills
tell the interviewer how to probe the selected question, which signals to
watch, and which shallow answer shapes to avoid.

Skills are sibling to `knowledge/strategy/`:

- `skills/`: hand-authored, static playbook cards curated by humans.
- `strategy/`: reward-driven memory maintained by `strategy_dream`.

The runtime reads skill cards through `app.memory.skill_store`, not through
Chroma/RAG. Frontmatter is used for rule selection by direction, role,
dimension, level, probe intent, and failure category.

## Available Skills

- [Concrete Evidence Probe](universal_concrete_evidence_probe.md)
- [Metric And Baseline Probe](universal_metric_baseline_probe.md)
- [Tradeoff Constraint Probe](universal_tradeoff_constraint_probe.md)
- [System Design Scale Reasoning](system_design_scale_reasoning.md)
- [Senior Backend Ownership Probe](senior_backend_ownership_probe.md)
- [Production Incident Probe](tech_production_incident_probe.md)
- [Code Boundary Quality Probe](tech_code_boundary_quality_probe.md)
- [Rollout And Migration Probe](tech_rollout_migration_probe.md)
- [Business User Metric Probe](business_user_metric_probe.md)
- [Stakeholder Alignment Probe](business_stakeholder_alignment_probe.md)
- [Sales Objection Diagnosis Probe](sales_objection_diagnosis_probe.md)
- [Service Escalation Probe](service_escalation_probe.md)
