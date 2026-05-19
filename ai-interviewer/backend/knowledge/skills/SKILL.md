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

### Universal (apply across direction / role / dimension)

- [Concrete Evidence Probe](universal_concrete_evidence_probe.md)
- [Metric And Baseline Probe](universal_metric_baseline_probe.md)
- [Tradeoff Constraint Probe](universal_tradeoff_constraint_probe.md)

### Internet Tech direction

- [System Design Scale Reasoning](system_design_scale_reasoning.md)
- [Senior Backend Ownership Probe](senior_backend_ownership_probe.md)
- [Production Incident Probe](tech_production_incident_probe.md)
- [Code Boundary Quality Probe](tech_code_boundary_quality_probe.md)
- [Rollout And Migration Probe](tech_rollout_migration_probe.md)
- [AI Evaluation Probe](tech_ai_evaluation_probe.md)
- [API Contract Probe](tech_api_contract_probe.md)
- [Security Risk Boundary Probe](tech_security_risk_boundary_probe.md)
- [Testing Confidence Probe](tech_testing_confidence_probe.md)
- [Performance Bottleneck Probe](tech_performance_bottleneck_probe.md)
- [Debug Root Cause Probe](tech_debug_root_cause_probe.md)
- [Data Engineering Pipeline Probe](tech_data_engineering_pipeline_probe.md)
- [Frontend Performance and Render Probe](tech_frontend_perf_render_probe.md)
- [Mobile Platform Probe](tech_mobile_platform_probe.md)
- [SRE SLO and Capacity Probe](tech_sre_slo_capacity_probe.md)
- [QA Test Strategy Probe](tech_qa_test_strategy_probe.md)
- [AI Algorithm Training Probe](tech_ai_algorithm_training_probe.md)
- [Security Compliance Probe](tech_security_compliance_probe.md)
- [Senior Backend Distributed State Probe](senior_backend_distributed_state_probe.md)

### Business direction

- [Business User Metric Probe](business_user_metric_probe.md)
- [Stakeholder Alignment Probe](business_stakeholder_alignment_probe.md)
- [Sales Objection Diagnosis Probe](sales_objection_diagnosis_probe.md)
- [Service Escalation Probe](service_escalation_probe.md)
- [Business Executive Strategy Probe](business_executive_strategy_probe.md)
- [Data Analyst Insight Probe](business_data_analyst_insight_probe.md)
- [UX Research and Design Decision Probe](design_ux_research_probe.md)
- [HR Talent Lifecycle Probe](business_hr_talent_lifecycle_probe.md)
- [Pricing and Packaging Probe](business_pricing_packaging_probe.md)
