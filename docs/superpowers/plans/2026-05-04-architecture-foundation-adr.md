# 架构定调 ADR · 轻量 Harness + 面试 Workflow + 与文件系统解耦

> **状态：** Accepted (2026-05-04)
> **决策范围：** 整仓库长期架构基底
> **覆盖范围：** Agent 编排层 / Memory / 工具调度 / 状态管理 / 验证护栏 / Skill；不覆盖产品文案与发布形态（产品语言遵循 `2026-05-04-coach-positioning-alignment.md` v2 校准）

> **面向 AI 代理的工作者：** 必需子技能：使用 writing-plans。本 ADR 不含可执行任务；它只冻结架构叙事，防后续接手者走偏成"文件系统中心"或"过度多 Agent"。

## 上下文

项目最初考虑借鉴 Claude Code / Hermes Agent / OpenClaw 等成熟 Agent 架构：

- Content Engineering（上下文工程）
- Memory（跨会话记忆）
- 工具编排
- 状态管理
- 验证与护栏
- Skill / Subagent / Teammate 模式

但 Claude Code / Hermes / OpenClaw 都是桌面应用，对**文件系统**有紧密关联。直觉上担心的是：

> 项目目标交付形态是 Web SaaS 给 C 端面试用户，没有用户文件树，看上去这套 Harness 思路无法照搬。

## 决策

**Harness Engineering 的内核（抽象层）与文件操作（实现层）是解耦的。** 项目采用「轻量 Harness + 垂直领域 Workflow」混合架构，移植 Harness 内核，但不携带"代码仓为中心"的顶层工具集。

### Harness 内核映射表

| Harness 内核 | Claude Code 做法 | Hermes 做法 | 项目实现位置 |
|---|---|---|---|
| Content Engineering | system_prompt + CLAUDE.md + recent files snippet | program / declarative / episodic 三层拼接 | `app/engine/context/` slot-based ContextBuilder + `app/engine/agents/prompts/` |
| Memory | MEMORY.md + scoped recall | LRU cache + episodic | `app/memory/strategy_store` / `skill_store` / `llm_selector`；前端 `frontend/src/lib/storage/interviewHistory.ts` |
| 工具编排 | tool_use + parallel calling | bee/fly/spider tool family | `app/engine/workflow/nodes/` LangGraph node + `app/engine/agents/` 多 Agent |
| 状态管理 | ConvoState + tool_results | episodic state machine | `app/engine/workflow/state.py` + `app/services/session_manager.py` checkpointer |
| 验证与护栏 | hooks + pre-commit | review-mode subagent | `app/engine/agents/verifier.py` + `app/engine/agents/guard.py` + `app/ml/drift/` |
| Skill | SKILL.md + agent-skill registry | declarative knowledge slot | `knowledge/skills/` + `app/engine/context/` slot 加载 |
| Subagent / Teammate | spawn subagent + role isolation | role-tagged worker | LangGraph subgraph + 多 Agent 角色（generator / evaluator / verifier / guard / coach） |
| Generator-Evaluator 迭代合同（Anthropic） | gen + eval loop | 三 Agent 对抗 | Generator 出题 → Evaluator 评分 → Verifier drift → refine_followup |

### 不携带的部分（排除项）

| Claude Code / Hermes 携带 | 项目不携带 | 理由 |
|---|---|---|
| Read / Write / Edit / Grep / Bash 工具 | ✗ | 面试场景没有"用户工作目录"概念 |
| 工作目录 / .claude / SKILL.md 本地加载 | ✗ | 后端服务不能依赖个人本地文件 |
| Pre-commit hook / Post-tool hook | ✗ | 非编程助手 |
| 文件锁 / 跨进程锁 | ✗ | 集中式后端无此需求 |
| 多 tab IDE 上下文同步 | ✗ | 浏览器单 tab + 服务端 sessionId |
| Tool result 译为 diff / snippet | ✗ | 业务产出是 score / dimension / question，不是 diff |
| Token 计费反馈"另起新会话"建议 | ✗ | C 端用户不应感知 token 与窗口边界 |

### 顶层工具集替换

|（删）面向代码仓的工具 |（用）面向面试的工具 |
|---|---|
| Read / Write / Edit | ask_question / wait_answer |
| Grep | rag_retrieve（Chroma + BM25） |
| Bash | score_dimension / refine_followup |
| Tool result diff | dimension_scores + verdict + rubric |

## 决策的后果

### 正面

1. **能复用成熟抽象、避免自创轮子**：generator-evaluator 迭代、verifier 护栏、bandit 旁路、skill slot 都是经过验证的模式
2. **避免过度工程**：不引入"5 个 subagent + 3 个 hook"这种重型协作
3. **代码现状已对齐 70%**：LangGraph state、ContextBuilder、agents、skill_store、bandit、trace/outcome/reward 都已就位
4. **轻量上线友好**：阶段 1 不需要重构架构；阶段 2 加额度只需在 `_llm_override_var` 之后扩展中间件

### 反面 / 放弃的能力

1. **没有本地文件感知**：用户上传简历仍走 HTTP form，不能直接读用户磁盘
2. **没有跨进程文件锁**：项目内部使用 ContextVar + DB 行锁解决并发
3. **没有 IDE 集成**：用户不能在 VS Code 内调用面试官（不是项目目标场景）
4. **没有"自我反思 → 写文件"循环**：教练计划仍由 LLM 一次产出，不通过文件系统迭代

### 待办（不在本 ADR 范围）

- 阶段 1 上线前**不动**
- 阶段 2 加额度时按现有 Harness 抽象扩展（在 `_llm_override_var` 后加中间件，不重写）
- 阶段 3 商业化由业务总部决策

## 叙事保护（与 v2 校准对齐）

| 场景 | 是否使用「Harness」叙事 |
|---|---|
| 用户可见 README / 首页 / 对话气泡 | **不使用**。保持「AI 面试官 / 多维度反馈 / 成长规划」产品语言 |
| 工程师内部 ADR / 设计文档 | **使用**。包括本 ADR、`AI 面试官 Agentic Workflow 后端工程 Plan.md` |
| 跨参考知识库（reference/） | 可使用，对照 Claude Code / Hermes / OpenClaw 模式 |
| 接手者第一份阅读路径 | 先读 v2 校准 plan + 本 ADR + release-roadmap，再读后端代码 |

**铁律：**「Harness」是工程语言，不进入产品语言。`README.md` / `ai-interviewer/README.md` 顶部仍坚持「AI 面试官 + LangGraph + 多智能体」表述，不替换为「Harness Engineering」。

## BYOK key 安全保证

> 用户在前端 LLMSettingsDialog 填的 `api_key` **必然要传到服务器**——后端代用户调 LLM，是项目架构的固有事实。本节冻结当前代码已建立的三层防护，保证 key 在服务器内**只在内存里转一圈**、不落盘 / 不进日志 / 不进 trace。

### 三层防护

| 层 | 位置 | 行为 |
|---|---|---|
| 1. 内存传递 + 请求结束释放 | `app/services/session_manager.py` `_llm_override_var` + `temporary_llm_override` | key 仅存在于请求范围的 ContextVar；请求结束 `reset(token)` 释放 |
| 2. DB 落盘脱敏 | `app/services/session_manager.py` `_safe_llm_config_meta` | 落 `interview_sessions.llm_config_meta` 时移除全部 `api_key` 字段（含嵌套 `role_overrides.*.api_key`），仅保留 `requires_reauth` 布尔标志 |
| 3. 错误日志脱敏 | `app/engine/agents/llm_client.py` `redact_llm_secrets` | LLM provider 异常文本写入日志前替换 key 原文为 `[redacted-api-key]` |

### 防御性测试

`backend/tests/unit/test_llm_secret_redaction.py` 锁定上述三层契约：

- `_safe_llm_config_meta` 顶层 / 嵌套 `api_key` 均被剥离
- `_safe_llm_config_meta` `requires_reauth` 标志正确反映是否曾有 key
- `redact_llm_secrets` 正确替换错误文本中的顶层 / 嵌套 key
- 边界条件：`None` / 空 dict / 无 key 配置均不抛异常

未来 PR 若动到上述任一行为，CI 会立即拦下。

### 不可走的捷径

| 听起来更安全 / 实际不行 | 原因 |
|---|---|
| 让 key 完全不传服务器 | 后端调 LLM = 后端需 key；前端直连 = 跨域 + key 暴露给开发者工具与浏览器扩展 |
| 用临时 token 代替 key | OpenAI / Anthropic 主流 API 不提供「子代 token + 限额」机制；只能签发新 key（属用户责任） |
| 后端中转给上游 | 中转仍要拼 key 到 Authorization 头，只是多一跳 |

### 升级到 KMS / Vault 的触发条件

仅在以下情形之一成立时，再考虑把 BYOK key 从 ContextVar 升级到 KMS / Vault 加密存储：

- 进入 release-roadmap 阶段 2，多进程后端同时调用 LLM 需共享 key
- 出现合规要求（如等保 / SOC2）需要审计 key 生命周期
- 出现已知泄漏事件需要事后审计

阶段 0 / 1 不做，避免过度工程。

### 不在本节范围

- 平台 fallback key（后端 `.env` `OPENAI_API_KEY`）的保护：那是部署者职责，不是 BYOK 范畴
- 用户身份 / 鉴权：阶段 2 用户系统范畴
- 计费 / 额度：阶段 2 / 3 范畴

## 关联文档

| 文档 | 关系 |
|---|---|
| `docs/superpowers/plans/2026-05-04-coach-positioning-alignment.md` | v2 校准的产品语言定调 → 本 ADR 服从 |
| `docs/superpowers/plans/2026-05-04-release-roadmap.md` | 发布路径 C 双轨混合 → 本 ADR 是其前提 |
| `docs/superpowers/plans/2026-05-04-interview-mainline-improvements-plan.md` | 跨参考补强 audit → 本 ADR 提供长期指南 |
| `ai-interviewer/docs/AI 面试官 Agentic Workflow 后端工程 Plan.md` | 后端工程实现细节 → 受本 ADR 约束 |
| `reference/MEMORY.md` | 跨项目模式借鉴入口 → 本 ADR 决定借鉴哪些、不借鉴哪些 |

## 反例（防误读）

> "Harness 模式 = 必须有文件操作工具集"

错。文件操作只是 Claude Code 实现层选择，不是 Harness 内核。

> "项目采用 Harness 模式 = 要让用户能传文件给 AI"

错。简历上传走 `POST /api/v1/interview/resume/parse`，是面试场景的业务端点，不是 Harness 工具。

> "Harness Engineering = 必须用多 subagent 推动主链路"

错。LangGraph subgraph + 几个固定角色（gen / eval / verifier / guard / coach）足够。多生几个 subagent 不会带来价值，只会引入协调成本。

> "v2 校准强调面试主线 = 不能用 Harness 叙事"

错。v2 校准约束的是**产品语言**（用户可见处保留 AI 面试官 / 评分维度 / 报告等术语）；工程语言不受此约束。本 ADR 在工程层面用 Harness 表述完全合规。

## 下一次修订触发条件

仅在以下情形之一发生时修订本 ADR：

- 用户产品形态从 Web SaaS 转向桌面应用（违反 release-roadmap 的形态决策）
- 项目决定接入 IDE 插件场景（如 Cursor 内置面试官）
- 团队决定从 LangGraph 迁移到其他 orchestration 框架（如 CrewAI / AutoGen）

非以上场景下，**不修订本 ADR**。新需求若与 ADR 冲突，应先发起新 ADR 推翻本文，再动代码。

---

## 给下一个执行者的备注

- 本 ADR 不含任务，只是架构基线。
- 阶段 1 上线、阶段 2 用户系统、阶段 3 商业化，**全部继承本 ADR 的"轻量"约束**。
- 任何"加 5 个 subagent / 加文件操作工具 / 加多 IDE 同步"的提案，都需要先发起新 ADR 替换本文。
- 已有跨参考资料（`reference/projects/`）应作为模式来源，不应作为最新外部观点；用 `reference/topics/` 入口对照。
