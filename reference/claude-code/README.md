# 模块架构文档

## 这一组文档解决什么问题

现有 `docs/` 已经把 Claude Code 的很多能力讲清楚了，但更多是白皮书式说明。  
这组 `module-docs/` 的目标更偏向源码架构解读：

- 明确每个模块由哪些核心目录和文件提供服务
- 说明模块在运行期的执行流程，而不是只讲概念
- 总结模块背后的开发范式和工程抽象
- 判断它为什么能被称为 Harness Engineering
- 为后续继续补厚细节留出“下一轮深挖入口”

## 阅读前提

这个仓库是一个逆向/裁剪版本：

- 真实入口仍然是 `src/entrypoints/cli.tsx`
- `feature()` 在当前构建里被固定为 `false`
- 一部分 Anthropic 内部能力仍保留架构骨架，但在这个版本里被关掉或桩化

这意味着：  
我们仍然能非常清楚地看到系统设计，但不能把所有分支都当成“当前构建一定活跃”的运行路径。

## 模块地图

| 模块 | 重点源码 | 本文档关注点 |
| --- | --- | --- |
| Agent Loop | `src/QueryEngine.ts`, `src/query.ts`, `src/services/tools/*` | 对话循环、工具回填、恢复机制、状态机 |
| Context Engineering | `src/context.ts`, `src/utils/systemPrompt.ts`, `src/utils/attachments.ts`, `src/utils/claudemd.ts` | Prompt 组装、上下文分层、缓存边界、动态附件 |
| 记忆系统 | `src/memdir/*`, `src/utils/claudemd.ts`, `src/tools/AgentTool/agentMemory.ts` | 文件化记忆、召回、作用域、子代理记忆 |
| 工具 / Skill / MCP | `src/Tool.ts`, `src/tools.ts`, `src/skills/*`, `src/services/mcp/*` | 能力总线、适配层、声明式元数据、外部能力接入 |
| 安全与约束 | `src/hooks/useCanUseTool.tsx`, `src/utils/permissions/*`, `src/utils/sandbox/*`, `src/services/policyLimits/*` | 权限判定链、自动模式约束、沙箱、组织策略 |
| Multi-Agent | `src/tools/AgentTool/*`, `src/utils/forkedAgent.ts`, `src/tools/shared/spawnMultiAgent.ts`, `src/tools/SendMessageTool/*` | 子代理运行时、上下文继承、隔离、通信协议 |

## 阅读顺序建议

如果你是为了真正“理解这套系统为什么高级”，建议按下面顺序看：

1. [Agent Loop](./agent-loop.md)
2. [Context Engineering](./context-engineering.md)
3. [记忆系统](./memory-system.md)
4. [工具、Skill 与 MCP](./tools-skills-mcp.md)
5. [安全与约束](./safety-and-constraints.md)
6. [Multi-Agent 架构](./multi-agent-architecture.md)

原因很简单：

- `Agent Loop` 决定系统如何运行
- `Context` 和 `Memory` 决定系统如何“理解当前任务”
- `Tools / Skill / MCP` 决定系统能做什么
- `Safety` 决定系统做这些事时是否可控
- `Multi-Agent` 决定系统如何扩展到更复杂的协作场景

## 这组文档的分析边界

这批文档暂时仍然坚持“系统架构和实现流程优先”的边界：

- 会引用关键类型、关键函数名、关键执行路径
- 但不会把每个函数逐行拆开
- 会重点解释为什么代码会被这样组织
- 会持续给出“下一轮可以继续深挖”的接口

这正适合我们后续按模块继续补厚：

- 哪个模块不清楚，就继续把那个模块往下压
- 哪条执行链不清楚，就单独做时序图
- 哪个抽象最值得学，就继续拔高为设计模式总结

## 与现有文档的关系

这组文档不是替代现有 `docs/`，而是把它们“落到代码”：

- `docs/conversation/*` 更像产品层解释
- `docs/context/*` 更像机制说明
- `docs/extensibility/*` 更像能力说明
- `module-docs/*` 则更强调“代码怎样把这些能力串成一个 runtime”

## 下一步怎么继续补厚

后面如果你希望继续深化，我们可以按下面三种方式扩展：

- 做模块级时序图：例如“用户输入到一次完整 tool loop 的全链路”
- 做源码分层图：例如“REPL / QueryEngine / query / API / tool runtime 的控制边界”
- 做设计模式专题：例如“为什么它的上下文工程不是简单 Prompt Engineering”

这也是这组文档的价值：  
先把架构地图搭起来，后面再逐块深挖，而不是每次都从零重建理解。
