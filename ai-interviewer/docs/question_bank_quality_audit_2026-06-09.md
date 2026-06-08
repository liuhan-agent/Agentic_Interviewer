# Question Bank Quality Audit - 2026-06-09

## Scope

This audit is read-only. It does not bulk-edit YAML and does not change runtime scoring.

Inputs:

- `ai-interviewer/backend/knowledge/question_seeds`
- Existing reviewed acceptance coverage reporter
- A deterministic local scan over YAML seed/variant/rubric/reviewed-check fields

Commands run:

```bash
cd ai-interviewer/backend
python -m app.scripts.report_reviewed_acceptance_coverage knowledge/question_seeds
pytest tests/unit -q
```

Latest full backend unit result before this audit: `2189 passed, 4 skipped`.

## Snapshot

| Metric | Count |
| --- | ---: |
| Total seeds | 162 |
| Total variants | 324 |
| Variants with reviewed checks | 268 |
| Variants without reviewed checks | 56 |
| Reviewed checks | 1877 |
| Draft/deprecated checks | 0 |
| Stale reviewed checks | 0 |
| DB/YAML mismatches reported by coverage tool | 0 |
| `source_text` mismatches against `must_cover` / `rubric_additions` | 0 |

The main quality risk is no longer schema validity. The main risk is semantic alignment:
selector anchors, `must_cover`, reviewed/core, reviewed/supporting, and variant context must all point at the same topic.

## P0 Findings

### 1. Missing Reviewed Checks

56 variants have no reviewed checks. In `reviewed_append` mode these fall back to deterministic compiled checks; in enforce mode they do not provide reviewed/core gate coverage.

Grouped by dimension:

| Dimension | Missing variants |
| --- | ---: |
| `communication` | 30 |
| `product_thinking` | 24 |
| `leadership` | 2 |

Full missing list:

`communication`

- `communication.frontend_design_backend_alignment.design_tradeoff`
- `communication.frontend_design_backend_alignment.api_contract`
- `communication.sre_incident_stakeholder_alignment.incident_update`
- `communication.sre_incident_stakeholder_alignment.postmortem_alignment`
- `communication.ai_fullstack_cross_role_alignment.quality_expectation`
- `communication.ai_fullstack_cross_role_alignment.data_permission`
- `communication.ai_agent_risk_alignment.tool_permission`
- `communication.ai_agent_risk_alignment.effect_review`
- `communication.mobile_release_alignment.version_scope`
- `communication.mobile_release_alignment.backend_contract`
- `communication.ai_algorithm_metric_explanation.offline_online_gap`
- `communication.ai_algorithm_metric_explanation.risk_tradeoff`
- `communication.java_technical_tradeoff_explanation.consistency_tradeoff`
- `communication.java_technical_tradeoff_explanation.performance_risk`
- `communication.java_cross_team_incident_alignment.permission_change_rollout`
- `communication.java_cross_team_incident_alignment.mq_incident_alignment`
- `communication.architect_review_alignment.risk_explanation`
- `communication.architect_review_alignment.disagreement_resolution`
- `communication.ai_agent_failure_alignment.metric_consensus`
- `communication.ai_agent_failure_alignment.post_incident`
- `communication.ai_fullstack_failure_explanation.cross_role_briefing`
- `communication.ai_fullstack_failure_explanation.expectation_reset`
- `communication.ai_algorithm_dumb_explanation.attribution`
- `communication.ai_algorithm_dumb_explanation.expectation_reset`
- `communication.frontend_web_cross_role_alignment_round2.shared_consensus`
- `communication.frontend_web_cross_role_alignment_round2.timeline_risk`
- `communication.sre_stability_governance.alignment`
- `communication.sre_stability_governance.escalation`
- `communication.mobile_cross_role_coordination.shared_consensus`
- `communication.mobile_cross_role_coordination.deadline`

`product_thinking`

- `product_thinking.frontend_experience_resilience.dashboard`
- `product_thinking.frontend_experience_resilience.checkout`
- `product_thinking.ai_agent_effect_loop.support_resolution`
- `product_thinking.ai_agent_effect_loop.user_control`
- `product_thinking.ai_fullstack_experience_metrics.ai_copilot`
- `product_thinking.ai_fullstack_experience_metrics.latency_quality_tradeoff`
- `product_thinking.ai_algorithm_business_metric.recommendation_ctr`
- `product_thinking.ai_algorithm_business_metric.risk_metric`
- `product_thinking.ai_agent_negative_scope.refusal_design`
- `product_thinking.ai_agent_negative_scope.boundary_evolution`
- `product_thinking.ai_agent_trace_transparency.user_view`
- `product_thinking.ai_agent_trace_transparency.audit_view`
- `product_thinking.ai_fullstack_explainable_ux.first_use`
- `product_thinking.ai_fullstack_explainable_ux.failure_recovery`
- `product_thinking.ai_fullstack_scope_judgement.decision_framework`
- `product_thinking.ai_fullstack_scope_judgement.business_alignment`
- `product_thinking.ai_algorithm_metric_to_outcome.translation`
- `product_thinking.ai_algorithm_metric_to_outcome.calibration`
- `product_thinking.ai_algorithm_commitment_boundary.scope`
- `product_thinking.ai_algorithm_commitment_boundary.risk_plan`
- `product_thinking.frontend_web_micro_interaction.state_design`
- `product_thinking.frontend_web_micro_interaction.long_polling`
- `product_thinking.frontend_web_ab_test.frontend_impl`
- `product_thinking.frontend_web_ab_test.data_trust`

`leadership`

- `leadership.architect_technical_governance.arch_review`
- `leadership.architect_technical_governance.cross_team_standard`

Priority:

1. Add reviewed checks for Java/AI-agent/AI-fullstack communication variants.
2. Add reviewed checks for AI/product-thinking variants.
3. Add reviewed checks for remaining frontend/SRE/mobile/product-thinking variants.
4. Add leadership architect variants last unless architect interviews become frequent.

### 2. Core/Supporting Classification Mismatch

6 reviewed variants have a mismatch between seed `must_cover` count and reviewed/core count. These are high risk because enforce gate reads only `reviewed/core`, so misplaced core clauses can make the gate too lenient or too strict.

| Variant | Dimension | Current core / must_cover | Current supporting / additions | Notes |
| --- | --- | ---: | ---: | --- |
| `system_design.cache_consistency.flash_sale_inventory` | `system_design` | 1 / 4 | 6 / 3 | Three must-cover items are currently supporting. |
| `system_design.cache_consistency.redis_failover_repair` | `system_design` | 1 / 4 | 6 / 3 | Same risk pattern as flash-sale cache. |
| `technical_depth.java_transaction_consistency.order_payment_boundary` | `technical_depth` | 2 / 4 | 5 / 3 | `异步补偿` / `对账修复` should be re-checked as core candidates. |
| `technical_depth.java_transaction_consistency.outbox_compensation` | `technical_depth` | 3 / 4 | 4 / 3 | `对账修复` likely misplaced as supporting. |
| `problem_solving.java_cache_message_consistency.consumer_lag_repair` | `problem_solving` | 2 / 4 | 5 / 3 | `一致性边界` / `修复验证` likely misplaced as supporting. |
| `project_experience.java_performance_optimization_review.database_write_reduction` | `project_experience` | 2 / 4 | 5 / 3 | `验证指标` / `风险控制` likely misplaced as supporting. |

Priority:

1. Fix `system_design.cache_consistency.*`, because these are high-frequency Java backend system design variants.
2. Fix `technical_depth.java_transaction_consistency.*`, because they directly affect transaction consistency assessment.
3. Fix `problem_solving.java_cache_message_consistency.consumer_lag_repair`.
4. Fix `project_experience.java_performance_optimization_review.database_write_reduction`.

### 3. Non-Variant Check IDs

7 variants / 49 checks use short pilot-style check IDs that do not include the full variant id. Runtime can still consume them, but trace/debugging/source audits are weaker.

Affected variants:

- `coding_quality.java_api_contract_idempotency.client_retry_status`
- `problem_solving.java_async_retry_incident.mq_duplicate_delivery`
- `problem_solving.java_cache_message_consistency.consumer_lag_repair`
- `system_design.cache_consistency.flash_sale_inventory`
- `system_design.cache_consistency.redis_failover_repair`
- `technical_depth.java_transaction_consistency.order_payment_boundary`
- `technical_depth.java_transaction_consistency.outbox_compensation`

Priority: fix together with the core/supporting cleanup where variants overlap. Do not rewrite IDs alone if it would churn trace comparisons without improving clauses.

## P1 Candidate Risks

### 4. Topic-Alignment Candidates

A heuristic scan found topic-alignment candidates where the variant/seed looks specialized but reviewed/core text may not carry the same domain vocabulary.

Counts from the heuristic scan:

| Topic | Candidate count |
| --- | ---: |
| AI/RAG/LLM/Agent | 74 |
| Frontend | 38 |
| Mobile | 31 |
| SRE | 27 |
| Algorithm | 9 |

Important: this is a triage list, not a defect list. The heuristic intentionally over-flags. For example, an id containing `ai_strategy` may be a business strategy variant rather than an LLM/Agent variant.

Representative candidates worth manual review first:

- `problem_solving.ai_fullstack_contract_regression.model_response_schema`
- `problem_solving.ai_fullstack_contract_regression.prompt_versioning`
- `problem_solving.ai_agent_failure_evaluation.wrong_tool_action`
- `problem_solving.ai_agent_failure_evaluation.hallucinated_answer`
- `technical_depth.ai_fullstack_ai_app_integration.streaming_response`
- `technical_depth.ai_fullstack_ai_app_integration.async_job`
- `project_experience.ai_fullstack_end_to_end_delivery.internal_copilot`
- `project_experience.ai_fullstack_end_to_end_delivery.feedback_iteration`
- `project_experience.ai_algorithm_online_delivery.recommendation_launch`
- `project_experience.ai_algorithm_online_delivery.cross_team_iteration`
- `coding_quality.frontend_web_type_contract.public_api`
- `coding_quality.frontend_web_type_contract.evolution`
- `technical_depth.mobile_cross_platform_tradeoff.selection`
- `technical_depth.mobile_cross_platform_tradeoff.migration`

Recommended handling:

- Do not batch-edit from this list automatically.
- For each candidate, inspect whether `reviewed/core` is genuinely too generic or whether the topic was a naming false positive.
- If true, make clause text mention the domain-specific object being judged, not just the generic engineering behavior.

### 5. Missing Selector Anchors

4 variants appear to mention a specialized topic in id/title/stem but do not expose enough matching terms in `skill_tags` / `scenario_skill_tags` / `resume_anchor_hints`.

| Variant | Candidate topic |
| --- | --- |
| `coding_quality.java_agent_extension_boundaries.ai_strategy_hot_swap` | AI/RAG/Agent |
| `technical_depth.mobile_cross_platform_tradeoff.selection` | Frontend |
| `technical_depth.mobile_cross_platform_tradeoff.migration` | Frontend |
| `user_insight.user_journey_pain_point.cross_channel_onboarding` | Mobile |

These need manual review because some may be naming false positives. The Java AI workflow issue fixed on 2026-06-09 belongs to this class: the seed had the right intent but insufficient selector anchors for `LangChainJ` / `Spring-AI` / `RAG`.

## Recommended Repair Order

### Batch A - Hard Gate Correctness

Fix the 6 core/supporting mismatches and their short pilot-style IDs where applicable.

Target files:

- `system_design.yaml`
- `technical_depth.yaml`
- `problem_solving.yaml`
- `project_experience.yaml`

Expected benefit: reviewed/core gate becomes semantically aligned with `must_cover` for high-frequency Java backend dimensions.

### Batch B - Reviewed Coverage Holes

Add reviewed checks for the 56 missing variants.

Recommended order:

1. `communication.java_*`, `communication.ai_agent_*`, `communication.ai_fullstack_*`
2. `product_thinking.ai_agent_*`, `product_thinking.ai_fullstack_*`, `product_thinking.ai_algorithm_*`
3. Remaining frontend/SRE/mobile communication and product-thinking variants
4. `leadership.architect_technical_governance.*`

Expected benefit: fewer compiled fallback contracts, better source-aware report/gate coverage.

### Batch C - Topic Alignment Review

Manually review the representative topic-alignment candidates. Promote only confirmed mismatches into YAML edits.

Expected benefit: fewer cases where a specialized question is judged by generic reviewed clauses.

### Batch D - Regression Tests

For every repaired high-risk selector/contract mismatch, add a focused regression test:

- Candidate/JD context should select the specialized seed over a generic seed.
- Reviewed/core items should come from the selected variant.
- `contract_gate_result.eligible_count` should be non-zero when reviewed/core exists.
- Trace diagnostics should not contain `reviewed_acceptance_topic_mismatch` for the repaired scenario.

## Proposed Next Step

Start with Batch A. It is small, deterministic, and directly affects reviewed/core enforcement correctness. It should not require broad selector changes or LLM prompt changes.

## Remediation Log

- 2026-06-09: Batch A completed. The 6 core/supporting classification mismatches were corrected, short pilot-style check IDs were replaced where they overlapped with the Batch A variants, strict lint now enforces reviewed/core alignment with `must_cover`, and the local runtime DB was synced with `updated_variants=6`.
- 2026-06-09: Batch B-1 completed. Added reviewed checks for 16 Java/AI communication variants. Coverage moved to 284 / 324 variants with reviewed checks, reviewed checks moved to 1989 total, `variants_without_reviewed` dropped to 40, and the local runtime DB was synced with `updated_variants=16`.
- 2026-06-09: Batch B-2 completed. Added reviewed checks for 18 AI product-thinking variants. Coverage moved to 302 / 324 variants with reviewed checks, reviewed checks moved to 2115 total, `variants_without_reviewed` dropped to 22, and the local runtime DB was synced with `updated_variants=18`.
- 2026-06-09: Batch B-3 completed. Added reviewed checks for 14 remaining technical communication variants and 6 frontend product-thinking variants. Coverage moved to 322 / 324 variants with reviewed checks, reviewed checks moved to 2255 total, `variants_without_reviewed` dropped to 2, and the local runtime DB was synced with `updated_variants=20`. The only remaining uncovered variants are `leadership.architect_technical_governance.arch_review` and `leadership.architect_technical_governance.cross_team_standard`.
- 2026-06-09: Batch B-4 completed. Added reviewed checks for the final 2 leadership architect variants. Coverage moved to 324 / 324 variants with reviewed checks, reviewed checks moved to 2269 total, `variants_without_reviewed` dropped to 0, and the local runtime DB was synced with `updated_variants=2`.
