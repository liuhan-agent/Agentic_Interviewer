---
id: tech_data_engineering_pipeline_probe
name: Data Engineering Pipeline Probe
description: Force data-pipeline answers toward freshness contract, ordering / dedup, and downstream consumer impact.
display_name_zh: 数据管道追问卡
display_description_zh: 引导数据管道回答覆盖 freshness contract、ordering / dedup，以及下游消费者影响。
status: active
priority: 8
direction_tags: [internet_tech]
role_tags: [java_backend, ai_algorithm, architect]
dimensions: [system_design, technical_depth, problem_solving, project_experience]
job_levels: [junior, mid, senior, staff, principal]
probe_intents: [contract_probe, performance_probe, evidence_probe]
failure_categories: [missing_scale_reasoning, weak_attribution, missing_risk_boundary]
generator_moves:
  - "Ask which data is fact vs dimension, where lateness or duplicates were tolerated, and which downstream consumer paid for it."
  - "Probe schema evolution, backfill strategy, and one corrupted-batch recovery example with the impacted SLA."
  - "Ask how they distinguished a producer bug from a consumer bug when the same metric looked wrong on both sides."
watch_for:
  - "Separates streaming, micro-batch, and batch tradeoffs by SLA and freshness window."
  - "Names a concrete downstream owner who consumed the data and the contract they agreed on."
avoid:
  - "Accepting 'Spark/Flink/Kafka/Airflow' as architecture without explaining ordering, exactly-once, or replay semantics."
  - "Letting the answer hide behind 'we use the data platform team' without owning a contract."
evaluator_rubric_hints:
  - "Credit freshness contract, ordering / dedup guarantee, schema-evolution plan, and named downstream owner."
positive_signals:
  - "Mentions watermark, late-arriving data window, idempotent key, or replay-safe checkpoint."
negative_signals:
  - "Cannot say which consumer breaks first when the pipeline lags or replays."
score_bias_rules:
  - "Soft negative when both freshness contract and dedup / ordering guarantee are absent."
evaluator_visibility: true
---

Use when the scenario involves data ingestion, ETL / ELT pipelines, stream
processing, lakehouse, feature stores, or any data product consumed by
downstream services or analytics.

- Ask for the freshness contract first: how late is too late, who notices,
  and what dashboard / model degrades when the SLA slips.
- Require ordering / dedup discipline: which key guarantees idempotency,
  what happens on producer retry, how late-arriving records are reconciled.
- Probe schema evolution: how a new column / type change reaches the
  consumer without a breaking deploy, and what migration window stayed
  in dual-write.
- Force at least one **downstream owner** to surface: a metric, model,
  finance close, or operations workflow that paid for the pipeline.
- Reject "we use Spark / Flink / Kafka" as architecture; insist on the
  failure mode the chosen stack is protecting against and the operational
  cost of the chosen guarantee (latency vs throughput vs cost).
