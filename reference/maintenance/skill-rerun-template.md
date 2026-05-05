# Skill Rerun Template

## Scope
Use this file to rerun the four cases most sensitive to the latest `SKILL.md` changes:
- `P3`
- `P4`
- `P12`
- `B1`

## Before You Run
- Restart Codex first so the updated installed skill is loaded.
- Use a fresh thread for each case if possible.
- For this rerun, the main checks are:
  - Does the visible answer show the route first?
  - Does it lead with `Topics` or `Projects` instead of raw docs?
  - Does it stay inside `navigation + pattern extraction + source map`?

## Paste Template
Fill one block per test.

```md
## Test ID
P3

## Mode
Auto

## Prompt
Claude Code 和 OpenClaw 在 context engineering 上最大的差别是什么？

## Response
<把 Codex 的完整回复贴这里>

## Skill Signal
unknown

## Notes
<可选>
```

## Rerun Cases

```md
## Test ID
P3

## Mode
Auto

## Prompt
Claude Code 和 OpenClaw 在 context engineering 上最大的差别是什么？

## Response
<**Route**

这题我走的是主题卡 [Context Engineering](/D:/Agent/Agentic_Interviewer/reference/topics/context-engineering.md)，再用项目卡 [Claude Code](/D:/Agent/Agentic_Interviewer/reference/projects/claude-code.md) 和 [OpenClaw](/D:/Agent/Agentic_Interviewer/reference/projects/open-claw.md) 做对照；最后回到最小原始资料集验证了两边的实现边界。

**Pattern Extraction**

最大的差别可以压成一句话：

**Claude Code 把 context engineering 做成“内建、固定分层、强预算意识”的上下文装配流水线；OpenClaw 把它做成“平台级、可替换”的上下文治理槽位。**

更具体地说：

- Claude Code 的核心是一个很明确的三层模型：
  - `systemPrompt` 静态骨架
  - `systemPrompt` 动态区
  - `messages` 侧运行时事实流
- 它连 `MEMORY.md`、`topic files`、`relevant_memories`、`nested_memory`、attachments、prompt cache boundary、compaction 都放进同一条装配链里协同优化。
- 所以 Claude Code 关心的是：**哪些内容进哪个通道、何时注入、如何保持 cache-friendly、如何按路径和语义最小注入。**

而 OpenClaw 的重心不一样：

- 它把 Context Engine 定义成独占的 `context-engine` slot，可以 `registerContextEngine(...)`，再由配置选择 active engine。
- 这个 engine 通过 `bootstrap / ingest / assemble / compact / afterTurn / prepareSubagentSpawn / onSubagentEnded` 这些生命周期钩子接管上下文治理。
- 默认 `legacy` 更像兼容层，说明 OpenClaw 的重点是：**把上下文策略从 Agent 主循环里解耦出来，成为可替换的 control-plane/runtime 边界。**

所以如果只问“最大的差别是什么”，我的结论是：

**Claude Code 更像“上下文装配产品学”**  
它已经强定义了最佳实践：三层分流、路径感知记忆、运行期 attachments、cache 边界、compaction 耦合。

**OpenClaw 更像“上下文治理平台学”**  
它先定义 slot、生命周期和 session-first 架构，让“上下文怎么装配”成为一个可替换策略，而不是写死的一套产品内核。

换个更直白的表述：

- Claude Code 在回答：“怎样把 coding agent 的上下文喂得最准、最省、最稳？”
- OpenClaw 在回答：“上下文策略应该放在系统的哪一层，怎么和 session、memory、subagent、plugin 解耦？”

**Source Map**

如果你想继续往下验证，最值得读的是：

- [reference/claude-code/context-engineering.md](/D:/Agent/Agentic_Interviewer/reference/claude-code/context-engineering.md)
- [reference/claude-code/memory-system.md](/D:/Agent/Agentic_Interviewer/reference/claude-code/memory-system.md)
- [reference/open-claw/phase9_ Context Engine.md](/D:/Agent/Agentic_Interviewer/reference/open-claw/phase9_%20Context%20Engine.md)
- [reference/open-claw/phase7_ Session 与状态管理.md](/D:/Agent/Agentic_Interviewer/reference/open-claw/phase7_%20Session%20%E4%B8%8E%E7%8A%B6%E6%80%81%E7%AE%A1%E7%90%86.md)

如果你愿意，我下一步可以继续把这个差别再压成一张“Claude Code vs OpenClaw context engineering 对照表”。>

## Skill Signal
unknown

## Notes
重点看是否先点名 `context-engineering` topic，再做对比。
```

```md
## Test ID
P4

## Mode
Auto

## Prompt
跨 Claude Code、Hermes、OpenClaw 看，memory 和 retrieval 应该怎么分层？

## Response
<**Route**

这题我先走了 [Memory And Retrieval](/D:/Agent/Agentic_Interviewer/reference/topics/memory-and-retrieval.md)，再用 [Claude Code](/D:/Agent/Agentic_Interviewer/reference/projects/claude-code.md)、[Hermes Agent](/D:/Agent/Agentic_Interviewer/reference/projects/hermes-agent.md)、[OpenClaw](/D:/Agent/Agentic_Interviewer/reference/projects/open-claw.md) 做交叉校正。

**Pattern Extraction**

跨这三套系统，最稳的分层不是“一个 memory 层 + 一个 RAG 层”，而是至少拆成 **5 层**：

1. **长期知识层**
   - 存“跨 session 仍然值得保留”的东西，而且要人可读。
   - Claude Code: `MEMORY.md + topic files`
   - Hermes: `MEMORY.md / USER.md` 这类 declarative memory
   - OpenClaw: `MEMORY.md + memory/*.md`

2. **知识类型分层**
   - 至少要把这三类分开：
   - `declarative`：事实、偏好、约束、项目背景
   - `procedural`：怎么做，最好沉淀成 skill / workflow
   - `episodic`：这次会话里发生了什么，也就是 transcript / session history
   - Hermes 在这层最清楚，直接拆成 procedural / declarative / episodic；这是三者里最值得复用的模式。

3. **检索入口层**
   - 不要拿正文直接当入口，要有“索引页 / 候选清单 / 目录层”。
   - Claude Code 的典型做法是 `MEMORY.md` 只做 index，topic file 才是正文。
   - Hermes 是 skills index 先让模型看到“有哪些方法”。
   - OpenClaw 是 `memory_search -> memory_get`，先粗召回，再精读局部。

4. **会话侧材料层**
   - transcript 不等于长期 memory。
   - 它应该单独存在，承担“恢复、审计、压缩前原始依据”的角色。
   - Claude Code: transcript 是底账，真正 recall 时只窄搜。
   - Hermes: episodic experience 和 session search 不应直接混成长期知识。
   - OpenClaw: `transcript`、`SessionEntry`、`activeSession.messages`、`compaction summary` 是并行链，不是一个东西。

5. **工作记忆层**
   - 真正喂给模型的永远应该是“当前最小必要子集”，不是整个知识库。
   - Claude Code: `relevant_memories` / `nested_memory` attachment 注入
   - Hermes: skill 正文只在相关时 `skill_view()` 加载
   - OpenClaw: `memory_search` 找候选，`memory_get` 取片段，compaction summary 保持短期连续性

如果把它压成一句设计原则：

**长期知识要文件化，程序性知识要单独成 skill，episodic history 要留在 transcript，retrieval 要先索引后精读，working memory 只拿最小相关片段。**

再压缩成一个跨项目统一模型：

- `Layer 1 durable knowledge`
  - `MEMORY.md` / topic files / memory files / USER facts
- `Layer 2 procedural knowledge`
  - skills / workflows / reusable recipes
- `Layer 3 episodic history`
  - transcript / session logs / experience replay
- `Layer 4 retrieval surface`
  - index、manifest、search、selector、`memory_search`
- `Layer 5 active working set`
  - relevant recalls、loaded skills、compaction summary、current messages

其中最重要的边界是：

- **memory 不是 transcript**
- **skill 不是普通 memory note**
- **retrieval 不是把全文塞进 prompt**
- **compaction summary 不是长期知识**

**Source Map**

继续深读的话，最值得看的原始卡片是：

- [reference/claude-code/memory-system.md](/D:/Agent/Agentic_Interviewer/reference/claude-code/memory-system.md)
- [reference/hermes-agent/hermes-closed-loop-learning-analysis.md](/D:/Agent/Agentic_Interviewer/reference/hermes-agent/hermes-closed-loop-learning-analysis.md)
- [reference/open-claw/phase8_ 记忆、多模态与能力服务.md](/D:/Agent/Agentic_Interviewer/reference/open-claw/phase8_%20%E8%AE%B0%E5%BF%86%E3%80%81%E5%A4%9A%E6%A8%A1%E6%80%81%E4%B8%8E%E8%83%BD%E5%8A%9B%E6%9C%8D%E5%8A%A1.md)
- [reference/open-claw/phase7_ Session 与状态管理.md](/D:/Agent/Agentic_Interviewer/reference/open-claw/phase7_%20Session%20%E4%B8%8E%E7%8A%B6%E6%80%81%E7%AE%A1%E7%90%86.md)

如果你想，我下一步可以把这 5 层直接展开成一张“你自己系统该怎么落表、落文件、落工具接口”的映射表。>

## Skill Signal
unknown

## Notes
重点看是否先点名 `memory-and-retrieval` topic，且不要直接滑成你的底座设计方案。
```

```md
## Test ID
P12

## Mode
Auto

## Prompt
ACO 里 business loop 和 three-loop boundary 分别在哪几篇？先给我导航。

## Response
<**Route**

先从项目卡进，不要直接散读原文：

- [agentic-content-optimizer.md](/D:/Agent/Agentic_Interviewer/reference/projects/agentic-content-optimizer.md)

这张卡已经把你这两个点分开了：

- `business loop` 主要去看 [LANGGRAPH_WORKFLOW_BUSINESS_LOOP.md](/D:/Agent/Agentic_Interviewer/reference/Agentic-Content-Optimizer/LANGGRAPH_WORKFLOW_BUSINESS_LOOP.md)
- `three-loop boundary` 主要去看 [混合架构中的底座与三层Loop边界.md](/D:/Agent/Agentic_Interviewer/reference/Agentic-Content-Optimizer/混合架构中的底座与三层Loop边界.md)

**Fast Path**

如果你想按最省时间的顺序读：

1. 先看 [混合架构中的底座与三层Loop边界.md](/D:/Agent/Agentic_Interviewer/reference/Agentic-Content-Optimizer/混合架构中的底座与三层Loop边界.md)
   这篇负责把 `tool loop / workflow loop / node-local loop` 的边界讲清。
2. 再看 [LANGGRAPH_WORKFLOW_BUSINESS_LOOP.md](/D:/Agent/Agentic_Interviewer/reference/Agentic-Content-Optimizer/LANGGRAPH_WORKFLOW_BUSINESS_LOOP.md)
   这篇负责把 ACO 现在那条 LangGraph 业务闭环怎么跑讲清。

**Supporting Cards**

如果你读完还想补一层“概念导航”而不是继续扎原文：

- [workflow-orchestration.md](/D:/Agent/Agentic_Interviewer/reference/topics/workflow-orchestration.md)
  对应 `business loop`
- [control-plane-and-runtime-boundaries.md](/D:/Agent/Agentic_Interviewer/reference/topics/control-plane-and-runtime-boundaries.md)
  对应 `three-loop boundary`

如果你愿意，我下一条可以继续帮你做一版“这两篇分别该看哪些段落”的二级导航。>

## Skill Signal
unknown

## Notes
重点看是否先点名 `projects/agentic-content-optimizer.md`，而不是一上来先列 raw docs。
```

```md
## Test ID
B1

## Mode
Auto

## Prompt
我想设计一个 Agentic Workflow 控制底座，你先给我三种可选架构。

## Response
<**Route**
先走 [control-plane-and-runtime-boundaries.md](<D:/Agent/Agentic_Interviewer/reference/topics/control-plane-and-runtime-boundaries.md>)，辅以 [workflow-orchestration.md](<D:/Agent/Agentic_Interviewer/reference/topics/workflow-orchestration.md>) 和 [memory-and-retrieval.md](<D:/Agent/Agentic_Interviewer/reference/topics/memory-and-retrieval.md>)。下面这轮先给你“参考引导的三种架构原型”，不直接替你拍最终版。

**三种可选架构**
1. 平台控制面型  
核心是 `Gateway / Auth / Routing / Session / Event Bus / Cron / Node Registry / Agent Runtime` 分层。`Session` 是状态锚点，不等于 prompt；`Context` 是单独的装配策略；业务 workflow 放在底座之上。适合多入口、多会话、强治理、后续要接 UI/API/自动化/外部通道的场景。代价是前期最重。

2. 运行时内核型  
核心是 `Conversation Orchestrator / Turn State Machine / Tool Executor / Context Compaction / Recovery Loop`。先把单个 agent 主循环、工具调用、恢复与上下文治理做扎实，再把 API/UI 当薄壳接上。适合先做一个强执行的 agent runtime。代价是后面补 Gateway、调度、会话治理时，通常还要再补一层平台壳。

3. 三层 Loop 混合型  
核心是 `tool loop + workflow loop + node-local loop`。底座负责 session、tool/skill/MCP、权限、审计、追踪；workflow 负责共享 state、节点顺序、质量阈值、终止条件；节点内部再做 retry/fallback/re-eval。`trace/outcome/reward` 的业务语义留在 workflow 层，持久化与治理放到底座层。这个最像“Agentic Workflow 控制底座”，也是我最推荐的方案。

**怎么选**
如果你要先做“平台化多入口”，选 1。  
如果你要先做“强 agent runtime”，选 2。  
如果你要同时兼顾“控制面 + 工作流闭环 + 后续扩展”，选 3。

**Source Map**
入口卡片：
[control-plane-and-runtime-boundaries.md](<D:/Agent/Agentic_Interviewer/reference/topics/control-plane-and-runtime-boundaries.md>)  
[workflow-orchestration.md](<D:/Agent/Agentic_Interviewer/reference/topics/workflow-orchestration.md>)  
[memory-and-retrieval.md](<D:/Agent/Agentic_Interviewer/reference/topics/memory-and-retrieval.md>)  

原始参考：
[phase2_ Gateway 与控制平面.md](<D:/Agent/Agentic_Interviewer/reference/open-claw/phase2_ Gateway 与控制平面.md>)  
[phase3_ Agent 运行时与会话编排.md](<D:/Agent/Agentic_Interviewer/reference/open-claw/phase3_ Agent 运行时与会话编排.md>)  
[agent-loop.md](<D:/Agent/Agentic_Interviewer/reference/claude-code/agent-loop.md>)  
[混合架构中的底座与三层Loop边界.md](<D:/Agent/Agentic_Interviewer/reference/Agentic-Content-Optimizer/混合架构中的底座与三层Loop边界.md>)

下一步我建议把第 3 种展开成一张模块图和边界清单。你更偏“平台型多入口”，还是“垂直 workflow 闭环”？>

## Skill Signal
unknown

## Notes
重点看是否仍然停留在 `reference-guided patterns`，而不是直接给出最终业务架构方案。
```

## Quick Score Table
Use this after the rerun if you want a fast pass/fail summary.

| ID | invoked | route_ok | contract_ok | Notes |
| --- | --- | --- | --- | --- |
| P3 |  |  |  |  |
| P4 |  |  |  |  |
| P12 |  |  |  |  |
| B1 |  |  |  |  |
