# Agentic Interviewer 文档索引

这个目录保存项目级公开文档：它们面向 GitHub 读者、面试讲解、演示准备和上线前检查。历史实施计划已归档到 `archive/`，不再作为主要阅读入口。

## 推荐阅读路径

### 快速了解项目

- [项目架构一页纸](<./项目架构一页纸.md>)：用一页说明 workflow runtime、控制面、数据层和生产化边界。
- [控制面与权限边界说明](<./控制面与权限边界说明.md>)：说明账号归属、匿名记录、平台额度、BYOK、Admin role 和生产预检的边界。
- [Phase 3.0 产品与上线决策](<./PHASE_3_0_产品与上线决策.md>)：说明为什么项目在当前阶段收口，以及哪些能力有意延后。

### 本地运行与验证

- [本地开发命令速查](<./本地开发命令速查.md>)：常用 Docker、后端、前端、测试和排障命令。
- [Production Readiness Runbook](./PRODUCTION_READINESS_RUNBOOK.md)：生产环境变量、预检规则、smoke drill、排障和回滚建议。
- [Session Anchor RAG Rollout Runbook](./RESUME_RAG_ROLLOUT.md)：候选人材料 RAG 的 rollout、shadow 指标、缓存和回滚策略。
- [Evaluation Baseline Hook](./EVALUATION_BASELINE_HOOK.md)：记录“拒绝玄学自评”的后续评估层接入点，等真人标注样本具备后再做基线对比。

### 简历与面试准备

- [简历与面试讲解稿](<./简历与面试讲解稿.md>)：简历 bullet、30 秒/2 分钟讲解、深挖问答和项目收口口径。

## 归档文档

`archive/` 保存早期设计与执行计划，用于追溯工程决策，不建议作为第一次阅读入口。

- `archive/implementation-plans/`：项目级与 Superpowers 生成的实现计划。
- `archive/backend-plans/`：后端专项计划、优化计划和架构风险记录。
- `archive/frontend-plans/`：前端早期交付计划。
- `archive/demo-artifacts/`：早期 demo / LangSmith 素材说明。

## 文档维护原则

- README 和本目录主文档只链接远程仓库中真实存在、可阅读的文件。
- 本地 agent 计划、复盘和临时审查默认不进入公开文档树。
- 新增公开文档时，优先服务“项目是什么、如何演示、如何运行、如何解释工程边界”。
- 如果只是一次任务执行计划，优先放入本地工作区；确实需要保留时放入 `archive/`。
