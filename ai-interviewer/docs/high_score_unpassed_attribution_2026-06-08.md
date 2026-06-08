# 高分但未通过归因清单

生成时间：2026-06-08

样本范围：本地运行库中已有 `final_report` 的 52 场面试。只统计最终报告维度结果里满足以下条件的维度：

- `score_status = scored`
- `score >= quality_threshold`
- `passed = false`

统计口径：按 `final_report.dimension_scores` 的维度结果去重，不按 `evaluator` / `verification` trace 节点重复计数。

## 总览

- 命中维度数：20
- 报告侧状态：20 个全部为 `coverage_limited`
- 维度分布：
  - `problem_solving`: 6
  - `system_design`: 5
  - `coding_quality`: 5
  - `technical_depth`: 2
  - `project_experience`: 1
  - `communication`: 1

## 归因分层

| 层级 | 数量 | 含义 | 处理建议 |
| --- | ---: | --- | --- |
| A 硬拦截：`contract_gate_enforced` | 4 | reviewed/core gate 在 enforce 模式下失败，主链路被强制压成未通过 | 暂不放松；只复核 check 文案和 severity 是否真的属于 core |
| B 硬缺口候选：reviewed/core 未满足但未 enforced | 1 | gate 在 shadow 模式下失败，或未强制生效 | 先观察；不直接改主链路 |
| C 硬缺口候选：`no` / `missing` | 14 | 存在 acceptance `no` 或 rubric `missing`，但多为老记录或非 reviewed/core 结构 | 需要人工抽样复核，判断是否被旧口径误伤 |
| D 软缺口候选：partial-only | 1 | 只有 `partial` / `rubric_partial`，没有明确 `no` / `missing` | 已收敛：partial-only 不再直接压主链路 |

## 明细清单

| # | 归因 | Session | 维度 | 分数 | 主要触发原因 |
| ---: | --- | --- | --- | --- | --- |
| 1 | A 硬拦截 | `sess-20260607-155911-b93e96` | `problem_solving` | 7.0 / 7.0 | reviewed/core gate 失败：任务状态、重试边界、死信/告警/人工审核未满足；另有止血方案缺口 |
| 2 | A 硬拦截 | `sess-20260607-182939-204340` | `problem_solving` | 7.0 / 7.0 | reviewed/core gate 失败：MQ lag 复现证据、权威源边界、用户侧降级说明不足 |
| 3 | A 硬拦截 | `sess-20260607-182939-204340` | `system_design` | 7.0 / 7.0 | reviewed/core gate 失败：缓存失效策略和不一致窗口未说明；超卖/少卖/释放回补策略不足 |
| 4 | A 硬拦截 | `sess-20260607-182939-204340` | `technical_depth` | 9.0 / 7.0 | reviewed/core gate 失败：本地事务内写入与事务外副作用边界只达到 partial |
| 5 | B shadow gate | `sess-20260607-153956-4deb1f` | `coding_quality` | 7.0 / 7.0 | reviewed/core gate 在 shadow 下失败：错误状态语义 partial；另有响应字段变更向后兼容缺口 |
| 6 | C no/missing | `codex-debug-48d46627d849` | `communication` | 7.5 / 7.5 | rubric 多项 missing：具体例子、Redis 展开、关键取舍说明不足 |
| 7 | C no/missing | `sess-20260513-123825-71291c` | `technical_depth` | 8.7 / 7.0 | acceptance `no`：未分析索引刷新间隔或写入延迟原因 |
| 8 | C no/missing | `sess-20260523-010354-7c61f1` | `system_design` | 8.26 / 7.0 | rubric missing：偏差控制与防雪崩的对账机制不足；老记录字段存在混杂，需要复核 |
| 9 | C no/missing | `sess-20260523-080938-02d85c` | `coding_quality` | 8.0 / 7.0 | acceptance `no`：测试或监控验证幂等正确性不足；rubric missing：向后兼容、测试验证 |
| 10 | C no/missing | `sess-20260526-133721-43e4d8` | `problem_solving` | 9.0 / 7.0 | acceptance `no`：只提到一种不一致来源或漏掉权衡讨论 |
| 11 | C no/missing | `sess-20260526-133721-43e4d8` | `system_design` | 8.5 / 7.0 | acceptance `no`：只讲缓存架构，不讨论一致性风险 |
| 12 | C no/missing | `sess-20260528-095532-df2e1b` | `problem_solving` | 7.9 / 7.0 | acceptance `no`：项目背景、个人职责或真实项目上下文不足 |
| 13 | C no/missing | `sess-20260529-162210-cceb99` | `coding_quality` | 7.966 / 7.0 | 多项 acceptance `no`：向后兼容、幂等机制、错误码设计不足 |
| 14 | C no/missing | `sess-20260529-162210-cceb99` | `system_design` | 8.28 / 7.0 | 多项 acceptance `no`：对账设计、故障后修复、量化数字不足 |
| 15 | C no/missing | `sess-20260530-081628-64435e` | `coding_quality` | 8.0 / 7.0 | rubric missing：向后兼容和版本演进；partial：幂等键字段和过期机制不完整 |
| 16 | C no/missing | `sess-20260531-015658-6f761c` | `system_design` | 7.5 / 7.0 | acceptance `no`：极端场景降级/熔断不足；rubric 多项 missing |
| 17 | C no/missing | `sess-20260531-084534-214e4a` | `problem_solving` | 9.0 / 7.0 | acceptance `no`：只提到去重但未说明修复方案；缺少审计 |
| 18 | C no/missing | `sess-20260607-060709-3d32de` | `coding_quality` | 8.0 / 7.0 | rubric missing：向后兼容和版本演进；partial：幂等业务键存储/校验机制 |
| 19 | C no/missing | `sess-20260607-182939-204340` | `project_experience` | 8.0 / 7.0 | acceptance `no`：未说明写入放大的来源 |
| 20 | D partial-only | `sess-20260607-023238-c547f4` | `problem_solving` | 7.0 / 7.0 | 只有 partial：验证有效性/鲁棒性、问题拆解、实现关键点不够完整 |

## 初步判断

1. A 类不建议现在放松。它们是 reviewed/core gate 明确拦截，至少从结构上是主链路认可的硬理由。
2. B 类先不动。它还在 shadow 语义或未强制语义里，适合继续作为观测样本。
3. C 类数量最多，但老记录混杂较多，不能直接说明 gate 过严。需要人工抽样判断这些 `no/missing` 是否真的硬到足以覆盖高分。
4. D 类是最干净的收敛入口：如果没有 `no`、没有 `missing`、没有 enforced gate，只是 `partial`，它更像软缺口，应该进入建议/追问，不应该直接把高分维度压成未通过。当前代码已按这个口径收敛 final_report 聚合层。

## C 类人工抽样初审

抽样原则：避开 debug session，优先覆盖近期真实面试和不同维度；同时保留少量老记录，用来判断旧 evaluator / legacy 字段是否污染 C 类。

| 样本 | 维度 | 分数 | 触发项 | 人工判断 | 建议 |
| --- | --- | ---: | --- | --- | --- |
| `sess-20260607-182939-204340` | `project_experience` | 8.0 / 7.0 | `compiled_fallback/supporting` 的 `no`: 未说明写入放大来源；`partial`: 压测和监控验证不够细 | 偏软。题目主目标是量化瓶颈、验证指标和一致性风险，回答已覆盖响应时间、成本、命中率、准确率、Redis/MySQL 状态校验；写入放大属于补充追问，不应单独覆盖高分 | 已纳入 C1 收敛规则：结构化 supporting `no/partial` 不直接压主链路 |
| `sess-20260607-060709-3d32de` | `coding_quality` | 8.0 / 7.0 | legacy `partial`: 幂等键存储/校验机制不够深；rubric `missing`: 向后兼容和版本演进策略 | 偏软。题目要求状态码、错误码、业务字段和重试幂等，回答已覆盖 requestId、唯一约束、TASK_ALREADY_PROCESSED、状态查询等；向后兼容不在题干显式要求里 | 可作为 C 类低风险收敛候选，但要限定为非 reviewed/core 且无 acceptance `no` |
| `sess-20260523-080938-02d85c` | `coding_quality` | 8.0 / 7.0 | legacy `no`: 测试/监控验证幂等正确性；rubric `missing`: 向后兼容、测试验证 | 中等风险。测试/监控对 coding_quality 可能是核心质量证据，但该记录是 legacy 形态，缺少 source/severity，且 rationale 写着“给予 8 分并标记通过” | 不适合直接驱动代码规则；应先通过题库/contract authoring 明确测试验证是否 core |
| `sess-20260526-133721-43e4d8` | `problem_solving` | 9.0 / 7.0 | legacy `no`: 文本本身是 `PARTIAL: 只提到一种不一致来源或漏掉权衡讨论` | 明显旧口径噪音。触发文本写着 PARTIAL 却被 legacy 统计成 no；回答和 rationale 都显示强通过 | 不作为主链路规则依据；用于 legacy 数据清洗或报表归因降噪 |
| `sess-20260529-162210-cceb99` | `system_design` | 8.28 / 7.0 | 多个 legacy `no/partial`: 对账、修复、指标量化、目标合理性等 | 混杂。部分答案实际提到了对账和修复，但 legacy 触发项仍判 no；同时多轮弱项确实集中在指标、SLA 依据和持续监控 | 不适合一刀释放；需要 reviewed/core 化后再判断哪些是硬缺口 |
| `sess-20260531-015658-6f761c` | `system_design` | 7.5 / 7.0 | legacy `no/missing` 很多，且存在 evaluator fallback 轮次污染 | 不适合用于产品口径判断。该 session 的若干 turn 显示 evaluator fallback rationale，但 final aggregation 仍带入大量 missing | 先排除在 C 类口径收敛样本之外，作为 fallback/legacy 报表污染问题单独处理 |

抽样结论：

1. C 类不能整体收敛，里面混有真缺口、软缺口、legacy 噪音和 fallback 污染。
2. 可以拆出一个较低风险的 C1 子类：高分、无 contract gate failure、无 reviewed/core failure，仅存在非 core/supporting 的 `no/missing` 或题干外 rubric missing。这类更像“可补齐项”，不应直接覆盖高分结论。当前代码已按这个口径收敛 final_report 聚合层。
3. legacy `no` 不能等价为硬缺口。部分老记录的触发文本本身带 `PARTIAL/YES`，但统计结果归成 `no`，直接用它改主链路会误伤。
4. 带 evaluator fallback 的样本应从 C 类口径收敛样本中剔除，否则会把“评分不可用/旧报表污染”误当成候选人能力缺口。

## 建议下一步

 最小风险收敛顺序：

1. D 类规则已处理：`partial-only` 高分维度不再进入主链路失败，也不会继续生成覆盖不足 warning。
2. C1 子类已处理：新结构化 `acceptance_check_result_items` 中仅有 supporting / adaptive 辅助缺口时，高分维度不再进入主链路失败；缺口仍保留在 evidence / weaknesses 中。
3. 暂不动 A 类 enforced gate，只检查 reviewed/core authoring 是否把软要求错误标成 core。
4. legacy/fallback 污染另开问题，不和 contract gate 口径收敛混在一起修。
